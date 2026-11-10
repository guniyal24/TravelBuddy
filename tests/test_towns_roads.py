"""Town registry, OpenStreetMap places, and the calibrated road matrix."""
from datetime import date

from app.rules.season import load_seasons
from app.towns import (
    ACCESS_NOTES,
    CIRCUITS,
    DESTINATIONS,
    ELEVATION_M,
    KUMAON,
    NOT_READY,
    PLACE_ALIASES,
    STATIONS,
)
from app.transport.routes import HILL_FACTOR, matrix_route, transport_options
from ingest.osm_places import classify, places_from_osm
from ingest.schema import EntityType


# ---------------------------------------------------------------- registry
def test_registry_is_complete_and_consistent():
    assert len(DESTINATIONS) >= 25
    seasons = load_seasons()
    for d, meta in DESTINATIONS.items():
        assert d in seasons, f"{d} has no season data"
        assert d in ELEVATION_M and d in STATIONS and meta["themes"]
        assert 28.7 <= meta["lat"] <= 31.5 and 77.5 <= meta["lon"] <= 81.1
        assert meta["name"].lower() in PLACE_ALIASES[d]
    for towns, days in CIRCUITS:
        assert all(t in DESTINATIONS for t in towns) and days >= len(towns)
    assert "destination_nainital" in KUMAON and "destination_haridwar" not in KUMAON
    assert NOT_READY < set(DESTINATIONS)  # some offered, some not


def test_aliases_are_unique_across_towns():
    seen = {}
    for d, aliases in PLACE_ALIASES.items():
        for a in aliases:
            assert seen.setdefault(a, d) == d, f"alias {a!r} used by {seen[a]} and {d}"


# ---------------------------------------------------------------- OSM places
def test_osm_tags_map_to_our_types_with_readable_descriptions():
    assert classify({"tourism": "guest_house"}) == (EntityType.STAY, "Guest house")
    assert classify({"tourism": "hotel", "stars": "3"}) == (EntityType.STAY, "Hotel, 3 star")
    assert classify({"amenity": "restaurant", "cuisine": "indian;regional",
                     "diet:vegetarian": "only"}) == (
        EntityType.EATERY, "Restaurant (cuisine: indian, regional; pure vegetarian)")
    assert classify({"amenity": "place_of_worship", "religion": "hindu"}) == (
        EntityType.ATTRACTION, "Hindu temple")
    assert classify({"natural": "peak", "ele": "3680"}) == (EntityType.ATTRACTION, "Peak, 3680 m")
    assert classify({"shop": "bakery"}) is None


def _el(i, name, tags, lat=29.84, lon=79.60):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"name": name, **tags}}


def test_osm_places_filter_dedupe_and_cap():
    cfg = {"id": "destination_kausani", "name": "Kausani", "lat": 29.843, "lon": 79.6045,
           "region": "Kumaon"}
    elements = [
        _el(1, "Anasakti Ashram", {"tourism": "attraction"}),
        _el(2, "Temple", {"amenity": "place_of_worship"}),  # generic name
        _el(3, "कौसानी होटल", {"tourism": "hotel"}),  # no Latin-script name
        _el(4, "Hotel Uttarakhand", {"tourism": "hotel"}),
        _el(5, "Far Away Inn", {"tourism": "hotel"}, lat=30.5, lon=80.5),  # outside radius
        _el(6, "Already Known Cafe", {"amenity": "cafe"}),  # in Wikivoyage already
        {"type": "way", "id": 7, "center": {"lat": 29.85, "lon": 79.61},
         "tags": {"name": "Tea Garden View", "tourism": "viewpoint"}},
        *[_el(100 + i, f"Shiva Temple {i}", {"amenity": "place_of_worship",
                                              "religion": "hindu"}) for i in range(12)],
    ]
    out = places_from_osm(cfg, date(2026, 11, 10), {"already known"}, elements=elements)
    names = [e.name for e in out]
    assert "Anasakti Ashram" in names and "Hotel Uttarakhand" in names
    assert "Tea Garden View" in names  # ways use their centre point
    for dropped in ("Temple", "कौसानी होटल", "Far Away Inn", "Already Known Cafe"):
        assert dropped not in names
    assert sum(1 for n in names if n.startswith("Shiva Temple")) == 8  # worship cap
    e = next(x for x in out if x.name == "Hotel Uttarakhand")
    assert e.destination_id == "destination_kausani" and e.source.name == "OpenStreetMap"
    assert e.source.url == "https://www.openstreetmap.org/node/4" and e.coord_source == "osm"


# ---------------------------------------------------------------- roads
def test_matrix_fills_pairs_with_calibrated_hill_times():
    r = matrix_route("destination_almora", "destination_kausani")
    assert 40 <= r["km"] <= 70
    lo, hi = r["hours"]
    assert lo < hi and HILL_FACTOR == (1.5, 2.1)
    assert matrix_route("destination_almora", "destination_almora") is None
    assert matrix_route("destination_almora", "city_mumbai") is None


def test_curated_routes_win_and_matrix_fills_the_rest():
    curated = transport_options("destination_haridwar", "destination_rishikesh")
    assert curated["confidence"] == "curated_unverified" and curated["distance_km"] == 25
    filled = transport_options("delhi", "destination_lansdowne", 2)
    assert filled["found"] and filled["confidence"] == "osrm_calibrated"
    assert filled["fares"]["source"] == "assumption"


def test_trek_access_is_always_mentioned():
    assert set(ACCESS_NOTES) == {"destination_kedarnath", "destination_ghangaria"}
    r = transport_options("destination_joshimath", "destination_ghangaria")
    assert "trek" in r["note"]
