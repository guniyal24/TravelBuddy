"""Fill missing coordinates by fuzzy-matching names against OpenStreetMap places.

Data (c) OpenStreetMap contributors, ODbL. We pull every named hotel / guest house /
restaurant / attraction / place of worship around a destination from the Overpass API
once (cached on disk) and match listing names against them locally. Local matching is
far kinder to the public Overpass servers than one query per place.

Only confident matches are accepted (see `normalize` and MATCH_THRESHOLD); listings
without a match keep no coordinates and fall back to destination-level location.
"""
import hashlib
import json
import logging
import re
import time
from difflib import SequenceMatcher

import httpx

from ingest.geo import haversine_km
from ingest.http import RAW_DIR, USER_AGENT
from ingest.schema import Entity, EntityType, in_uttarakhand

log = logging.getLogger(__name__)

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
RADIUS_M = 12000
MAX_KM = 15.0
MATCH_THRESHOLD = 0.88
NOISE_WORDS = {"hotel", "restaurant", "the", "resort", "guest", "house", "cafe", "and", "n", "dhaba"}


def normalize(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", name.lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in NOISE_WORDS)


def _query(lat: float, lon: float, radius: int) -> str:
    return (
        f'[out:json][timeout:60];('
        f'nwr(around:{radius},{lat},{lon})["name"]'
        f'["tourism"~"hotel|guest_house|hostel|motel|attraction|apartment"];'
        f'nwr(around:{radius},{lat},{lon})["name"]'
        f'["amenity"~"restaurant|cafe|fast_food|place_of_worship|food_court"];'
        f");out center tags;"
    )


def fetch_osm_places(lat: float, lon: float, radius: int = RADIUS_M, rounds: int = 3) -> list[dict]:
    """Return named OSM elements around a point; cached on disk; rotates through mirrors."""
    key = hashlib.sha256(f"osm{lat:.4f},{lon:.4f},{radius}".encode()).hexdigest()[:20]
    cache = RAW_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    query = _query(lat, lon, radius)
    for attempt in range(rounds):
        for url in MIRRORS:
            try:
                r = httpx.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT},
                               timeout=90)
                if r.status_code == 200:
                    elements = r.json()["elements"]
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(elements))
                    return elements
                log.warning("Overpass %s -> %s", url, r.status_code)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("Overpass %s failed: %s", url, exc)
        time.sleep(10 * (attempt + 1))
    log.warning("Overpass unavailable; skipping OSM coordinates for (%s, %s)", lat, lon)
    return []


def _point(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


def match_name(name: str, elements: list[dict], dest_lat: float, dest_lon: float
               ) -> tuple[float, float] | None:
    target = normalize(name)
    if len(target) < 3:
        return None
    best: tuple[float, tuple[float, float]] | None = None
    for el in elements:
        osm_name = (el.get("tags") or {}).get("name", "")
        pt = _point(el)
        if not osm_name or pt is None:
            continue
        cand = normalize(osm_name)
        if not cand:
            continue
        score = 1.0 if cand == target else SequenceMatcher(None, target, cand).ratio()
        if score < MATCH_THRESHOLD:
            continue
        if not in_uttarakhand(*pt) or haversine_km(*pt, dest_lat, dest_lon) > MAX_KM:
            continue
        if best is None or score > best[0]:
            best = (score, pt)
    return best[1] if best else None


def fill_from_osm(entities: list[Entity], destinations: list[Entity]) -> dict:
    stats = {"tried": 0, "filled": 0}
    for dest in destinations:
        if dest.lat is None or dest.lon is None:
            continue
        missing = [e for e in entities if e.destination_id == dest.id
                   and e.lat is None and e.type != EntityType.DESTINATION]
        if not missing:
            continue
        elements = fetch_osm_places(dest.lat, dest.lon)
        for e in missing:
            stats["tried"] += 1
            hit = match_name(e.name, elements, dest.lat, dest.lon)
            if hit:
                e.lat, e.lon = hit
                e.coord_source = "osm"
                stats["filled"] += 1
    return stats
