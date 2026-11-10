"""Optional enrichment from the Google Places API (New), Text Search.

Opt-in: runs only with `--google` and a `GOOGLE_PLACES_API_KEY` in the environment.

Cost and terms guard-rails:
- `max_requests` caps billable calls per run (default 100) so a bug cannot run up a bill.
- Responses are cached on disk (git-ignored `data/raw/`), so re-runs are free.
- As we understand Google's terms, `place_id` may be stored indefinitely but coordinates
  may only be cached for a limited time (30 days at the time of writing). Cached entries
  therefore expire after CACHE_DAYS and are re-fetched. Check the current Google Maps
  Platform terms before publishing a dataset containing Google-sourced coordinates.
"""
import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

import httpx

from ingest.geo import haversine_km
from ingest.http import RAW_DIR, USER_AGENT
from ingest.osm import normalize
from ingest.schema import Entity, EntityType, in_uttarakhand

log = logging.getLogger(__name__)

API = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.displayName,places.location"
MAX_KM = 15.0
NAME_SIMILARITY = 0.6  # looser than OSM: Google display names often add words
CACHE_DAYS = 30


def api_key() -> str | None:
    return os.getenv("GOOGLE_PLACES_API_KEY") or None


def _cache_path(name: str, dest: str):
    key = hashlib.sha256(f"gp|{name}|{dest}".encode()).hexdigest()[:20]
    return RAW_DIR / f"gp_{key}.json"


def _load_cache(path) -> dict | None:
    if not path.exists():
        return None
    entry = json.loads(path.read_text())
    fetched = datetime.fromisoformat(entry["fetched_at"])
    if datetime.now(UTC) - fetched > timedelta(days=CACHE_DAYS):
        return None
    return entry


def pick_match(places: list[dict], name: str, dest_lat: float, dest_lon: float) -> dict | None:
    """Choose the best result that is inside the state, near the destination, and
    similar enough in name. Returns {place_id, lat, lon} or None."""
    target = normalize(name)
    best = None
    for p in places:
        loc = p.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            continue
        if not in_uttarakhand(lat, lon) or haversine_km(lat, lon, dest_lat, dest_lon) > MAX_KM:
            continue
        shown = normalize((p.get("displayName") or {}).get("text", ""))
        score = SequenceMatcher(None, target, shown).ratio() if target and shown else 0.0
        if score < NAME_SIMILARITY:
            continue
        if best is None or score > best[0]:
            best = (score, {"place_id": p.get("id", ""), "lat": lat, "lon": lon})
    return best[1] if best else None


def search_place(name: str, dest_name: str, dest_lat: float, dest_lon: float, key: str) -> dict | None:
    """One Text Search call (billable). Returns a cache-shaped dict or None."""
    body = {
        "textQuery": f"{name}, {dest_name}, Uttarakhand",
        "maxResultCount": 3,
        "locationBias": {
            "circle": {"center": {"latitude": dest_lat, "longitude": dest_lon}, "radius": 15000.0}
        },
    }
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK, "User-Agent": USER_AGENT}
    r = httpx.post(API, json=body, headers=headers, timeout=30)
    r.raise_for_status()
    return pick_match(r.json().get("places", []), name, dest_lat, dest_lon)


def fill_from_google(entities: list[Entity], destinations: list[Entity], max_requests: int = 100
                     ) -> dict:
    stats = {"tried": 0, "filled": 0, "api_calls": 0, "cached": 0, "skipped_over_cap": 0}
    key = api_key()
    if not key:
        log.warning("GOOGLE_PLACES_API_KEY not set; skipping Google Places.")
        return stats
    centres = {d.id: d for d in destinations if d.lat is not None and d.lon is not None}

    for e in entities:
        if e.type == EntityType.DESTINATION or e.lat is not None:
            continue
        dest = centres.get(e.destination_id or "")
        if dest is None:
            continue
        stats["tried"] += 1
        path = _cache_path(e.name, dest.name)
        entry = _load_cache(path)
        if entry is not None:
            stats["cached"] += 1
        else:
            if stats["api_calls"] >= max_requests:
                stats["skipped_over_cap"] += 1
                continue
            try:
                match = search_place(e.name, dest.name, dest.lat, dest.lon, key)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (400, 401, 403):
                    # Auth / API-not-enabled / bad key: every call would fail, so stop.
                    log.error("Google Places rejected the request (%s): %s",
                              exc.response.status_code, exc.response.text[:300])
                    stats["aborted"] = exc.response.status_code
                    break
                log.warning("Google Places failed for %r: %s", e.name, exc)
                continue
            except httpx.HTTPError as exc:
                log.warning("Google Places failed for %r: %s", e.name, exc)
                continue
            stats["api_calls"] += 1
            entry = {"fetched_at": datetime.now(UTC).isoformat(), "match": match}
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(entry))
            time.sleep(0.2)
        m = entry["match"]
        if m:
            e.lat, e.lon = m["lat"], m["lon"]
            e.google_place_id = m["place_id"]
            e.coord_source = "google"
            stats["filled"] += 1
    return stats
