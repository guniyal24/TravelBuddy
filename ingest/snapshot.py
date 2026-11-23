"""Export the open-data travel graph that ships with the API image.

Regenerate after updating the live index with `python -m ingest.snapshot`.
"""
import json
from pathlib import Path

from app.db.snapshot import SNAPSHOT_PATH
from ingest.load import load_entities, node_props, relationships

FIELDS = {
    "id", "name", "type", "destination_id", "description", "semantic_text", "lat", "lon",
    "elevation_m", "tier", "price_text", "hours", "address", "region", "tags", "confidence",
    "source_name", "source_url", "source_license", "last_verified",
}
LOCATION_FIELDS = {"lat", "lon", "elevation_m"}


def write_snapshot(entities: list[dict], path: Path) -> None:
    rows = []
    restricted_locations = {e["id"] for e in entities if e.get("coord_source") == "google"}
    for entity in entities:
        fields = FIELDS - LOCATION_FIELDS if entity["id"] in restricted_locations else FIELDS
        rows.append({k: v for k, v in node_props(entity).items() if k in fields and v != ""})
    edges = [
        [e["src"], e["dst"], rel, e["km"]]
        for rel, group in relationships(entities).items() for e in group
        if rel != "NEAR" or not restricted_locations.intersection((e["src"], e["dst"]))
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    nodes_json = ",\n    ".join(json.dumps(row, ensure_ascii=False) for row in rows)
    edges_json = ",\n    ".join(json.dumps(edge, ensure_ascii=False) for edge in edges)
    path.write_text(
        '{\n  "entities": [\n    ' + nodes_json + '\n  ],\n  "edges": [\n    ' + edges_json + '\n  ]\n}\n',
        encoding="utf-8",
    )


if __name__ == "__main__":
    write_snapshot(load_entities(), SNAPSHOT_PATH)
