"""Fill missing coordinates using OSM Nominatim (data (c) OpenStreetMap contributors, ODbL).

Nominatim's usage policy allows ~1 request/second with an identifying User-Agent, which
`ingest.http.get_json` provides (plus an on-disk cache so re-runs cost nothing).

A match is accepted only if it falls inside Uttarakhand AND within MAX_KM of the
destination centre. A wrong pin is worse than no pin, because it would feed wrong
distances to the planner.
"""
import logging

from ingest.geo import haversine_km
from ingest.http import get_json
from ingest.schema import Entity, EntityType, in_uttarakhand

log = logging.getLogger(__name__)

API = "https://nominatim.openstreetmap.org/search"
MAX_KM = 15.0
VIEWBOX_DEG = 0.2  # search window around the destination centre


def geocode(name: str, dest_name: str, dest_lat: float, dest_lon: float) -> tuple[float, float] | None:
    params = {
        "q": f"{name}, {dest_name}, Uttarakhand",
        "format": "jsonv2",
        "limit": 3,
        "countrycodes": "in",
        "viewbox": (
            f"{dest_lon - VIEWBOX_DEG},{dest_lat + VIEWBOX_DEG},"
            f"{dest_lon + VIEWBOX_DEG},{dest_lat - VIEWBOX_DEG}"
        ),
        "bounded": 1,
    }
    try:
        results = get_json(API, params)
    except Exception:
        log.warning("Geocoding failed for %r", name)
        return None
    for r in results or []:
        try:
            lat, lon = float(r["lat"]), float(r["lon"])
        except (KeyError, ValueError):
            continue
        if in_uttarakhand(lat, lon) and haversine_km(lat, lon, dest_lat, dest_lon) <= MAX_KM:
            return lat, lon
    return None


def fill_missing_coordinates(entities: list[Entity], destinations: list[Entity]) -> dict:
    """Geocode places without coordinates. Returns counts for logging."""
    centres = {d.id: d for d in destinations if d.lat is not None and d.lon is not None}
    stats = {"tried": 0, "filled": 0}
    for e in entities:
        if e.type == EntityType.DESTINATION or e.lat is not None:
            continue
        dest = centres.get(e.destination_id or "")
        if dest is None:
            continue
        stats["tried"] += 1
        hit = geocode(e.name, dest.name, dest.lat, dest.lon)
        if hit:
            e.lat, e.lon = hit
            e.coord_source = "nominatim"
            stats["filled"] += 1
    return stats
