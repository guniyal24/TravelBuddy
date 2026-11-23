from neo4j.exceptions import AuthError

from app.api import main
from app.api.deps_health import build_checks
from ingest.snapshot import write_snapshot


def test_unavailable_neo4j_uses_sourced_read_only_snapshot(monkeypatch, settings, client):
    def unavailable(*args):
        raise AuthError("wrong database credentials")

    monkeypatch.setattr(main, "GraphStore", unavailable)
    store = main.open_graph(settings)
    graph_health = build_checks(type("Planner", (), {"store": store})(), None)["graph"]()
    assert graph_health["mode"] == "snapshot" and graph_health["entities"] > 700
    assert store.fetch_entities(["destination_haridwar"])["destination_haridwar"]["source_url"]
    facts = store.fetch_graph_context(["destination_haridwar"], limit=2)
    assert len(facts) == 2 and all(f["source_url"] for f in facts)
    client.app.state.store = store

    guest = client.post("/api/guest")
    assert guest.status_code == 200
    headers = {"Authorization": f"Bearer {guest.json()['access_token']}"}
    assert client.get("/api/trips", headers=headers).status_code == 200
    response = client.post("/api/token", data={"username": "a@b.com", "password": "pass1234"})
    assert response.status_code == 503 and "plan as a guest" in response.json()["detail"]


def test_snapshot_excludes_google_coordinates_and_derived_distances(tmp_path):
    output = tmp_path / "snapshot.json"
    write_snapshot([
        {"id": "a", "name": "A", "type": "Stay", "coord_source": "google", "lat": 30.1,
         "lon": 78.1, "elevation_m": 123, "google_place_id": "g", "connections": [
             {"target": "b", "relation": "NEAR", "distance_km": 2.3}]},
        {"id": "b", "name": "B", "type": "Destination", "coord_source": "osm",
         "lat": 30.2, "lon": 78.2},
    ], output)
    store = main.SnapshotGraph(output)
    a, b = store.fetch_entities(["a", "b"]).values()
    assert {"lat", "lon", "elevation_m", "google_place_id"}.isdisjoint(a)
    assert b["lat"] == 30.2
    assert store.fetch_graph_context(["a", "b"]) == []
