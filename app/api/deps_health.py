"""Readiness check: is every service the planner needs reachable with the configured keys?

GET /health/deps answers {"ok": bool, "checks": {name: {"ok", "ms", "error"?}}}. It is for
operators after a deploy ("search is down": which service, and is it a bad key or a timeout?).

Safe to expose publicly:
- errors are reported as the exception type and HTTP status only, never the message, which
  can echo part of a key or a connection string;
- the result is cached, so hitting the endpoint repeatedly costs at most one tiny LLM and one
  embedding call a minute.
"""
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date

log = logging.getLogger(__name__)

CHECK_TIMEOUT = 20.0
CACHE_SECONDS = 60.0


def describe_error(exc: BaseException) -> str:
    """'UnauthorizedException (HTTP 401)': enough to tell a bad key from an outage."""
    status = (getattr(exc, "status_code", None) or getattr(exc, "status", None)
              or getattr(getattr(exc, "response", None), "status_code", None))
    return type(exc).__name__ + (f" (HTTP {status})" if isinstance(status, int) else "")


def build_checks(planner, trips) -> dict[str, Callable[[], dict | None]]:
    """The checks that apply to the wired services; anything not wired is left out."""
    checks: dict[str, Callable[[], dict | None]] = {}
    db = getattr(trips, "_db", None)
    if db is not None:
        checks["database"] = lambda: db.query("SELECT 1", ()) and None
    store = getattr(planner, "store", None)
    driver = getattr(store, "driver", None)
    if driver is not None:
        checks["graph"] = lambda: driver.verify_connectivity()
    retriever = getattr(planner, "retriever", None)
    index = getattr(retriever, "index", None)
    if index is not None:
        def vector_index():
            stats = index.describe_index_stats()
            total = getattr(stats, "total_vector_count", None)
            if total is None and isinstance(stats, dict):
                total = stats.get("total_vector_count")
            return {"vectors": total}
        checks["vector_index"] = vector_index
    embedder = getattr(retriever, "embedder", None)
    if embedder is not None:
        def embeddings():
            vec = embedder.embeddings.create(model=retriever.embed_model, input=["health check"],
                                             encoding_format="float").data[0].embedding
            return {"dim": len(vec)}
        checks["embeddings"] = embeddings
    if planner is not None:  # live weather, the same fallback path as the planner, uncached
        def weather():
            from mcp_server import weather as wm
            today = date.today()
            w = wm.get_weather(30.32, 78.03, today, today,
                               fetch=lambda url, params: wm.fetch_uncached(url, params, 1),
                               fetch_met=wm.fetch_met_uncached)
            return {"source": w.get("source")}
        checks["weather"] = weather
    llm, model = getattr(planner, "llm", None), getattr(planner, "small", None)
    if llm is not None and model:
        checks["llm"] = lambda: llm.complete(
            model, [{"role": "user", "content": "Reply with OK."}], max_tokens=2) and None
    return checks


def run_checks(checks: dict[str, Callable[[], dict | None]],
               timeout: float = CHECK_TIMEOUT) -> dict:
    results: dict[str, dict] = {}
    # Not a `with` block: that would wait for a hung call and defeat the timeout.
    pool = ThreadPoolExecutor(max_workers=max(1, len(checks)), thread_name_prefix="deps-check")
    try:
        started = {name: (pool.submit(fn), time.monotonic()) for name, fn in checks.items()}
        for name, (future, t0) in started.items():
            try:
                extra = future.result(timeout=max(0.0, timeout - (time.monotonic() - t0)))
                results[name] = {"ok": True, **(extra or {})}
            except FutureTimeout:
                results[name] = {"ok": False, "error": f"timed out after {timeout:.0f}s"}
            except Exception as exc:
                log.warning("dependency check %s failed", name, exc_info=True)
                results[name] = {"ok": False, "error": describe_error(exc)}
            results[name]["ms"] = round((time.monotonic() - t0) * 1000)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return {"ok": all(r["ok"] for r in results.values()), "checks": results}


class DepsHealth:
    """Caches the last result so the endpoint cannot be used to run up provider costs."""

    def __init__(self, cache_seconds: float = CACHE_SECONDS):
        self.cache_seconds = cache_seconds
        self._lock = threading.Lock()
        self._at = 0.0
        self._result: dict | None = None

    def get(self, planner, trips) -> dict:
        with self._lock:
            if self._result is None or time.monotonic() - self._at > self.cache_seconds:
                self._result = run_checks(build_checks(planner, trips))
                self._at = time.monotonic()
            return self._result
