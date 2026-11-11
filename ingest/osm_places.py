"""OpenStreetMap as a primary source of places for towns Wikivoyage covers thinly.

Data (c) OpenStreetMap contributors, ODbL. One Overpass query per town (cached on disk), then:
  * tags -> our types: hotels/guest houses/hostels/camps -> Stay; restaurants/cafes -> Eatery;
    viewpoints, temples, waterfalls, peaks, museums, forts, parks -> Attraction
  * a readable description built from the tags (religion, cuisine, vegetarian diet, elevation)
  * only places with a usable Latin-script name; generic names ("Temple", "Hotel") dropped
  * de-duplicated against the town's Wikivoyage listings, nearest to the centre first, capped
    per type so one town cannot flood the knowledge base
OSM places carry less detail than Wikivoyage listings (rarely prices or opening hours); the
source on every entity says where it came from.
"""
import hashlib
import json
import logging
import re
import time
from datetime import date

import httpx

from ingest.geo import haversine_km
from ingest.http import RAW_DIR, USER_AGENT
from ingest.osm import MIRRORS, normalize
from ingest.schema import Confidence, Entity, EntityType, Source, in_uttarakhand, make_id

log = logging.getLogger(__name__)

CAPS = {EntityType.STAY: 15, EntityType.EATERY: 12, EntityType.ATTRACTION: 20}
MAX_WORSHIP = 8  # temples are everywhere; keep the attraction list varied
GENERIC = {"temple", "mandir", "hotel", "restaurant", "cafe", "guest house", "dhaba", "homestay",
           "shiv mandir", "hanuman mandir", "durga mandir", "masjid", "church", "viewpoint",
           "view point", "waterfall", "park", "camp", "garage", "parking", "house", "home",
           "shop"}

STAY = {"hotel", "guest_house", "hostel", "motel", "apartment", "camp_site", "alpine_hut",
        "chalet"}
EAT = {"restaurant", "cafe", "fast_food", "food_court"}
SIGHT_TOURISM = {"attraction", "viewpoint", "museum", "gallery"}
SIGHT_NATURAL = {"waterfall", "peak", "glacier", "spring"}
SIGHT_HISTORIC = {"monument", "fort", "ruins", "castle", "memorial", "archaeological_site"}


def _query(lat: float, lon: float, radius: int) -> str:
    a = f"(around:{radius},{lat},{lon})"
    return ("[out:json][timeout:90];("
            f'nwr{a}["name"]["tourism"~"^({"|".join(STAY | SIGHT_TOURISM)})$"];'
            f'nwr{a}["name"]["amenity"~"^(restaurant|cafe|fast_food|food_court|place_of_worship)$"];'
            f'nwr{a}["name"]["natural"~"^({"|".join(SIGHT_NATURAL)})$"];'
            f'nwr{a}["name"]["historic"~"^({"|".join(SIGHT_HISTORIC)})$"];'
            f'nwr{a}["name"]["leisure"~"^(park|nature_reserve)$"];'
            ");out center tags;")


def fetch(lat: float, lon: float, radius: int, rounds: int = 3) -> list[dict]:
    key = hashlib.sha256(f"osmplaces{lat:.4f},{lon:.4f},{radius}".encode()).hexdigest()[:20]
    cache = RAW_DIR / f"osmp_{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    query = _query(lat, lon, radius)
    for attempt in range(rounds):
        for url in MIRRORS:
            try:
                r = httpx.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT},
                               timeout=120)
                if r.status_code == 200:
                    elements = r.json()["elements"]
                    RAW_DIR.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps(elements))
                    return elements
                log.warning("Overpass %s -> %s", url, r.status_code)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                log.warning("Overpass %s failed: %s", url, exc)
        time.sleep(10 * (attempt + 1))
    log.warning("Overpass unavailable for (%s, %s)", lat, lon)
    return []


def _name(tags: dict) -> str | None:
    for key in ("name:en", "name", "int_name"):
        n = (tags.get(key) or "").strip()
        if n and re.search(r"[A-Za-z]{3}", n) and not re.search(r"[ऀ-ॿ]", n):
            return n if normalize(n) and n.lower() not in GENERIC else None
    return None


