"""Read-only travel listings used when the live Neo4j graph cannot start."""
import json
from collections import defaultdict
from pathlib import Path

from app.db.graph import AccountStoreUnavailable

SNAPSHOT_PATH = Path(__file__).resolve().parents[2] / "data" / "snapshot" / "places.json"


class SnapshotGraph:
    """The same listing and relationship lookups as Neo4j, backed by bundled open data."""

    def __init__(self, path: Path = SNAPSHOT_PATH):
        data = json.loads(path.read_text())
        self.entities = {e["id"]: e for e in data["entities"]}
        if not self.entities:
            raise ValueError("The travel snapshot is empty")
        self.edges = defaultdict(list)
        for source, target, rel, km in data["edges"]:
            self.edges[source].append((target, rel, km))
            self.edges[target].append((source, rel, km))

    def fetch_entities(self, ids: list[str]) -> dict:
        return {i: self.entities[i].copy() for i in ids if i in self.entities}

    def fetch_graph_context(self, node_ids: list[str], limit: int = 25) -> list[dict]:
        facts = []
        for source in node_ids:
            for target, rel, km in self.edges.get(source, ()):
                node = self.entities[target]
                facts.append({"source_id": source, "rel": rel, "target_id": target,
                              "name": node["name"], "desc": node.get("description", "")[:200],
                              "km": km, "source_url": node.get("source_url")})
        return sorted(facts, key=lambda fact: (fact["km"] is None, fact["km"] or 0))[:limit]

    def get_user(self, email: str) -> dict:
        raise AccountStoreUnavailable

    def save_feedback(self, *args) -> None:
        # No writable chat log in snapshot mode.
        return None

    def close(self) -> None:
        return None  # nothing to release (same interface as GraphStore)

    def readiness(self) -> dict:
        return {"mode": "snapshot", "entities": len(self.entities), "accounts_available": False}
