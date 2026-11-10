"""Long-term agent memory, per traveller, on a LangGraph store.

Two kinds of memory (the trip state itself is short-term memory, in the checkpointer):

  preference   something lasting the traveller said ("avoid long drives", "we travel with a
               toddler"), extracted by the memory agent with an exact quote of their words,
               checked in code
  trip         a short episode of an approved trip: towns, month, the changes they asked for

Design rules:
  * learn only from trips the traveller approved, so abandoned drafts teach nothing
  * every preference keeps the quote it came from, and the traveller can see and delete any
    memory (GET/DELETE /api/memories)
  * no contact details, ID numbers or payment details are ever stored (prompt rule plus a code
    filter)
Storage: LangGraph's PostgresStore when DATABASE_URL is set, otherwise SqliteStore.
"""
import hashlib
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from langgraph.store.base import BaseStore

from app.graph.persistence import is_postgres, make_pg_pool

log = logging.getLogger(__name__)

NS = "memories"
MAX_MEMORIES = 40  # recalled per traveller, newest first
SENSITIVE = re.compile(
    r"(\b\d{10}\b|\+\d{6,}|@\w+\.\w+|\b\d{4}\s?\d{4}\s?\d{4}\b|passport|aadhaar|aadhar|\bpan\b"
    r"|credit card|debit card|\bcvv\b|\bupi\b|password)", re.IGNORECASE)

MEMORY_SYSTEM = (
    "You maintain a travel assistant's long-term memory about one traveller. From the "
    "traveller's own messages below, extract LASTING preferences that should shape future trips "
    "(for example: dislikes long drives, prefers quiet places, vegetarian, travels with elderly "
    "parents or small children, likes trekking, hates crowds). Ignore details that only apply "
    "to this one trip (dates, number of days, this trip's towns). Never extract names, phone "
    "numbers, email addresses, ID or passport numbers, or payment details. Return JSON only: "
    '{"memories": [{"text": "<short preference in the third person, e.g. Avoids long '
    'drives>", "quote": "<the traveller\'s exact words it comes from>"}]}. At most 5. If '
    'there is nothing lasting, return {"memories": []}.')


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").lower()).split())


def open_store(location: str) -> BaseStore:
    """PostgresStore for a postgres:// URL, otherwise SqliteStore at a path (or :memory:)."""
    if is_postgres(location):
        from langgraph.store.postgres import PostgresStore

        store = PostgresStore(make_pg_pool(location))
    else:
        from langgraph.store.sqlite import SqliteStore

        if location != ":memory:":
            Path(location).expanduser().parent.mkdir(parents=True, exist_ok=True)
        # autocommit: the store manages its own transactions
        store = SqliteStore(sqlite3.connect(location, check_same_thread=False,
                                            isolation_level=None))
    store.setup()
    return store


class TravelMemory:
    def __init__(self, store: BaseStore):
        self.store = store

    @classmethod
    def open(cls, location: str) -> "TravelMemory":
        return cls(open_store(location))

    @staticmethod
    def _ns(user: str) -> tuple[str, str]:
        return (NS, user)

    def remember(self, user: str, kind: str, text: str, quote: str = "",
                 trip_id: str | None = None, extra: dict | None = None) -> dict | None:
        """Store one memory; the same preference said again refreshes the old one."""
        text = " ".join((text or "").split())[:200]
        if not user or not text or SENSITIVE.search(text) or SENSITIVE.search(quote or ""):
            return None
        key = hashlib.sha256(f"{kind}|{_norm(text)}".encode()).hexdigest()[:16]
        value = {"kind": kind, "text": text, "quote": (quote or "")[:300], "trip_id": trip_id,
                 "updated": _now(), **(extra or {})}
        self.store.put(self._ns(user), key, value)
        return {"key": key, **value}

    def recall(self, user: str, kind: str | None = None, limit: int = MAX_MEMORIES) -> list[dict]:
        if not user:
            return []
        items = self.store.search(self._ns(user), filter={"kind": kind} if kind else None,
                                  limit=limit)
        out = [{"key": i.key, **i.value} for i in items]
        return sorted(out, key=lambda m: m.get("updated", ""), reverse=True)

    def forget(self, user: str, key: str) -> bool:
        if self.store.get(self._ns(user), key) is None:
            return False
        self.store.delete(self._ns(user), key)
        return True

    def forget_all(self, user: str) -> int:
        keys = [m["key"] for m in self.recall(user, limit=1000)]
        for k in keys:
            self.store.delete(self._ns(user), k)
        return len(keys)

    def close(self) -> None:
        conn = getattr(self.store, "conn", None)
        if conn is not None and hasattr(conn, "close"):
            conn.close()


def extract_preferences(llm, model: str, messages: list[str]) -> tuple[list[dict], int]:
    """Memory agent: lasting preferences from the traveller's own messages. A preference is
    kept only if its quote really is in one of the messages (checked in code).
    Returns (kept, proposed)."""
    msgs = [m.strip() for m in messages if isinstance(m, str) and m.strip()]
    if not msgs:
        return [], 0
    raw = llm.json(model, [
        {"role": "system", "content": MEMORY_SYSTEM},
        {"role": "user", "content": "TRAVELLER'S MESSAGES:\n" + "\n".join(f"- {m}" for m in msgs)}],
        default={}, max_tokens=500)
    proposed = [m for m in (raw.get("memories") or [])[:5] if isinstance(m, dict)]
    joined = " | ".join(_norm(m) for m in msgs)
    kept = []
    for m in proposed:
        quote, text = _norm(str(m.get("quote", ""))), str(m.get("text", "")).strip()
        if text and len(quote.split()) >= 2 and quote in joined:
            kept.append({"text": text, "quote": str(m["quote"]).strip()})
    return kept, len(proposed)


def trip_episode(request: dict, plan: dict, edits: list[str]) -> str:
    """One line describing an approved trip, for episodic recall."""
    from app.graph.critic import pretty

    towns = " + ".join(dict.fromkeys(pretty(d["destination"]) for d in plan.get("days", [])))
    months = ("January", "February", "March", "April", "May", "June", "July", "August",
              "September", "October", "November", "December")
    month = request.get("month")
    when = months[month - 1] if isinstance(month, int) and 1 <= month <= 12 else ""
    line = (f"{request.get('days')}-day trip to {towns}"
            + (f" in {when}" if when else "")
            + f" for {request.get('people')}, {request.get('tier')} tier")
    if edits:
        line += "; asked for changes: " + "; ".join(e[:80] for e in edits[:3])
    return line
