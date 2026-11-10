"""Usage metering, cost, the stats endpoint, and parallel translation."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import fakeredis
from conftest import FakeRAG
from conftest import FakeStore as FakeUserStore
from fastapi.testclient import TestClient
from test_trip_graph import GOOD, HW, REQ, RK, FakeRetriever, FakeStore

from app import usage
from app.api.main import create_app
from app.api.ratelimit import RateLimiter
from app.config import Settings
from app.graph.trip_graph import TripPlanner, split_lines, split_sections
from app.rag.llm import LLM
from app.trips.store import TripStore
from app.usage import Meter, in_context, metered, record


# ---------------------------------------------------------------- meter and cost
def test_meter_prices_tokens_per_model_and_unknown_models_are_not_free():
    m = Meter()
    m.add("mistralai/Mistral-Small-3.2-24B-Instruct-2506", 1_000_000, 1_000_000)
    assert round(m.cost_usd(), 2) == 0.28  # 0.08 in + 0.20 out
    m2 = Meter()
    m2.add("some/unknown-model", 1_000_000, 0)
    assert m2.cost_usd() == usage.FALLBACK_PRICE[0]
    s = m.summary()
    assert s["llm_calls"] == 1 and s["tokens_in"] == 1_000_000 and s["cost_inr"] > 0


def test_prices_can_be_overridden(monkeypatch):
    monkeypatch.setenv("MODEL_PRICES", '{"x/y": [1.0, 2.0]}')
    m = Meter()
    m.add("x/y", 1_000_000, 1_000_000)
    assert m.cost_usd() == 3.0


def test_calls_outside_a_meter_are_ignored():
    record("m", 10, 10)  # no meter open: must not raise


def test_in_context_survives_truly_concurrent_threads():
    """Regression: one shared Context cannot be entered by two threads at once."""
    barrier = threading.Barrier(6)

    def work(_):
        barrier.wait(timeout=5)  # force every call to overlap
        time.sleep(0.01)
        record("m", 1, 1)

    with metered() as m, ThreadPoolExecutor(6) as ex:
        list(ex.map(in_context(work), range(6)))
    assert m.calls == 6


def test_plain_threads_would_lose_usage_which_is_why_pools_use_in_context():
    with metered() as m, ThreadPoolExecutor(2) as ex:
        ex.submit(record, "m", 1, 1).result()
    assert m.calls == 0


# ---------------------------------------------------------------- planner integration
class UsageClient:
    """OpenAI-shaped fake that reports token usage, behind the real LLM wrapper."""

    def __init__(self, replies):
        self.replies = list(replies)
        outer = self

        class Completions:
            def create(self, **kw):
                import json
                content = json.dumps(outer.replies.pop(0))
                return type("R", (), {
                    "choices": [type("C", (), {"message": type("M", (), {
                        "content": content})()})()],
                    "usage": type("U", (), {"prompt_tokens": 1000, "completion_tokens": 200})()})()

        self.chat = type("Chat", (), {"completions": Completions()})()


def test_every_run_reports_its_usage_including_parallel_agents():
    llm = LLM(UsageClient([REQ, GOOD]))
    tp = TripPlanner(llm, FakeRetriever(), FakeStore(), "mistralai/Mistral-Small-3.2-24B-"
                     "Instruct-2506", "mistralai/Mistral-Small-3.2-24B-Instruct-2506")
    r1 = tp.start("u", "x")
    assert r1["usage"]["llm_calls"] == 1 and r1["usage"]["tokens_in"] == 1000
    r2 = tp.resume("u", f"{HW}+{RK}")
    assert r2["usage"]["llm_calls"] == 1 and r2["usage"]["cost_usd"] > 0


def test_api_saves_usage_per_step_and_publishes_aggregate_stats():
    app = create_app(Settings(secret_key="test-secret-key-at-least-16-chars"))
    store = TripStore(":memory:")

    class Planner:
        def __init__(self):
            self.owners = {}

        def owner(self, tid):
            return self.owners.get(tid)

        def start(self, tid, text, owner="", profile=None, on_event=None):
            self.owners[tid] = owner
            return {"status": "waiting", "prompt": {"type": "choose", "options": []},
                    "usage": {"llm_calls": 2, "tokens_in": 900, "tokens_out": 100,
                              "cost_usd": 0.001, "seconds": 3.0}}

        def resume(self, tid, value, on_event=None):
            from test_tier23 import _trip
            trip = {**_trip(), "checklist": []}
            trip.pop("trip_id")
            trip.pop("title")
            return {"status": "done", "itinerary": "# plan", "state": {"structured": trip},
                    "usage": {"llm_calls": 5, "tokens_in": 4000, "tokens_out": 900,
                              "cost_usd": 0.002, "seconds": 9.0}}

    app.state.store, app.state.rag, app.state.planner = FakeUserStore(), FakeRAG(), Planner()
    app.state.trips = store
    app.state.limiter = RateLimiter(fakeredis.FakeRedis(), 50)
    with TestClient(app) as c:
        assert c.get("/api/stats").json() == {"trips": 0}
        h = {"Authorization": "Bearer " + c.post("/api/guest").json()["access_token"]}
        r = c.post("/api/trips", json={"text": "x"}, headers=h).json()
        assert r["usage"]["llm_calls"] == 2
        done = c.post(f"/api/trips/{r['trip_id']}/resume", json={"value": "a"}, headers=h).json()
        assert done["usage"] == {"runs": 2, "llm_calls": 7, "tokens_in": 4900, "tokens_out": 1000,
                                 "cost_usd": 0.003, "seconds": 12.0}
        stats = c.get("/api/stats").json()
        assert stats["trips"] == 1 and stats["cost_usd"]["p50"] == 0.003
        assert stats["seconds"]["p50"] == 12.0 and stats["cost_inr"]["p50"] > 0


# ---------------------------------------------------------------- parallel translation
DOC = "# Trip\n\n## Day 1 - Haridwar\n- Visit: A\n- Stay: B\n\n## Day 2 - Rishikesh\n- Visit: C"


def test_sections_and_lines_split_and_rejoin_losslessly():
    long_doc = DOC + "\n\n## Costs\n" + "\n".join(f"- line {i}: ₹{i * 100}" for i in range(40))
    sections = split_sections(long_doc)
    assert [s.splitlines()[0] for s in sections] == [
        "# Trip", "## Day 1 - Haridwar", "## Day 2 - Rishikesh", "## Costs"]
    rebuilt = "\n\n".join("\n".join(split_lines(s)) for s in sections)
    assert rebuilt == long_doc
    assert all(len(p) <= 320 for s in sections for p in split_lines(s))
    assert split_sections("short") == ["short"]


def test_translation_runs_pieces_in_parallel_and_keeps_order():
    calls = []

    class Echo:
        def complete(self, model, messages, max_tokens=None):
            calls.append(messages[1]["content"])
            time.sleep(0.05)
            return messages[1]["content"].upper()

    tp = TripPlanner.__new__(TripPlanner)
    tp.llm, tp.small = Echo(), "m"
    doc = DOC + "\n\n" + "\n".join(f"- filler line number {i}" for i in range(40))
    t0 = time.time()
    out = tp._loc({"request": {"language": "hi"}}, doc)
    assert out == "\n\n".join("\n".join(p.upper() for p in split_lines(s))
                              for s in split_sections(doc))
    assert len(calls) > 3 and time.time() - t0 < 0.05 * len(calls) / 2  # overlapped
    assert tp._loc({"request": {"language": "en"}}, doc) == doc


def test_langfuse_is_used_only_when_configured(monkeypatch):
    from openai import OpenAI

    from app.rag import factory
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert factory._client_class() is OpenAI
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    import builtins
    real_import = builtins.__import__

    def no_langfuse(name, *a, **kw):
        if name.startswith("langfuse"):
            raise ImportError(name)
        return real_import(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", no_langfuse)
    assert factory._client_class() is OpenAI  # keys but no package: untraced, not broken
