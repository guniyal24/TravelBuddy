from ingest.load import node_props, pinecone_record, relationships

ENTITIES = [
    {"id": "destination_haridwar", "type": "Destination", "name": "Haridwar", "lat": 29.9,
     "lon": 78.1, "elevation_m": None, "tags": [], "semantic_text": "Haridwar text",
     "source": {"name": "Wikivoyage", "url": "u", "license": "CC BY-SA 4.0"},
     "connections": [{"relation": "NEAR", "target": "destination_rishikesh", "distance_km": 20.1},
                     {"relation": "BAD-REL", "target": "destination_rishikesh"},
                     {"relation": "NEAR", "target": "ghost_id"}]},
    {"id": "destination_rishikesh", "type": "Destination", "name": "Rishikesh", "tags": [],
     "source": {"name": "Wikivoyage", "url": "u"}, "connections": []},
    {"id": "stay_haridwar_x", "type": "Stay", "name": "Hotel X", "destination_id":
     "destination_haridwar", "tier": "budget", "tags": ["sleep"], "semantic_text": "s" * 900,
     "source": {"name": "Wikivoyage", "url": "u"}, "connections": []},
]


def test_node_props_drops_none_and_flattens_source():
    p = node_props(ENTITIES[0])
    assert "elevation_m" not in p and p["source_name"] == "Wikivoyage"
    assert p["lat"] == 29.9 and isinstance(p["tags"], list)


def test_relationships_filters_invalid_and_unknown_targets():
    r = relationships(ENTITIES)
    assert list(r) == ["NEAR"]
    assert r["NEAR"] == [{"src": "destination_haridwar", "dst": "destination_rishikesh", "km": 20.1}]


def test_pinecone_record_has_no_coordinates_and_truncates_text():
    rec = pinecone_record(ENTITIES[2])
    meta = rec["metadata"]
    assert "lat" not in meta and "lon" not in meta
    assert len(meta["semantic_text"]) == 500 and meta["city"] == "Haridwar"
    assert meta["tier"] == "budget"
    assert pinecone_record(ENTITIES[0])["metadata"]["city"] == "Haridwar"
