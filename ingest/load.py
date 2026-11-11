"""Load data/processed/entities.json into Neo4j and Pinecone.

    python -m ingest.load neo4j      [--dry-run] [--wipe] [--only destination_almora ...]
    python -m ingest.load pinecone   [--dry-run]          [--only destination_almora ...]

`--only` loads just those towns (after `ingest.build --only ... --merge`) and removes their
places that are no longer in entities.json from the store.

Neo4j gets every entity as (:Entity:<Type>) plus typed relationships.
Pinecone gets one vector per entity (embedding of `semantic_text`) with small metadata.
Google-sourced coordinates are NOT copied to Pinecone (a third-party store); they stay in
Neo4j only, where the app reads them. Re-run `ingest.build --google` at least every 30 days.
"""
import argparse
import json
import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)
PROCESSED = Path(__file__).resolve().parent.parent / "data" / "processed" / "entities.json"
REL_RE = re.compile(r"^[A-Z][A-Z_]*$")  # relationship types are interpolated into Cypher
BATCH = 100


def load_entities(path: Path = PROCESSED) -> list[dict]:
    return json.loads(path.read_text())


# ---------- pure helpers (unit-tested) ----------
def node_props(e: dict) -> dict:
    """Flat, Neo4j-safe property map (no nested objects, no None values)."""
    src = e.get("source") or {}
    props = {
        "id": e["id"], "name": e["name"], "type": e["type"],
        "destination_id": e.get("destination_id"),
        "description": e.get("description", ""),
        "semantic_text": e.get("semantic_text", ""),
        "lat": e.get("lat"), "lon": e.get("lon"), "elevation_m": e.get("elevation_m"),
        "coord_source": e.get("coord_source", ""),
        "google_place_id": e.get("google_place_id", ""),
        "tier": e.get("tier"), "price_text": e.get("price_text", ""),
        "hours": e.get("hours", ""), "address": e.get("address", ""),
        "phone": e.get("phone", ""), "url": e.get("url", ""),
        "region": e.get("region", ""), "tags": e.get("tags", []),
        "confidence": e.get("confidence"),
        "source_name": src.get("name", ""), "source_url": src.get("url", ""),
        "source_license": src.get("license", ""),
        "last_verified": e.get("last_verified"),
    }
    return {k: v for k, v in props.items() if v is not None}


def relationships(entities: list[dict], known: set[str] | None = None) -> dict[str, list[dict]]:
    """Group edges by relationship type. Edges to unknown ids are dropped; `known` is every id
    in the store when only some entities are being loaded."""
    ids = known if known is not None else {e["id"] for e in entities}
    grouped: dict[str, list[dict]] = {}
    for e in entities:
        for c in e.get("connections", []):
            rel = c["relation"]
            if not REL_RE.match(rel) or c["target"] not in ids:
                continue
            grouped.setdefault(rel, []).append(
                {"src": e["id"], "dst": c["target"], "km": c.get("distance_km")})
    return grouped


def select_towns(entities: list[dict], towns: list[str]) -> list[dict]:
    """The towns themselves and every place in them."""
    wanted = set(towns)
    return [e for e in entities if e["id"] in wanted or e.get("destination_id") in wanted]


def place_prefixes(towns: list[str]) -> list[str]:
    """Id prefixes of a town's places (ids are <type>_<town>_<name>, see schema.make_id)."""
    return [f"{t}_{town.removeprefix('destination_')}_" for town in towns
            for t in ("attraction", "activity", "eatery", "stay")]


def pinecone_record(e: dict) -> dict:
    """Metadata only; the hybrid retriever reads name/type/city/semantic_text."""
    dest = (e.get("destination_id") or "").removeprefix("destination_").replace("_", " ").title()
    meta = {
        "name": e["name"], "type": e["type"],
        "city": e["name"] if e["type"] == "Destination" else dest,
        "semantic_text": (e.get("semantic_text") or "")[:500],
        "confidence": e.get("confidence") or "",
    }
    if e.get("tier"):
        meta["tier"] = e["tier"]
    return {"id": e["id"], "text": e.get("semantic_text") or e["name"], "metadata": meta}