def classify(tags: dict) -> tuple[EntityType, str] | None:
    """(type, short description) for an OSM element, or None if we do not use it."""
    t, a = tags.get("tourism"), tags.get("amenity")
    if t in STAY:
        kind = {"guest_house": "Guest house", "hostel": "Hostel", "camp_site": "Campsite",
                "alpine_hut": "Mountain hut", "apartment": "Holiday apartment",
                "chalet": "Chalet", "motel": "Motel"}.get(t, "Hotel")
        stars = tags.get("stars")
        return EntityType.STAY, kind + (f", {stars} star" if stars else "")
    if a in EAT:
        kind = {"cafe": "Cafe", "fast_food": "Fast food", "food_court": "Food court"}.get(
            a, "Restaurant")
        bits = []
        if tags.get("cuisine"):
            bits.append("cuisine: " + tags["cuisine"].replace(";", ", ").replace("_", " "))
        if tags.get("diet:vegetarian") in ("only", "yes"):
            bits.append("pure vegetarian" if tags["diet:vegetarian"] == "only"
                        else "vegetarian options")
        return EntityType.EATERY, kind + (f" ({'; '.join(bits)})" if bits else "")
    if a == "place_of_worship":
        religion = tags.get("religion", "")
        word = {"hindu": "Hindu temple", "sikh": "Gurdwara", "buddhist": "Buddhist monastery",
                "muslim": "Mosque", "christian": "Church", "jain": "Jain temple"}
        return EntityType.ATTRACTION, word.get(religion, "Place of worship")
    if t in SIGHT_TOURISM:
        return EntityType.ATTRACTION, {"viewpoint": "Viewpoint", "museum": "Museum",
                                       "gallery": "Art gallery"}.get(t, "Attraction")
    nat, his, lei = tags.get("natural"), tags.get("historic"), tags.get("leisure")
    if nat in SIGHT_NATURAL:
        ele = tags.get("ele")
        return EntityType.ATTRACTION, nat.capitalize() + (f", {ele} m" if ele else "")
    if his in SIGHT_HISTORIC:
        return EntityType.ATTRACTION, "Historic " + his.replace("_", " ")
    if lei in ("park", "nature_reserve"):
        return EntityType.ATTRACTION, "Nature reserve" if lei == "nature_reserve" else "Park"
    return None


def _point(el: dict) -> tuple[float, float] | None:
    if "lat" in el and "lon" in el:
        return el["lat"], el["lon"]
    c = el.get("center") or {}
    return (c["lat"], c["lon"]) if "lat" in c and "lon" in c else None


def places_from_osm(cfg: dict, today: date, known_names: set[str], radius_m: int = 9000,
                    elements: list[dict] | None = None) -> list[Entity]:
    """Entities for one town from OSM, skipping names we already have."""
    elements = elements if elements is not None else fetch(cfg["lat"], cfg["lon"], radius_m)
    candidates = []
    for el in elements:
        tags = el.get("tags") or {}
        name, kind, pt = _name(tags), classify(tags), _point(el)
        if not name or not kind or not pt or not in_uttarakhand(*pt):
            continue
        km = haversine_km(cfg["lat"], cfg["lon"], *pt)
        if km > radius_m / 1000 + 0.5:
            continue
        candidates.append((km, name, kind, pt, el, tags))
    candidates.sort(key=lambda c: c[0])
    seen = set(known_names)
    counts: dict[EntityType, int] = {}
    worship = 0
    out = []
    for km, name, (etype, desc), (lat, lon), el, tags in candidates:
        key = normalize(name)
        if key in seen or counts.get(etype, 0) >= CAPS[etype]:
            continue
        if tags.get("amenity") == "place_of_worship":
            if worship >= MAX_WORSHIP:
                continue
            worship += 1
        seen.add(key)
        counts[etype] = counts.get(etype, 0) + 1
        description = f"{desc}, about {km:.1f} km from the centre of {cfg['name']}."
        osm_url = f"https://www.openstreetmap.org/{el['type']}/{el['id']}"
        out.append(Entity(
            id=make_id(etype, cfg["name"], name), type=etype, name=name,
            destination_id=cfg["id"], description=description,
            semantic_text=f"{name}: {description} {cfg['name']}, Uttarakhand.",
            lat=lat, lon=lon, coord_source="osm", region=cfg.get("region", ""),
            phone=tags.get("phone", "")[:40], url=tags.get("website", "")[:200],
            tags=[f"osm:{k}={tags[k]}" for k in ("tourism", "amenity", "natural", "historic",
                                                  "leisure", "religion", "cuisine")
                  if tags.get(k)],
            source=Source(name="OpenStreetMap", url=osm_url, license="ODbL 1.0",
                          fetched_at=today),
            confidence=Confidence.SOURCED))
    return out
