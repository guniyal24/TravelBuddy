"""Saved trips, traveller profiles and booking-checklist state (SQLite).

Separate from the LangGraph checkpoint file: checkpoints hold in-flight graph state, this holds
the user-facing records. On hosts with an ephemeral disk (Render free tier) the file is lost on
redeploy unless a persistent disk is mounted at TRIPS_PATH.
"""
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (email TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trips (
  trip_id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS trips_owner ON trips(owner, updated_at);
CREATE TABLE IF NOT EXISTS checks (
  trip_id TEXT NOT NULL, item_id TEXT NOT NULL, done INTEGER NOT NULL,
  PRIMARY KEY (trip_id, item_id));
"""

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


class TripStore:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- profiles ----
    def get_profile(self, email: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT data FROM profiles WHERE email=?", (email,)).fetchone()
        return json.loads(row[0]) if row else {}

    def save_profile(self, email: str, data: dict) -> dict:
        clean = clean_profile(data)
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO profiles VALUES (?, ?)",
                             (email, json.dumps(clean)))
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
        with self._lock, self._db:
            row = self._db.execute("SELECT created_at FROM trips WHERE trip_id=? AND owner=?",
                                   (trip_id, owner)).fetchone()
            self._db.execute(
                "INSERT OR REPLACE INTO trips VALUES (?, ?, ?, ?, ?, ?)",
                (trip_id, owner, title, row[0] if row else now, now, json.dumps(trip)))

    def get_trip(self, trip_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT owner, title, created_at, data FROM trips WHERE trip_id=?",
                (trip_id,)).fetchone()
            done = {r[0] for r in self._db.execute(
                "SELECT item_id FROM checks WHERE trip_id=? AND done=1", (trip_id,))}
        if not row:
            return None
        trip = json.loads(row[3])
        for item in trip.get("checklist", []):
            item["done"] = item["id"] in done
        return {"trip_id": trip_id, "owner": row[0], "title": row[1], "created_at": row[2],
                **trip}

    def list_trips(self, owner: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT trip_id, title, created_at, updated_at FROM trips WHERE owner=? "
                "ORDER BY updated_at DESC LIMIT 50", (owner,)).fetchall()
        return [{"trip_id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3]}
                for r in rows]

    def set_check(self, trip_id: str, item_id: str, done: bool) -> bool:
        """Tick or untick a checklist item; False if the trip has no such item."""
        trip = self.get_trip(trip_id)
        if not trip or item_id not in {i["id"] for i in trip.get("checklist", [])}:
            return False
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO checks VALUES (?, ?, ?)",
                             (trip_id, item_id, 1 if done else 0))
        return True
