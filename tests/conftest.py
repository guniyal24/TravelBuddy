import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-at-least-16-chars")

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.trips.store import TripStore


class FakeStore:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.feedback: list[tuple] = []

    def create_user(self, email, password_hash):
        self.users[email] = {"email": email, "password_hash": password_hash}

    def get_user(self, email):
        return self.users.get(email)

    def save_feedback(self, *args):
        self.feedback.append(args)

    def close(self):
        pass


class FakeRAG:
    def get_answer(self, query, session_id, history=None):
        yield from ["Hello ", "from ", "Uttarakhand"]


class FakePlanner:
    def __init__(self):
        self.calls = []
        self.owners = {}

    def owner(self, thread_id):
        return self.owners.get(thread_id)

    def replan(self, thread_id, from_day, reason):
        self.calls.append(("replan", thread_id, from_day, reason))
        if from_day > 3:
            raise ValueError("from_day must be between 1 and 3.")
        return {"status": "waiting", "prompt": {"type": "approve", "preview": "new plan"}}

    def start(self, thread_id, text, owner="", profile=None):
        self.calls.append(("start", thread_id, text))
        self.owners[thread_id] = owner
        return {"status": "waiting", "prompt": {"type": "choose", "options": []}}

    def resume(self, thread_id, value):
        self.calls.append(("resume", thread_id, value))
        return {"status": "done", "itinerary": "# plan"}


@pytest.fixture
def settings():
    return Settings(secret_key="test-secret-key-at-least-16-chars")


@pytest.fixture
def client(settings):
    app = create_app(settings)
    app.state.store = FakeStore()
    app.state.rag = FakeRAG()
    app.state.planner = FakePlanner()
    app.state.trips = TripStore(":memory:")
    app.state.limiter = RateLimiter(fakeredis.FakeRedis(), limit_per_minute=3)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    client.post("/api/register", json={"email": "a@b.com", "password": "pass1234"})
    r = client.post("/api/token", data={"username": "a@b.com", "password": "pass1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
