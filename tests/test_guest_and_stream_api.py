"""Guest mode (try without an account) and the streaming trip endpoints."""
import json

import fakeredis
import pytest
from conftest import FakePlanner, FakeRAG, FakeStore
from fastapi.testclient import TestClient

from app.api import security
from app.api.main import create_app
from app.api.ratelimit import RateLimiter, RateLimitExceeded
from app.config import Settings
from app.trips.store import TripStore

SECRET = "test-secret-key-at-least-16-chars"


def make_client(**overrides):
    app = create_app(Settings(secret_key=SECRET, **overrides))
    app.state.store = FakeStore()
    app.state.rag = FakeRAG()
    app.state.planner = FakePlanner()
    app.state.trips = TripStore(":memory:")
    app.state.limiter = RateLimiter(fakeredis.FakeRedis(), limit_per_minute=10)
    return TestClient(app)


def guest_headers(c):
    r = c.post("/api/guest")
    assert r.status_code == 200 and r.json()["guest"] is True
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def sse(text):
    return [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]


# ---------- guest mode ----------
def test_guest_can_plan_and_owns_only_their_trips():
    with make_client() as c:
        g1, g2 = guest_headers(c), guest_headers(c)
        r = c.post("/api/trips", json={"text": "3 days"}, headers=g1)
        assert r.status_code == 200 and r.json()["status"] == "waiting"
        trip = r.json()["trip_id"]
        assert c.post(f"/api/trips/{trip}/resume", json={"value": "x"},
                      headers=g2).status_code == 403
        assert c.get("/api/trips", headers=g1).status_code == 200
        assert c.post("/api/chat", json={"query": "hi"}, headers=g1).status_code == 200


def test_guest_sessions_are_limited_per_ip_and_per_day():
    with make_client(guest_sessions_per_ip_per_hour=2) as c:
        assert [c.post("/api/guest").status_code for _ in range(3)] == [200, 200, 429]
    with make_client(guest_sessions_per_day=1) as c:
        assert [c.post("/api/guest").status_code for _ in range(2)] == [200, 429]


def test_guests_get_a_stricter_rate_limit():
    with make_client(guest_rate_limit_per_minute=2) as c:
        h = guest_headers(c)
        codes = [c.post("/api/chat", json={"query": "q"}, headers=h).status_code
                 for _ in range(3)]
        assert codes == [200, 200, 429]


def test_guest_mode_can_be_turned_off_and_tokens_stop_working():
    with make_client() as c:
        h = guest_headers(c)
    with make_client(guest_enabled=False) as c:
        assert c.post("/api/guest").status_code == 404
        assert c.get("/api/trips", headers=h).status_code == 401


def test_a_guest_claim_cannot_impersonate_a_registered_user():
    with make_client() as c:
        c.post("/api/register", json={"email": "a@b.com", "password": "pass1234"})
        forged = security.create_access_token({"sub": "a@b.com", "guest": True}, SECRET)
        h = {"Authorization": f"Bearer {forged}"}
        assert c.get("/api/trips", headers=h).status_code == 401


# ---------- streaming ----------
def test_start_stream_sends_progress_then_the_result():
    with make_client() as c:
        r = c.post("/api/trips?stream=true", json={"text": "3 days"}, headers=guest_headers(c))
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        events = sse(r.text)
        assert [e["type"] for e in events] == ["progress", "progress", "result"]
        assert events[0]["phase"] == "start" and events[1]["phase"] == "end"
        assert events[-1]["status"] == "waiting" and events[-1]["trip_id"]


def test_resume_stream_result_matches_the_json_endpoint():
    with make_client() as c:
        h = guest_headers(c)
        trip = c.post("/api/trips", json={"text": "x"}, headers=h).json()["trip_id"]
        plain = c.post(f"/api/trips/{trip}/resume", json={"value": "a"}, headers=h).json()
        live = sse(c.post(f"/api/trips/{trip}/resume?stream=true", json={"value": "a"},
                          headers=h).text)[-1]
        assert live.pop("type") == "result" and live == plain


def test_stream_reports_errors_as_an_event_not_a_crash():
    with make_client() as c:
        h = guest_headers(c)
        trip = c.post("/api/trips", json={"text": "x"}, headers=h).json()["trip_id"]
        events = sse(c.post(f"/api/trips/{trip}/resume?stream=true",
                            json={"value": "explode"}, headers=h).text)
        assert events == [{"type": "error",
                           "detail": "Planning failed on the server. Please try again."}]
        bad = sse(c.post(f"/api/trips/{trip}/replan?stream=true",
                         json={"from_day": 9, "reason": "rain"}, headers=h).text)
        assert bad == [{"type": "error", "detail": "from_day must be between 1 and 3."}]


def test_stream_still_checks_ownership_before_starting():
    with make_client() as c:
        trip = c.post("/api/trips", json={"text": "x"}, headers=guest_headers(c)).json()["trip_id"]
        r = c.post(f"/api/trips/{trip}/resume?stream=true", json={"value": "a"},
                   headers=guest_headers(c))
        assert r.status_code == 403


# ---------- in-memory rate limiting (no Redis) ----------
def test_limits_still_apply_without_redis():
    rl = RateLimiter(None, limit_per_minute=2)
    rl.check("u")
    rl.check("u")
    with pytest.raises(RateLimitExceeded):
        rl.check("u")
    rl.check("other")
    rl.check("u", limit=5, window=3600)  # separate window, separate count
