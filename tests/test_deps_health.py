"""Readiness check: which service is down, without leaking secrets or running up costs."""
from types import SimpleNamespace

from app.api.deps_health import DepsHealth, build_checks, describe_error, run_checks
from app.trips.store import TripStore


class Unauthorized(Exception):
    status = 401


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * 1024)])


def services(index_error=None):
    embedder = SimpleNamespace(embeddings=FakeEmbeddings())

    def stats():
        if index_error:
            raise index_error
        return {"total_vector_count": 721}

    retriever = SimpleNamespace(index=SimpleNamespace(describe_index_stats=stats),
                                embedder=embedder, embed_model="bge")
    llm = SimpleNamespace(complete=lambda *a, **kw: "OK")
    store = SimpleNamespace(driver=SimpleNamespace(verify_connectivity=lambda: None))
    planner = SimpleNamespace(retriever=retriever, llm=llm, small="small", store=store)
    return planner, TripStore(":memory:"), embedder


def test_all_services_up():
    planner, trips, _ = services()
    result = run_checks(build_checks(planner, trips))
    assert result["ok"] is True
    assert set(result["checks"]) == {"database", "graph", "vector_index", "embeddings", "llm"}
    assert result["checks"]["vector_index"]["vectors"] == 721
    assert result["checks"]["embeddings"]["dim"] == 1024


def test_a_bad_key_names_the_service_and_status_but_never_the_message():
    planner, trips, _ = services(Unauthorized("Invalid API key pcsk_SECRET123"))
    result = run_checks(build_checks(planner, trips))
    assert result["ok"] is False and result["checks"]["llm"]["ok"] is True
    assert result["checks"]["vector_index"] == {
        "ok": False, "error": "Unauthorized (HTTP 401)",
        "ms": result["checks"]["vector_index"]["ms"]}
    assert "SECRET" not in str(result)


def test_a_hanging_service_times_out():
    import threading
    planner, trips, _ = services()
    release = threading.Event()
    planner.store.driver.verify_connectivity = lambda: release.wait(5)
    try:
        result = run_checks(build_checks(planner, trips), timeout=0.2)
    finally:
        release.set()
    assert result["checks"]["graph"]["error"].startswith("timed out")


def test_results_are_cached_so_the_endpoint_cannot_run_up_costs():
    planner, trips, embedder = services()
    health = DepsHealth(cache_seconds=60)
    for _ in range(5):
        assert health.get(planner, trips)["ok"]
    assert embedder.embeddings.calls == 1


def test_unwired_services_are_skipped():
    assert run_checks(build_checks(None, None)) == {"ok": True, "checks": {}}
    assert describe_error(ValueError("x")) == "ValueError"


def test_endpoint_reports_503_when_a_service_is_down(client):
    planner, trips, _ = services(Unauthorized("nope"))
    client.app.state.planner, client.app.state.trips = planner, trips
    r = client.get("/health/deps")
    assert r.status_code == 503 and r.json()["checks"]["vector_index"]["ok"] is False
