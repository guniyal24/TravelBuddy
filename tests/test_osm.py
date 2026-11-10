from ingest import osm
from ingest.schema import Entity, EntityType, Source

SRC = Source(name="t", url="u")
DEST = Entity(
    id="destination_rishikesh", type=EntityType.DESTINATION, name="Rishikesh",
    lat=30.0869, lon=78.2676, source=SRC,
)
ELEMENTS = [
    {"type": "node", "lat": 30.10, "lon": 78.29, "tags": {"name": "Ganga Kinare Hotel"}},
    {"type": "way", "center": {"lat": 30.11, "lon": 78.30}, "tags": {"name": "Chotiwala"}},
    {"type": "node", "lat": 12.9, "lon": 77.6, "tags": {"name": "Spice Garden"}},  # wrong place
    {"type": "node", "lat": 30.3165, "lon": 78.0322, "tags": {"name": "Far Cafe"}},  # >15 km
]


def test_normalize_drops_noise_and_punctuation():
    assert osm.normalize("The Ganga Kinare Hotel & Resort") == "ganga kinare"


def test_exact_and_noise_insensitive_match():
    assert osm.match_name("Hotel Ganga Kinare", ELEMENTS, 30.0869, 78.2676) == (30.10, 78.29)


def test_way_center_used_and_small_typo_accepted():
    assert osm.match_name("Chotiwalas", ELEMENTS, 30.0869, 78.2676) == (30.11, 78.30)


def test_dissimilar_name_not_matched():
    assert osm.match_name("Bhagwati Chole Wala", ELEMENTS, 30.0869, 78.2676) is None


def test_rejects_outside_state_or_too_far():
    assert osm.match_name("Spice Garden", ELEMENTS, 30.0869, 78.2676) is None
    assert osm.match_name("Far Cafe", ELEMENTS, 30.0869, 78.2676) is None


def test_fill_from_osm_sets_source(monkeypatch):
    monkeypatch.setattr(osm, "fetch_osm_places", lambda *a, **k: ELEMENTS)
    stay = Entity(
        id="s1", type=EntityType.STAY, name="Ganga Kinare Hotel",
        destination_id=DEST.id, source=SRC,
    )
    stats = osm.fill_from_osm([stay], [DEST])
    assert stats == {"tried": 1, "filled": 1}
    assert (stay.lat, stay.coord_source) == (30.10, "osm")
