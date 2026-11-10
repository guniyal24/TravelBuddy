"""Hotel ratings and reviews from the Google Places API (New), Text Search.

Used by the Concierge stage after a plan is approved. One billable call per hotel; guard-rails:
  * PLACES_DAILY_CAP calls per process per day (default 300), so a bug or abuse cannot run up a
    bill; past it the tool reports itself unavailable
  * results kept in memory only, for CACHE_HOURS: Google's terms restrict storing Places
    content, so nothing is written to disk or a database
  * the match must be near the town and similar in name (ingest.google_places.pick_match), so a
    different hotel's reviews are never attached to ours
Reviews are shown with the author's name and a link, as Google's attribution rules require.
"""
import os
import re
import threading
import time
from datetime import date

import httpx
from dotenv import load_dotenv

from ingest.google_places import pick_match

load_dotenv(override=False)  # the MCP server may run as its own process

API = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(f"places.{f}" for f in (
    "id", "displayName", "location", "rating", "userRatingCount", "reviews", "googleMapsUri",
    "formattedAddress"))
CACHE_HOURS = 6
MAX_REVIEW_CHARS = 700

_lock = threading.Lock()
_cache: dict[tuple, tuple[float, dict]] = {}
_usage = {"day": date.today(), "calls": 0}


def _key() -> str | None:
    return os.getenv("GOOGLE_PLACES_API_KEY") or None


def _cap() -> int:
    return int(os.getenv("PLACES_DAILY_CAP", "300"))


def _take_quota() -> bool:
    with _lock:
        if _usage["day"] != date.today():
            _usage.update(day=date.today(), calls=0)
        if _usage["calls"] >= _cap():
            return False
        _usage["calls"] += 1
        return True


def _review(i: int, r: dict) -> dict | None:
    text = ((r.get("text") or {}).get("text") or (r.get("originalText") or {}).get("text") or "")
    text = " ".join(text.split())[:MAX_REVIEW_CHARS]
    if not text:
        return None
    author = r.get("authorAttribution") or {}
    return {"id": f"r{i + 1}", "rating": r.get("rating"), "text": text,
            "author": author.get("displayName", "Google user"), "author_uri": author.get("uri"),
            "when": r.get("relativePublishTimeDescription", "")}


def place_reviews(hotel: str, town: str, lat: float, lon: float, max_reviews: int = 5,
                  client: httpx.Client | None = None) -> dict:
    """Rating, review count and up to five recent reviews for a named hotel in a town."""
    key = _key()
    if not key:
        return {"available": False, "reason": "Google Places is not configured."}
    cache_key = (hotel.lower(), town.lower(), round(lat, 3), round(lon, 3))
    with _lock:
        hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < CACHE_HOURS * 3600:
        return hit[1]
    if not _take_quota():
        return {"available": False, "reason": "Daily review lookups are used up; try later."}
    body = {"textQuery": f"{hotel}, {town}, Uttarakhand", "maxResultCount": 3,
            "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                        "radius": 15000.0}}}
    headers = {"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK}
    try:
        http = client or httpx.Client(timeout=15)
        r = http.post(API, json=body, headers=headers)
        r.raise_for_status()
        places = r.json().get("places", [])
    except (httpx.HTTPError, ValueError) as exc:
        return {"available": False,
                "reason": f"Google Places request failed ({type(exc).__name__})."}
    # Google often appends the town ("Hotel Golden Haridwar"); compare names without it.
    town_re = re.compile(rf"[\s,(-]*\b{re.escape(town)}\b[\s,)]*", re.IGNORECASE)
    for_match = [{**p, "displayName": {"text": town_re.sub(" ", (p.get("displayName") or {})
                                                            .get("text", "")).strip()}}
                 for p in places]
    match = pick_match(for_match, hotel, lat, lon)
    if not match:
        out = {"available": True, "found": False}
    else:
        p = next(x for x in places if x.get("id") == match["place_id"])
        reviews = [x for i, r in enumerate((p.get("reviews") or [])[:max_reviews])
                   if (x := _review(i, r))]
        out = {"available": True, "found": True, "place_id": p.get("id"),
               "name": (p.get("displayName") or {}).get("text", hotel),
               "rating": p.get("rating"), "review_count": p.get("userRatingCount") or 0,
               "maps_url": p.get("googleMapsUri"), "address": p.get("formattedAddress"),
               "reviews": reviews, "source": "Google"}
    with _lock:
        _cache[cache_key] = (time.time(), out)
    return out
