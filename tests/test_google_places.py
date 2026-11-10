import json
from datetime import UTC, datetime, timedelta

import pytest

from ingest import google_places as gp
from ingest.schema import Entity, EntityType, Source

SRC = Source(name="t", url="u")
DEST = Entity(
    id="destination_haridwar", type=EntityType.DESTINATION, name="Haridwar",
    lat=29.9457, lon=78.1642, source=SRC,
)


def _place(name):
    return Entity(
        id=f"e_{name}", type=EntityType.STAY, name=name, destination_id=DEST.id, source=SRC
    )


def _result(name, lat, lon, pid="pid1"):
    return {"id": pid, "displayName": {"text": name}, "location": {"latitude": lat, "longitude": lon}}


@pytest.fixture(autouse=True)
def tmp_raw(tmp_path, monkeypatch):
    monkeypatch.setattr(gp, "RAW_DIR", tmp_path)


def test_pick_match_accepts_similar_nearby():
    m = gp.pick_match([_result("Hotel Haridwar Residency", 29.95, 78.17)],
                      "Haridwar Residency", 29.9457, 78.1642)
    assert m == {"place_id": "pid1", "lat": 29.95, "lon": 78.17}


def test_pick_match_rejects_dissimilar_far_or_outside():
    assert gp.pick_match([_result("Totally Different Cafe", 29.95, 78.17)],
                         "Haridwar Residency", 29.9457, 78.1642) is None
    assert gp.pick_match([_result("Haridwar Residency", 28.6, 77.2)],  # Delhi
                         "Haridwar Residency", 29.9457, 78.1642) is None


def test_no_key_means_no_calls(monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    called = []
    monkeypatch.setattr(gp, "search_place", lambda *a, **k: called.append(1))
    e = _place("X")
    stats = gp.fill_from_google([e], [DEST])
    assert not called and stats["filled"] == 0 and e.lat is None


def test_cap_limits_billable_calls_and_cache_is_reused(monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    calls = []

    def fake(name, dest, lat, lon, key):
        calls.append(name)
        return {"place_id": "p", "lat": 29.95, "lon": 78.17}

    monkeypatch.setattr(gp, "search_place", fake)
    es = [_place("A"), _place("B"), _place("C")]
    stats = gp.fill_from_google(es, [DEST], max_requests=2)
    assert stats["api_calls"] == 2 and stats["skipped_over_cap"] == 1 and stats["filled"] == 2
    assert es[0].coord_source == "google" and es[0].google_place_id == "p"

    # second run: the two fetched are served from cache, only C is fetched
    es2 = [_place("A"), _place("B"), _place("C")]
    stats2 = gp.fill_from_google(es2, [DEST], max_requests=2)
    assert stats2["cached"] == 2 and stats2["api_calls"] == 1 and len(calls) == 3


def test_expired_cache_is_refetched(monkeypatch, tmp_path):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    old = datetime.now(UTC) - timedelta(days=gp.CACHE_DAYS + 1)
    gp._cache_path("A", "Haridwar").write_text(
        json.dumps({"fetched_at": old.isoformat(), "match": {"place_id": "old", "lat": 1, "lon": 1}})
    )
    monkeypatch.setattr(gp, "search_place", lambda *a, **k: None)
    e = _place("A")
    stats = gp.fill_from_google([e], [DEST])
    assert stats["api_calls"] == 1 and e.lat is None


def test_auth_error_aborts_instead_of_hammering(monkeypatch):
    import httpx

    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    calls = []

    def forbidden(name, *a, **k):
        calls.append(name)
        req = httpx.Request("POST", gp.API)
        raise httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req))

    monkeypatch.setattr(gp, "search_place", forbidden)
    stats = gp.fill_from_google([_place("A"), _place("B"), _place("C")], [DEST])
    assert calls == ["A"] and stats["aborted"] == 403
