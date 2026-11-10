"""Long-term memory: storage, safety filters, the memory agent, recall across trips, API."""
import os
import uuid

import fakeredis
import pytest
from conftest import FakePlanner, FakeRAG
from conftest import FakeStore as FakeUserStore
from fastapi.testclient import TestClient
from test_trip_graph import GOOD, HW, REQ, RK, FakeLLM, FakeRetriever, FakeStore

from app.api.main import create_app
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.graph.trip_graph import TripPlanner
from app.memory import TravelMemory, extract_preferences, trip_episode
from app.trips.store import TripStore

BOTH = f"{HW}+{RK}"
PG_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(params=[":memory:", pytest.param(
    PG_URL, marks=pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set"))],
    ids=["sqlite", "postgres"])
def memory(request):
    m = TravelMemory.open(request.param)
    yield m
    m.close()


# ---------------------------------------------------------------- storage
def test_remember_recall_refresh_and_forget(memory):
    u = f"u-{uuid.uuid4()}"
    a = memory.remember(u, "preference", "Avoids long drives", "I hate long drives")
    memory.remember(u, "preference", "avoids  long drives!", "again")  # same, refreshed
    memory.remember(u, "trip", "3-day trip to Haridwar", extra={"towns": [HW]})
    got = memory.recall(u)
    assert len(got) == 2 and {m["kind"] for m in got} == {"preference", "trip"}
    assert memory.recall(u, kind="trip")[0]["towns"] == [HW]
    assert memory.recall(f"other-{uuid.uuid4()}") == []  # per-traveller namespaces
    assert memory.forget(u, a["key"]) and not memory.forget(u, a["key"])
    assert memory.forget_all(u) == 1 and memory.recall(u) == []


@pytest.mark.parametrize("text", ["Call me on 9876543210", "Email asha@example.com",
                                  "Aadhaar 1234 5678 9012", "My passport is ready",
                                  "Pays by credit card"])
def test_sensitive_details_are_never_stored(text):
    m = TravelMemory.open(":memory:")
    assert m.remember("u", "preference", text, text) is None and m.recall("u") == []


# ---------------------------------------------------------------- memory agent
class OneShot:
    def __init__(self, reply):
        self.reply = reply

    def json(self, model, messages, **kw):
        return self.reply


def test_memory_agent_keeps_only_preferences_quoted_from_the_traveller():
    said = ["3 days in Rishikesh, I really hate long drives", "less walking please"]
    llm = OneShot({"memories": [
        {"text": "Avoids long drives", "quote": "I really hate long drives"},
        {"text": "Prefers less walking", "quote": "less walking"},
        {"text": "Loves luxury spas", "quote": "we adore luxury spas"},  # not said
        {"text": "", "quote": "hate long drives"},  # empty text
        "junk"]})
    kept, proposed = extract_preferences(llm, "m", said)
    assert [k["text"] for k in kept] == ["Avoids long drives", "Prefers less walking"]
    assert proposed == 4
    assert extract_preferences(llm, "m", ["", "  "]) == ([], 0)


def test_trip_episode_is_a_readable_line():
    line = trip_episode({"days": 3, "people": 2, "month": 11, "tier": "mid"}, GOOD,
                        ["less walking"])
    assert line == ("3-day trip to Haridwar + Rishikesh in November for 2, mid tier; asked for "
                    "changes: less walking")


# ---------------------------------------------------------------- recall across trips
MEM_REPLY = {"memories": [{"text": "Avoids long drives", "quote": "hate long drives"}]}


class MemLLM(FakeLLM):
    def json(self, model, messages, default=None, **kw):
        self.prompts.append(messages[-1]["content"])
        if messages[0]["content"].startswith("You maintain a travel assistant"):
            return MEM_REPLY
        return self.replies.pop(0)


def _trip(tp, tid, text, owner="asha"):
    tp.start(tid, text, owner=owner)
    tp.resume(tid, BOTH)
    return tp.resume(tid, {"action": "approve"})


def test_an_approved_trip_teaches_the_next_one():
    memory = TravelMemory.open(":memory:")
    llm = MemLLM([REQ, GOOD])
    tp = TripPlanner(llm, FakeRetriever(), FakeStore(), "s", "b", memory=memory)
    events = []
    tp.start("t1", "3 days, I hate long drives", owner="asha")
    tp.resume("t1", BOTH)
    done = tp.resume("t1", {"action": "approve"}, on_event=events.append)
    assert done["status"] == "done"
    assert [m["text"] for m in memory.recall("asha", "preference")] == ["Avoids long drives"]
    assert memory.recall("asha", "trip")[0]["towns"] == [HW, RK]
    mem_event = next(e for e in events if e["node"] == "remember" and e["phase"] == "end")
    assert "Learned 1 lasting preference" in mem_event["message"]

    # Trip 2, no towns named: somewhere new is preferred over where they already went
    llm.replies = [REQ]
    r = tp.start("t2", "another trip", owner="asha")
    assert BOTH not in [o["id"] for o in r["prompt"]["options"]]

    # Trip 3, the same towns named again: offered first, labelled, and memory reaches the plan
    llm.replies = [REQ, GOOD]
    r = tp.start("t3", "Haridwar and Rishikesh again", owner="asha")
    first = r["prompt"]["options"][0]
    assert first["id"] == BOTH and first["visited"] == ["Haridwar", "Rishikesh"]
    tp.resume("t3", BOTH)
    assert "Remembered about this traveller" in llm.prompts[-1]
    assert "Avoids long drives" in llm.prompts[-1]


def test_cancelled_trips_and_other_travellers_teach_nothing():
    memory = TravelMemory.open(":memory:")
    tp = TripPlanner(MemLLM([REQ, GOOD]), FakeRetriever(), FakeStore(), "s", "b", memory=memory)
    tp.start("c", "I hate long drives", owner="ravi")
    tp.resume("c", BOTH)
    assert tp.resume("c", {"action": "cancel"})["status"] == "cancelled"
    assert memory.recall("ravi") == []
    _trip(TripPlanner(MemLLM([REQ, GOOD]), FakeRetriever(), FakeStore(), "s", "b",
                      memory=memory), "d", "I hate long drives", owner="asha")
    assert memory.recall("ravi") == [] and memory.recall("asha")


def test_without_memory_the_planner_works_as_before():
    tp = TripPlanner(FakeLLM([REQ, GOOD]), FakeRetriever(), FakeStore(), "s", "b")
    assert _trip(tp, "n", "x")["status"] == "done"


# ---------------------------------------------------------------- API
def _client(memory):
    app = create_app(Settings(secret_key="test-secret-key-at-least-16-chars"))
    app.state.store, app.state.rag, app.state.planner = FakeUserStore(), FakeRAG(), FakePlanner()
    app.state.trips = TripStore(":memory:")
    app.state.limiter = RateLimiter(fakeredis.FakeRedis(), 10)
    if memory is not None:
        app.state.memory = memory
    return TestClient(app)


def test_memory_api_lists_and_deletes_only_your_own():
    memory = TravelMemory.open(":memory:")
    with _client(memory) as c:
        tok = c.post("/api/guest").json()["access_token"]
        me = {"Authorization": f"Bearer {tok}"}
        other = {"Authorization": "Bearer " + c.post("/api/guest").json()["access_token"]}
        from app.api import security
        sub = security.decode_token(tok, "test-secret-key-at-least-16-chars")["sub"]
        m = memory.remember(sub, "preference", "Avoids long drives", "hate long drives")
        assert [x["text"] for x in c.get("/api/memories", headers=me).json()] == [
            "Avoids long drives"]
        assert c.get("/api/memories", headers=other).json() == []
        assert c.delete(f"/api/memories/{m['key']}", headers=other).status_code == 404
        assert c.delete(f"/api/memories/{m['key']}", headers=me).status_code == 200
        memory.remember(sub, "trip", "a trip")
        assert c.delete("/api/memories", headers=me).json() == {"forgotten": 1}
        assert c.get("/api/memories").status_code == 401


def test_memory_api_reports_when_memory_is_off():
    with _client(None) as c:
        h = {"Authorization": "Bearer " + c.post("/api/guest").json()["access_token"]}
        assert c.get("/api/memories", headers=h).status_code == 404