# ---------- Neo4j ----------
def _chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def load_neo4j(entities: list[dict], wipe: bool = False, known: set[str] | None = None,
               towns: list[str] | None = None) -> dict:
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    user = os.getenv("NEO4J_USER") or os.environ["NEO4J_USERNAME"]
    db = os.getenv("NEO4J_DATABASE", "neo4j")
    driver = GraphDatabase.driver(uri, auth=(user, os.environ["NEO4J_PASSWORD"]), database=db)
    driver.verify_connectivity()
    rels = relationships(entities, known)
    removed = 0
    with driver.session() as s:
        s.run("CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE")
        if wipe:
            s.run("MATCH (n:Entity) DETACH DELETE n")
        if towns:  # places dropped from these towns since the last load
            removed = s.run(
                "MATCH (n:Entity) WHERE n.destination_id IN $towns AND NOT n.id IN $keep "
                "DETACH DELETE n RETURN count(*) AS n",
                towns=towns, keep=[e["id"] for e in entities]).single()["n"]
        by_type: dict[str, list[dict]] = {}
        for e in entities:
            by_type.setdefault(e["type"], []).append(node_props(e))
        for etype, rows in by_type.items():
            label = re.sub(r"[^A-Za-z]", "", etype)  # e.g. Destination, Stay
            for chunk in _chunks(rows, 200):
                s.run(
                    f"UNWIND $rows AS r MERGE (n:Entity {{id: r.id}}) SET n:{label}, n += r",
                    rows=chunk)
        for rel, rows in rels.items():
            for chunk in _chunks(rows, 500):
                s.run(
                    "UNWIND $rows AS r MATCH (a:Entity {id: r.src}) MATCH (b:Entity {id: r.dst}) "
                    f"MERGE (a)-[x:{rel}]->(b) SET x.distance_km = r.km",
                    rows=chunk)
        counts = s.run("MATCH (n:Entity) RETURN count(n) AS n").single()["n"]
        edges = s.run("MATCH (:Entity)-[r]->(:Entity) RETURN count(r) AS n").single()["n"]
    driver.close()
    return {"nodes": counts, "relationships": edges, "removed": removed}


# ---------- Pinecone ----------
def load_pinecone(entities: list[dict], towns: list[str] | None = None) -> dict:
    from openai import OpenAI
    from pinecone import Pinecone

    name = os.environ["PINECONE_INDEX_NAME"]
    dim = int(os.getenv("PINECONE_VECTOR_DIM", "1024"))
    model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    if name not in pc.list_indexes().names():
        pc.create_index(name=name, dimension=dim, metric="cosine",
                        spec={"serverless": {"cloud": "aws", "region": "us-east-1"}})
    index = pc.Index(name)
    client = OpenAI(
        api_key=os.getenv("DEEPINFRA_API_KEY") or os.environ["OPENAI_API_KEY"],
        base_url=os.getenv("EMBED_BASE_URL", "https://api.deepinfra.com/v1/openai"),
    )

    records = [pinecone_record(e) for e in entities]
    for chunk in _chunks(records, BATCH):
        resp = client.embeddings.create(
            model=model, input=[r["text"] for r in chunk], encoding_format="float")
        if len(resp.data[0].embedding) != dim:
            raise ValueError(
                f"Embedding size {len(resp.data[0].embedding)} != PINECONE_VECTOR_DIM {dim}")
        index.upsert(vectors=[
            {"id": r["id"], "values": d.embedding, "metadata": r["metadata"]}
            for r, d in zip(chunk, resp.data, strict=True)])
    stale: list[str] = []
    if towns:  # places dropped from these towns since the last load
        keep = {r["id"] for r in records}
        for prefix in place_prefixes(towns):
            for page in index.list(prefix=prefix):
                ids = [getattr(i, "id", i) for i in page]  # ListItem objects in newer clients
                stale += [i for i in ids if i not in keep]
        for chunk in _chunks(stale, BATCH):
            index.delete(ids=chunk)
    return {"vectors_upserted": len(records), "removed": stale, "index": name}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=["neo4j", "pinecone"])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wipe", action="store_true", help="neo4j: delete existing :Entity nodes first")
    ap.add_argument("--only", nargs="*", help="destination ids: load just these towns")
    args = ap.parse_args()
    if args.only and args.wipe:
        ap.error("--wipe would delete every other town; use it only for a full load")

    everything = load_entities()
    known = {e["id"] for e in everything}
    entities = select_towns(everything, args.only) if args.only else everything
    if args.only and not entities:
        ap.error(f"no entities for {args.only}")
    if args.dry_run:
        rels = relationships(entities, known)
        print(f"{len(entities)} entities; relationships: "
              + ", ".join(f"{k}={len(v)}" for k, v in sorted(rels.items())))
        return
    result = (load_neo4j(entities, args.wipe, known, args.only) if args.target == "neo4j"
              else load_pinecone(entities, args.only))
    print(result)


if __name__ == "__main__":
    main()
