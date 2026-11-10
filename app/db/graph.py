"""Neo4j access: users, interaction logs, feedback, graph context."""
import logging
from typing import Any

from neo4j import GraphDatabase

log = logging.getLogger(__name__)


class GraphStore:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(uri, auth=(user, password), database=database)
        self.driver.verify_connectivity()

    def close(self) -> None:
        self.driver.close()

    # --- users ---
    def create_user(self, email: str, password_hash: str) -> None:
        cypher = """
        MERGE (u:User {email: $email})
        ON CREATE SET u.password_hash = $ph, u.created_at = datetime()
        """
        with self.driver.session() as s:
            s.run(cypher, email=email, ph=password_hash)

    def get_user(self, email: str) -> dict[str, Any] | None:
        cypher = (
            "MATCH (u:User {email: $email}) "
            "RETURN u.email AS email, u.password_hash AS password_hash"
        )
        with self.driver.session() as s:
            rec = s.run(cypher, email=email).single()
            return rec.data() if rec else None

    # --- retrieval ---
    def fetch_graph_context(self, node_ids: list[str], limit: int = 25) -> list[dict[str, Any]]:
        if not node_ids:
            return []
        cypher = """
        UNWIND $node_ids AS nid
        MATCH (n:Entity {id: nid})-[r]-(m:Entity)
        RETURN nid AS source_id, type(r) AS rel, m.id AS target_id, m.name AS name,
               COALESCE(left(m.description, 200), "") AS desc, r.distance_km AS km
        ORDER BY r.distance_km
        LIMIT $limit
        """
        with self.driver.session() as s:
            return [r.data() for r in s.run(cypher, node_ids=node_ids, limit=limit)]

    def fetch_entities(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Full property maps for entity ids (description, price, hours, tier, ...)."""
        if not ids:
            return {}
        with self.driver.session() as s:
            rows = s.run("UNWIND $ids AS i MATCH (n:Entity {id: i}) RETURN n", ids=ids)
            return {r["n"]["id"]: dict(r["n"]) for r in rows}

    # --- logs / feedback ---
    def log_interaction(
        self, session_id: str, query: str, response: str, retrieved_ids: list[str]
    ) -> None:
        cypher = """
        MERGE (s:Session {id: $sid})
        CREATE (l:Log {id: randomUUID(), query: $q, response: $r, timestamp: datetime()})
        CREATE (s)-[:HAS_LOG]->(l)
        WITH l UNWIND $ids AS nid
        MATCH (e:Entity {id: nid}) MERGE (l)-[:USED_CONTEXT]->(e)
        """
        try:
            with self.driver.session() as s:
                s.run(cypher, sid=session_id, q=query, r=response, ids=retrieved_ids)
        except Exception:
            log.exception("Failed to log interaction")

    def save_feedback(self, session_id: str, query: str, rating: int, comment: str | None) -> None:
        cypher = """
        MATCH (s:Session {id: $sid})-[:HAS_LOG]->(l:Log {query: $q})
        SET l.rating = $r, l.comment = $c
        """
        try:
            with self.driver.session() as s:
                s.run(cypher, sid=session_id, q=query, r=rating, c=comment)
        except Exception:
            log.exception("Failed to save feedback")
