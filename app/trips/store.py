"""Saved trips, traveller profiles and booking-checklist state.

Separate from the LangGraph checkpoints: checkpoints hold in-flight graph state, this holds the
user-facing records. The same SQL runs on two backends:

  TripStore("postgresql://...")   Postgres (set DATABASE_URL), survives redeploys
  TripStore("data/trips.sqlite")  SQLite file (default), or ":memory:" in tests

On hosts with an ephemeral disk (Render free tier) the SQLite file is lost on every redeploy.
"""
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.graph.persistence import is_postgres, make_pg_pool

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS profiles (email TEXT PRIMARY KEY, data TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS trips (
      trip_id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS trips_owner ON trips(owner, updated_at)",
    """CREATE TABLE IF NOT EXISTS checks (
      trip_id TEXT NOT NULL, item_id TEXT NOT NULL, done INTEGER NOT NULL,
      PRIMARY KEY (trip_id, item_id))""",
    # one row per planner run (start, each resume, re-plan): what that step cost
    """CREATE TABLE IF NOT EXISTS trip_usage (
      trip_id TEXT NOT NULL, step TEXT NOT NULL, at TEXT NOT NULL, llm_calls INTEGER NOT NULL,
      tokens_in INTEGER NOT NULL, tokens_out INTEGER NOT NULL, cost_usd REAL NOT NULL,
      seconds REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS trip_usage_trip ON trip_usage(trip_id)",
]

PROFILE_FIELDS = {"tier": str, "diet": str, "language": str, "origin": str,
                  "interests": list, "vulnerable_travellers": bool, "pace": str}
TIERS = ("budget", "mid", "premium")
DIETS = ("", "veg", "non-veg")
LANGUAGES = ("en", "hi", "hinglish")
PACES = ("", "relaxed", "balanced", "packed")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_profile(data: dict) -> dict:
    """Keep only known fields with valid values; never trust client input."""
    out: dict = {}
    if data.get("tier") in TIERS:
        out["tier"] = data["tier"]
    if data.get("diet") in DIETS:
        out["diet"] = data["diet"]
    if data.get("language") in LANGUAGES:
        out["language"] = data["language"]
    if data.get("pace") in PACES:
        out["pace"] = data["pace"]
    if isinstance(data.get("origin"), str):
        out["origin"] = data["origin"].strip()[:60]
    if isinstance(data.get("interests"), list):
        out["interests"] = [str(i).strip().lower()[:30] for i in data["interests"]
                            if str(i).strip()][:12]
    if isinstance(data.get("vulnerable_travellers"), bool):
        out["vulnerable_travellers"] = data["vulnerable_travellers"]
    return out


class _SQLite:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def run(self, *statements: tuple[str, tuple]) -> None:
        """Execute statements in one transaction."""
        with self._lock, self._db:
            for sql, params in statements:
                self._db.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._db.close()


class _Postgres:
    def __init__(self, url: str):
        self._pool = make_pg_pool(url)

    @staticmethod
    def _sql(sql: str) -> str:
        return sql.replace("?", "%s")  # our SQL never contains a literal '?'

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with self._pool.connection() as conn:
            rows = conn.execute(self._sql(sql), params).fetchall()
        return [tuple(r.values()) for r in rows]  # the pool hands out dict rows

    def run(self, *statements: tuple[str, tuple]) -> None:
        with self._pool.connection() as conn, conn.transaction():
            for sql, params in statements:
                conn.execute(self._sql(sql), params)

    def close(self) -> None:
        self._pool.close()


class TripStore:
    def __init__(self, location: str = ":memory:"):
        self._db = _Postgres(location) if is_postgres(location) else _SQLite(location)
        self._db.run(*[(s, ()) for s in SCHEMA])

    def close(self) -> None:
        self._db.close()

    # ---- profiles ----
    def get_profile(self, email: str) -> dict:
        rows = self._db.query("SELECT data FROM profiles WHERE email=?", (email,))
        return json.loads(rows[0][0]) if rows else {}

    def save_profile(self, email: str, data: dict) -> dict:
        clean = clean_profile(data)
        self._db.run(("INSERT INTO profiles (email, data) VALUES (?, ?) "
                      "ON CONFLICT (email) DO UPDATE SET data = excluded.data",
                      (email, json.dumps(clean))))
        return clean

    def learn(self, email: str, request: dict) -> dict:
        """Remember what the traveller chose on an approved trip. Explicit profile values the
        traveller set win: only fields still empty are filled, and interests accumulate."""
        profile = self.get_profile(email)
        learned = dict(profile)
        for key in ("tier", "origin", "diet", "pace"):
            if request.get(key) and not profile.get(key):
                learned[key] = request[key]
        if request.get("language") in ("hi", "hinglish") and not profile.get("language"):
            learned["language"] = request["language"]
        interests = list(dict.fromkeys([*profile.get("interests", []),
                                        *[str(i).lower() for i in request.get("interests", [])]]))
        if interests:
            learned["interests"] = interests[:12]
        if request.get("vulnerable_travellers") and "vulnerable_travellers" not in profile:
            learned["vulnerable_travellers"] = True
        return self.save_profile(email, learned)

    # ---- trips ----
    def save_trip(self, trip_id: str, owner: str, trip: dict) -> None:
        req = trip.get("request", {})
        names = [d["destination"].removeprefix("destination_").replace("_", " ").title()
                 for d in trip.get("plan", {}).get("days", [])]
        places = ", ".join(dict.fromkeys(names)) or "Uttarakhand"
        title = f"{req.get('days', '?')} days: {places}"
        now = _now()
        # created_at is kept on update (a re-planned trip keeps its original date)
        self._db.run((
            "INSERT INTO trips (trip_id, owner, title, created_at, updated_at, data) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (trip_id) DO UPDATE SET "
            "owner = excluded.owner, title = excluded.title, updated_at = excluded.updated_at, "
            "data = excluded.data",
            (trip_id, owner, title, now, now, json.dumps(trip))))

    def get_trip(self, trip_id: str) -> dict | None:
        rows = self._db.query(
            "SELECT owner, title, created_at, data FROM trips WHERE trip_id=?", (trip_id,))
        if not rows:
            return None
        owner, title, created_at, data = rows[0]
        done = {r[0] for r in self._db.query(
            "SELECT item_id FROM checks WHERE trip_id=? AND done=1", (trip_id,))}
        trip = json.loads(data)
        for item in trip.get("checklist", []):
            item["done"] = item["id"] in done
        return {"trip_id": trip_id, "owner": owner, "title": title, "created_at": created_at,
                **trip}

    def list_trips(self, owner: str) -> list[dict]:
        rows = self._db.query(
            "SELECT trip_id, title, created_at, updated_at FROM trips WHERE owner=? "
            "ORDER BY updated_at DESC LIMIT 50", (owner,))
        return [{"trip_id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
                for r in rows]

    # ---- usage (cost and latency) ----
    def record_usage(self, trip_id: str, step: str, u: dict) -> None:
        self._db.run(("INSERT INTO trip_usage (trip_id, step, at, llm_calls, tokens_in, "
                      "tokens_out, cost_usd, seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (trip_id, step[:20], _now(), int(u.get("llm_calls", 0)),
                       int(u.get("tokens_in", 0)), int(u.get("tokens_out", 0)),
                       float(u.get("cost_usd", 0.0)), float(u.get("seconds", 0.0)))))

    def trip_usage(self, trip_id: str) -> dict:
        rows = self._db.query(
            "SELECT COUNT(*), COALESCE(SUM(llm_calls), 0), COALESCE(SUM(tokens_in), 0), "
            "COALESCE(SUM(tokens_out), 0), COALESCE(SUM(cost_usd), 0), COALESCE(SUM(seconds), 0) "
            "FROM trip_usage WHERE trip_id=?", (trip_id,))
        n, calls, tin, tout, usd, secs = rows[0]
        return {"runs": n, "llm_calls": int(calls), "tokens_in": int(tin),
                "tokens_out": int(tout), "cost_usd": round(float(usd), 5),
                "seconds": round(float(secs), 1)}

    def usage_stats(self) -> dict:
        """Cost and agent time per completed trip (only trips that were approved and saved),
        as medians and 90th percentiles. Time is the agents' working time, not the minutes a
        traveller spends deciding."""
        rows = self._db.query(
            "SELECT u.trip_id, SUM(u.llm_calls), SUM(u.cost_usd), SUM(u.seconds) "
            "FROM trip_usage u JOIN trips t ON t.trip_id = u.trip_id GROUP BY u.trip_id", ())
        if not rows:
            return {"trips": 0}

        def pct(values: list[float], q: float) -> float:
            v = sorted(values)
            return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]

        calls = [float(r[1]) for r in rows]
        usd = [float(r[2]) for r in rows]
        secs = [float(r[3]) for r in rows]
        return {"trips": len(rows),
                "llm_calls": {"p50": pct(calls, 0.5), "p90": pct(calls, 0.9)},
                "cost_usd": {"p50": round(pct(usd, 0.5), 5), "p90": round(pct(usd, 0.9), 5)},
                "seconds": {"p50": round(pct(secs, 0.5), 1), "p90": round(pct(secs, 0.9), 1)}}

    def set_check(self, trip_id: str, item_id: str, done: bool) -> bool:
        """Tick or untick a checklist item; False if the trip has no such item."""
        trip = self.get_trip(trip_id)
        if not trip or item_id not in {i["id"] for i in trip.get("checklist", [])}:
            return False
        self._db.run(("INSERT INTO checks (trip_id, item_id, done) VALUES (?, ?, ?) "
                      "ON CONFLICT (trip_id, item_id) DO UPDATE SET done = excluded.done",
                      (trip_id, item_id, 1 if done else 0)))
        return True
