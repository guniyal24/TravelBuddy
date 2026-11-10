"""Trip store and planner checkpoints behave the same on SQLite and Postgres.

Postgres cases run when TEST_DATABASE_URL points at a database (CI starts one); otherwise
they are skipped. Ids are random, so tests never need to clean up and can share a database.
"""
import os
import uuid

import pytest
from test_trip_graph import GOOD, REQ, FakeLLM, FakeRetriever, FakeStore

from app.graph.persistence import close_checkpointer, make_checkpointer
from app.graph.trip_graph import TripPlanner
from app.trips.store import TripStore

PG_URL = os.environ.get("TEST_DATABASE_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL, reason="TEST_DATABASE_URL not set")
BACKENDS = [":memory:", pytest.param(PG_URL, marks=needs_pg, id="postgres")]


@pytest.fixture(params=BACKENDS, ids=["sqlite", "postgres"])
def store(request):
    s = TripStore(request.param)
    yield s
    s.close()


def _trip():
    return {"request": {"days": 2}, "plan": {"days": [
        {"day": 1, "destination": "destination_haridwar"},
        {"day": 2, "destination": "destination_rishikesh"}]},
        "checklist": [{"id": "todo-0", "kind": "todo", "label": "Book bus", "done": False}]}


def test_profiles_round_trip_and_upsert(store):
    email = f"{uuid.uuid4()}@x.com"
    assert store.get_profile(email) == {}
    store.save_profile(email, {"tier": "mid", "evil": 1})
    store.save_profile(email, {"tier": "premium", "diet": "veg"})
    assert store.get_profile(email) == {"tier": "premium", "diet": "veg"}


def test_trips_keep_created_at_and_checklist_ticks(store):
    trip_id, owner = str(uuid.uuid4()), f"{uuid.uuid4()}@x.com"
    store.save_trip(trip_id, owner, _trip())
    first = store.get_trip(trip_id)
    assert first["title"] == "2 days: Haridwar, Rishikesh" and first["owner"] == owner
    store.save_trip(trip_id, owner, {**_trip(), "request": {"days": 3}})
    again = store.get_trip(trip_id)
    assert again["created_at"] == first["created_at"] and again["title"].startswith("3 days")
    assert store.set_check(trip_id, "todo-0", True) and not store.set_check(trip_id, "nope", True)
    assert store.get_trip(trip_id)["checklist"][0]["done"] is True
    store.set_check(trip_id, "todo-0", False)
    assert store.get_trip(trip_id)["checklist"][0]["done"] is False
    assert [t["trip_id"] for t in store.list_trips(owner)] == [trip_id]
    assert store.get_trip("missing") is None


def test_usage_totals_keep_every_column(store):
    # SUM(...) columns share a name; a dict-row backend once merged them into one value
    trip_id = str(uuid.uuid4())
    assert store.trip_usage(trip_id)["runs"] == 0
    for step in ("choose", "approve"):
        store.record_usage(trip_id, step, {"llm_calls": 2, "tokens_in": 100, "tokens_out": 50,
                                           "cost_usd": 0.001, "seconds": 4.0})
    assert store.trip_usage(trip_id) == {"runs": 2, "llm_calls": 4, "tokens_in": 200,
                                         "tokens_out": 100, "cost_usd": 0.002, "seconds": 8.0}
    store.save_trip(trip_id, "a@x.com", _trip())
    assert store.usage_stats()["trips"] >= 1


@needs_pg
def test_a_paused_trip_survives_a_restart_on_postgres():
    """Start a trip, drop the planner (a redeploy), resume with a brand-new one."""
    thread = str(uuid.uuid4())
    saver = make_checkpointer("", PG_URL)
    tp = TripPlanner(FakeLLM([REQ, GOOD]), FakeRetriever(), FakeStore(), "s", "b",
                     checkpointer=saver)
    r = tp.start(thread, "3 days", owner="a@b.com")
    assert r["prompt"]["type"] == "choose"
    close_checkpointer(saver)

    saver2 = make_checkpointer("", PG_URL)
    tp2 = TripPlanner(FakeLLM([GOOD]), FakeRetriever(), FakeStore(), "s", "b",
                      checkpointer=saver2)
    assert tp2.owner(thread) == "a@b.com"
    r = tp2.resume(thread, "destination_haridwar+destination_rishikesh")
    assert r["prompt"]["type"] == "approve"
    r = tp2.resume(thread, {"action": "approve"})
    assert r["status"] == "done" and "Day 1 - Haridwar" in r["itinerary"]
    close_checkpointer(saver2)


@needs_pg
def test_store_survives_the_server_closing_idle_connections():
    # Neon closes idle connections when its compute suspends; the next request must not fail
    import psycopg

    store = TripStore(PG_URL)
    try:
        assert store.trip_usage("warm-up")["runs"] == 0
        with psycopg.connect(PG_URL, autocommit=True) as admin:
            admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                          "WHERE pid <> pg_backend_pid() AND datname = current_database() "
                          "AND usename = current_user")
        assert store.trip_usage("after-drop")["runs"] == 0
    finally:
        store.close()
