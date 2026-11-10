"""FastAPI entrypoint. Services are created in the lifespan and stored on app.state,
so tests can build the app with fakes instead of real Neo4j / Pinecone / OpenAI."""
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

from app.api import security
from app.api.ratelimit import RateLimiter, RateLimitExceeded, connect_redis
from app.config import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/token")


# --- schemas ---
class UserRegister(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str


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
        from app.rag.hybrid import HybridRAG

        s: Settings = app.state.settings
        app.state.store = GraphStore(s.neo4j_uri, s.neo4j_user, s.neo4j_password, s.neo4j_database)
        redis_client = connect_redis(s.redis_host, s.redis_port)
        app.state.limiter = RateLimiter(redis_client, s.rate_limit_per_minute)
        if s.rag_mode == "hybrid":
            app.state.rag = HybridRAG(s, app.state.store, redis_client)
        else:
            app.state.rag = build_self_rag(s, app.state.store, redis_client)
        app.state.planner = build_trip_planner(s, app.state.store, redis_client)
    if not hasattr(app.state, "trips"):
        from app.trips.store import TripStore

        app.state.trips = TripStore(app.state.settings.trips_path)
    yield
    planner = getattr(app.state, "planner", None)
    tools = getattr(planner, "tools", None)
    if tools is not None and hasattr(tools, "close"):
        tools.close()
    store = getattr(app.state, "store", None)
    if store is not None and hasattr(store, "close"):
        store.close()
    trips = getattr(app.state, "trips", None)
    if trips is not None and hasattr(trips, "close"):
        trips.close()


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
        user = request.app.state.store.get_user(email)
        if user is None:
            raise unauthorized
        return user

    async def rate_limited_user(request: Request, user: dict = Depends(current_user)) -> dict:
        try:
            request.app.state.limiter.check(user["email"])
        except RateLimitExceeded:
            limit = request.app.state.limiter.limit
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

    @app.post("/api/trips")
    async def start_trip(body: TripStart, request: Request,
                         user: dict = Depends(rate_limited_user)):
        trip_id = str(uuid.uuid4())
        profile = request.app.state.trips.get_profile(user["email"])
        result = await run_in_threadpool(
            request.app.state.planner.start, trip_id, body.text, user["email"], profile)
        return _trip_response(request, trip_id, result, user["email"])

    @app.get("/api/trips")
    async def list_trips(request: Request, user: dict = Depends(current_user)):
        return request.app.state.trips.list_trips(user["email"])

    @app.get("/api/trips/{trip_id}")
    async def get_trip(trip_id: str, request: Request, user: dict = Depends(current_user)):
        return _saved_trip(request, trip_id, user)

    @app.post("/api/trips/{trip_id}/resume")
    async def resume_trip(trip_id: str, body: TripResume, request: Request,
                          user: dict = Depends(rate_limited_user)):
        _owned_trip(request, trip_id, user)
        result = await run_in_threadpool(request.app.state.planner.resume, trip_id, body.value)
        return _trip_response(request, trip_id, result, user["email"])

    @app.post("/api/trips/{trip_id}/replan")
    async def replan_trip(trip_id: str, body: TripReplan, request: Request,
                          user: dict = Depends(rate_limited_user)):
        _owned_trip(request, trip_id, user)
        if not body.reason.strip():
            raise HTTPException(status_code=400, detail="Tell me what changed.")
        try:
            result = await run_in_threadpool(
                request.app.state.planner.replan, trip_id, body.from_day, body.reason.strip()[:500])
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
