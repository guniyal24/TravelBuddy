from ingest import geocode
from ingest.schema import Entity, EntityType, Source

SRC = Source(name="t", url="u")
DEST = Entity(
    id="destination_rishikesh", type=EntityType.DESTINATION, name="Rishikesh",
    lat=30.0869, lon=78.2676, source=SRC,
)


def _place(name, lat=None, lon=None):
    return Entity(
        id=f"stay_{name}", type=EntityType.STAY, name=name, destination_id=DEST.id,
        lat=lat, lon=lon, source=SRC,
    )


def _fake(results):
    return lambda url, params=None, **kw: results


def test_accepts_nearby_match(monkeypatch):
    monkeypatch.setattr(geocode, "get_json", _fake([{"lat": "30.10", "lon": "78.29"}]))
    assert geocode.geocode("Hotel X", "Rishikesh", 30.0869, 78.2676) == (30.10, 78.29)


def test_rejects_match_far_from_destination(monkeypatch):
    # Dehradun-ish coordinates are > 15 km from the Rishikesh centre
    monkeypatch.setattr(geocode, "get_json", _fake([{"lat": "30.3165", "lon": "78.0322"}]))
    assert geocode.geocode("Hotel X", "Rishikesh", 30.0869, 78.2676) is None


def test_rejects_outside_uttarakhand_and_bad_rows(monkeypatch):
    rows = [{"lat": "12.9", "lon": "77.6"}, {"nope": 1}, {"lat": "x", "lon": "y"}]
    monkeypatch.setattr(geocode, "get_json", _fake(rows))
    assert geocode.geocode("Hotel X", "Rishikesh", 30.0869, 78.2676) is None


def test_network_error_returns_none(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(geocode, "get_json", boom)
    assert geocode.geocode("Hotel X", "Rishikesh", 30.0869, 78.2676) is None


def test_fill_only_touches_missing_and_records_source(monkeypatch):
    monkeypatch.setattr(geocode, "get_json", _fake([{"lat": "30.10", "lon": "78.29"}]))
    has = _place("has", 30.11, 78.30)
    missing = _place("missing")
    stats = geocode.fill_missing_coordinates([has, missing], [DEST])
    assert stats == {"tried": 1, "filled": 1}
    assert (has.lat, has.coord_source) == (30.11, "")
    assert (missing.lat, missing.coord_source) == (30.10, "nominatim")
