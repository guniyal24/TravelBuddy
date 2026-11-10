"""FastAPI entrypoint. Services are created in the lifespan and stored on app.state,
so tests can build the app with fakes instead of real Neo4j / Pinecone / OpenAI."""
import json
import logging
import queue
import threading
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from app.api import security
from app.api.ratelimit import RateLimiter, RateLimitExceeded, connect_redis
from app.config import Settings, get_settings
from app.graph.trip_graph import PlanningUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")
GUEST_PREFIX = "guest:"  # guest subjects are never valid emails, so they cannot be registered
KEEPALIVE_SECONDS = 15  # comment lines keep proxies from closing a quiet event stream


# --- schemas ---
class UserRegister(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    guest: bool = False


class ChatRequest(BaseModel):
    query: str
    history: list[dict] = []


class TripStart(BaseModel):
    text: str


class TripResume(BaseModel):
    value: str | dict  # ask: text; choose: option id; approve: {"action": ..., "text"?: ...}


class TripReplan(BaseModel):
    from_day: int
    reason: str


class ChecklistUpdate(BaseModel):
    item_id: str
    done: bool


class FeedbackRequest(BaseModel):
    session_id: str
    query: str
    rating: int
    comment: str | None = None


# --- lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Heavy services are only built here if the app was not pre-wired (tests pre-wire).
    if not hasattr(app.state, "store"):
        from app.db.graph import GraphStore
        from app.rag.factory import build_self_rag, build_trip_planner

        s: Settings = app.state.settings
        app.state.store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
        redis_client = connect_redis(s.redis_host, s.redis_port)
        app.state.limiter = RateLimiter(redis_client, s.rate_limit_per_minute)
        if s.rag_mode == "hybrid":
            # imported only when used: it loads a re-ranking model (heavy on a 512 MB instance)
            from app.rag.hybrid import HybridRAG

            app.state.rag = HybridRAG(s, app.state.store, redis_client)
        else:
            app.state.rag = build_self_rag(s, app.state.store, redis_client)
        if s.memory_enabled:
            from app.memory import TravelMemory

            app.state.memory = TravelMemory.open(s.database_url or s.memory_path)
        app.state.planner = build_trip_planner(s, app.state.store, redis_client,
                                               getattr(app.state, "memory", None))
    if not hasattr(app.state, "trips"):
        from app.trips.store import TripStore

        s = app.state.settings
        app.state.trips = TripStore(s.database_url or s.trips_path)
    yield
    planner = getattr(app.state, "planner", None)
    tools = getattr(planner, "tools", None)
    if tools is not None and hasattr(tools, "close"):
        tools.close()
    if planner is not None and hasattr(planner, "graph"):
        from app.graph.persistence import close_checkpointer

        close_checkpointer(getattr(planner.graph, "checkpointer", None))
    store = getattr(app.state, "store", None)
    if store is not None and hasattr(store, "close"):
        store.close()
    trips = getattr(app.state, "trips", None)
    if trips is not None and hasattr(trips, "close"):
        trips.close()
    memory = getattr(app.state, "memory", None)
    if memory is not None:
        memory.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Uttarakhand Planner API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PlanningUnavailable)
    async def planning_unavailable(request: Request, exc: PlanningUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    # --- dependencies ---
    async def current_user(request: Request, token: str = Depends(oauth2_scheme)) -> dict:
        unauthorized = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        s: Settings = request.app.state.settings
        payload = security.decode_token(token, s.secret_key, s.jwt_algorithm)
        email = payload.get("sub") if payload else None
        if not email:
            raise unauthorized
        if payload.get("guest"):
            if not s.guest_enabled or not email.startswith(GUEST_PREFIX):
                raise unauthorized
            return {"email": email, "guest": True}
        user = request.app.state.store.get_user(email)
        if user is None:
            raise unauthorized
        return user

    async def rate_limited_user(request: Request, user: dict = Depends(current_user)) -> dict:
        s: Settings = request.app.state.settings
        limiter = request.app.state.limiter
        limit = s.guest_rate_limit_per_minute if user.get("guest") else limiter.limit
        try:
            limiter.check(user["email"], limit=limit)
        except RateLimitExceeded:
            raise HTTPException(
                status_code=429, detail=f"Rate limit exceeded ({limit} req/min)."
            ) from None
        return user

    # --- routes ---
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/register")
    async def register(body: UserRegister, request: Request):
        store = request.app.state.store
        if store.get_user(body.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        store.create_user(body.email, security.hash_password(body.password))
        return {"message": "User created successfully"}

    @app.post("/api/token", response_model=Token)
    async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
        s: Settings = request.app.state.settings
        user = request.app.state.store.get_user(form.username)
        if not user or not security.verify_password(form.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = security.create_access_token(
            {"sub": user["email"]},
            s.secret_key,
            s.jwt_algorithm,
            s.access_token_expire_minutes,
        )
        return {"access_token": token, "token_type": "bearer"}

    @app.post("/api/guest", response_model=Token)
    async def guest(request: Request):
        """A short-lived token for trying the app without an account."""
        s: Settings = request.app.state.settings
        if not s.guest_enabled:
            raise HTTPException(status_code=404, detail="Guest mode is turned off.")
        # Behind a proxy, uvicorn must be told to trust X-Forwarded-For (see Dockerfile) for this
        # to be the visitor's address. The daily cap bounds cost even if the header is spoofed.
        ip = request.client.host if request.client else "unknown"
        limiter = request.app.state.limiter
        try:
            limiter.check(f"guest-ip:{ip}", limit=s.guest_sessions_per_ip_per_hour, window=3600)
        except RateLimitExceeded:
            raise HTTPException(status_code=429, detail="Too many guest sessions from your "
                                "network. Please create a free account.") from None
        try:
            limiter.check("guest-all", limit=s.guest_sessions_per_day, window=86400)
        except RateLimitExceeded:
            raise HTTPException(status_code=429, detail="The demo is busy today. Please create a "
                                "free account to keep planning.") from None
        token = security.create_access_token(
            {"sub": f"{GUEST_PREFIX}{uuid.uuid4()}", "guest": True},
            s.secret_key, s.jwt_algorithm, s.guest_token_expire_minutes)
        return {"access_token": token, "token_type": "bearer", "guest": True}

    @app.post("/api/chat")
    async def chat(
        body: ChatRequest,
        request: Request,
        x_session_id: str | None = Header(None),
        user: dict = Depends(rate_limited_user),
    ):
        session_id = x_session_id or str(uuid.uuid4())
        log.info("chat user=%s session=%s", user["email"], session_id)
        rag = request.app.state.rag
        return StreamingResponse(
            rag.get_answer(body.query, session_id, body.history),
            media_type="text/event-stream",
            headers={"X-Session-ID": session_id},
        )

    def _trip_response(request: Request, trip_id: str, result: dict, owner: str) -> dict:
        out = {"trip_id": trip_id, "status": result["status"]}
        if result["status"] == "waiting":
            out["prompt"] = result["prompt"]
            return out
        out["itinerary"] = result.get("itinerary")
        structured = (result.get("state") or {}).get("structured")
        if result["status"] == "done" and structured:
            trips = request.app.state.trips
            trips.save_trip(trip_id, owner, structured)
            trips.learn(owner, structured["request"])  # remember preferences for next time
            out["trip"] = trips.get_trip(trip_id)
        return out

    def _event_stream(request: Request, trip_id: str, owner: str,
                      run: Callable[..., dict]) -> StreamingResponse:
        """Run the planner on its own thread and stream its progress as Server-Sent Events.

        Events: {"type": "progress", ...agent step...} while it works, then exactly one
        {"type": "result", ...same body as the JSON endpoint...} or {"type": "error", "detail"}.
        The run finishes and is saved even if the client disconnects half way.
        """
        events: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                result = run(on_event=lambda ev: events.put({"type": "progress", **ev}))
                events.put({"type": "result", **_trip_response(request, trip_id, result, owner)})
            except (ValueError, PlanningUnavailable) as exc:  # messages safe to show
                events.put({"type": "error", "detail": str(exc)})
            except Exception:
                log.exception("trip run failed trip=%s", trip_id)
                events.put({"type": "error",
                            "detail": "Planning failed on the server. Please try again."})
            finally:
                events.put(None)

        threading.Thread(target=work, name=f"trip-{trip_id[:8]}", daemon=True).start()

        def body():
            while True:
                try:
                    ev = events.get(timeout=KEEPALIVE_SECONDS)
                except queue.Empty:
                    yield ": keep-alive\n\n"
                    continue
                if ev is None:
                    return
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

        return StreamingResponse(body(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _owned_trip(request: Request, trip_id: str, user: dict) -> None:
        owner = request.app.state.planner.owner(trip_id)  # stored in durable trip state
        if owner is None:
            raise HTTPException(status_code=404, detail="Trip not found")
        if owner != user["email"]:
            raise HTTPException(status_code=403, detail="Not your trip")

    def _saved_trip(request: Request, trip_id: str, user: dict) -> dict:
        trip = request.app.state.trips.get_trip(trip_id)
        if trip is None:
            raise HTTPException(status_code=404, detail="Trip not found")
        if trip["owner"] != user["email"]:
            raise HTTPException(status_code=403, detail="Not your trip")
        return trip

    @app.get("/api/profile")
    async def get_profile(request: Request, user: dict = Depends(current_user)):
        return request.app.state.trips.get_profile(user["email"])

    @app.put("/api/profile")
    async def put_profile(body: dict, request: Request, user: dict = Depends(current_user)):
        return request.app.state.trips.save_profile(user["email"], body)

    # Trip endpoints answer with JSON, or with a live event stream of the agents' work when
    # called with ?stream=true.
    @app.post("/api/trips")
    async def start_trip(body: TripStart, request: Request, stream: bool = False,
                         user: dict = Depends(rate_limited_user)):
        trip_id = str(uuid.uuid4())
        profile = request.app.state.trips.get_profile(user["email"])
        planner = request.app.state.planner
        if stream:
            return _event_stream(request, trip_id, user["email"], lambda on_event: planner.start(
                trip_id, body.text, user["email"], profile, on_event=on_event))
        result = await run_in_threadpool(planner.start, trip_id, body.text, user["email"], profile)
        return _trip_response(request, trip_id, result, user["email"])

    @app.get("/api/trips")
    async def list_trips(request: Request, user: dict = Depends(current_user)):
        return request.app.state.trips.list_trips(user["email"])

    @app.get("/api/trips/{trip_id}")
    async def get_trip(trip_id: str, request: Request, user: dict = Depends(current_user)):
        return _saved_trip(request, trip_id, user)

    @app.post("/api/trips/{trip_id}/resume")
    async def resume_trip(trip_id: str, body: TripResume, request: Request, stream: bool = False,
                          user: dict = Depends(rate_limited_user)):
        _owned_trip(request, trip_id, user)
        planner = request.app.state.planner
        if stream:
            return _event_stream(request, trip_id, user["email"], lambda on_event: planner.resume(
                trip_id, body.value, on_event=on_event))
        result = await run_in_threadpool(planner.resume, trip_id, body.value)
        return _trip_response(request, trip_id, result, user["email"])

    @app.post("/api/trips/{trip_id}/replan")
    async def replan_trip(trip_id: str, body: TripReplan, request: Request, stream: bool = False,
                          user: dict = Depends(rate_limited_user)):
        _owned_trip(request, trip_id, user)
        if not body.reason.strip():
            raise HTTPException(status_code=400, detail="Tell me what changed.")
        planner, reason = request.app.state.planner, body.reason.strip()[:500]
        if stream:
            return _event_stream(request, trip_id, user["email"], lambda on_event: planner.replan(
                trip_id, body.from_day, reason, on_event=on_event))
        try:
            result = await run_in_threadpool(planner.replan, trip_id, body.from_day, reason)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return _trip_response(request, trip_id, result, user["email"])

    @app.put("/api/trips/{trip_id}/checklist")
    async def update_checklist(trip_id: str, body: ChecklistUpdate, request: Request,
                               user: dict = Depends(current_user)):
        _saved_trip(request, trip_id, user)
        if not request.app.state.trips.set_check(trip_id, body.item_id, body.done):
            raise HTTPException(status_code=404, detail="No such checklist item")
        return {"item_id": body.item_id, "done": body.done}

    @app.get("/api/trips/{trip_id}/export")
    async def export_trip(trip_id: str, request: Request, format: str = "txt",
                          start: str | None = None, user: dict = Depends(current_user)):
        from app.export.ics import build_ics
        from app.export.share import build_pdf, build_share_text

        trip = _saved_trip(request, trip_id, user)
        if format == "txt":
            return Response(build_share_text(trip), media_type="text/plain; charset=utf-8")
        if format == "pdf":
            return Response(build_pdf(trip), media_type="application/pdf", headers={
                "Content-Disposition": 'attachment; filename="uttarakhand-trip.pdf"'})
        if format == "ics":
            try:
                first_day = date.fromisoformat(start or "")
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail="Give the first day as start=YYYY-MM-DD.") from None
            return Response(build_ics(trip, first_day), media_type="text/calendar", headers={
                "Content-Disposition": 'attachment; filename="uttarakhand-trip.ics"'})
        raise HTTPException(status_code=400, detail="format must be txt, pdf or ics")

    # --- long-term memory: the traveller can see and delete everything remembered ---
    def _memory(request: Request):
        memory = getattr(request.app.state, "memory", None)
        if memory is None:
            raise HTTPException(status_code=404, detail="Memory is turned off.")
        return memory

    @app.get("/api/memories")
    async def list_memories(request: Request, user: dict = Depends(current_user)):
        return _memory(request).recall(user["email"])

    @app.delete("/api/memories/{key}")
    async def forget_memory(key: str, request: Request, user: dict = Depends(current_user)):
        if not _memory(request).forget(user["email"], key):
            raise HTTPException(status_code=404, detail="No such memory")
        return {"forgotten": key}

    @app.delete("/api/memories")
    async def forget_all(request: Request, user: dict = Depends(current_user)):
        return {"forgotten": _memory(request).forget_all(user["email"])}

    @app.post("/api/feedback")
    async def feedback(
        body: FeedbackRequest,
        request: Request,
        background: BackgroundTasks,
        user: dict = Depends(current_user),
    ):
        background.add_task(
            request.app.state.store.save_feedback,
            body.session_id,
            body.query,
            body.rating,
            body.comment,
        )
        return {"status": "received"}

    return app
