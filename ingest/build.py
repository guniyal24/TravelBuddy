"""Build the processed knowledge-graph dataset.

    python -m ingest.build [--only destination_haridwar ...] [--skip-elevation]

Output: data/processed/entities.json, data/processed/quality_report.md and
data/processed/getting_in_notes.json (raw "Get in" text kept for manual curation of
transport facts).
"""
import argparse
import json
import logging
from collections import Counter
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from ingest import wikivoyage
from ingest.elevation import fetch_elevations
from ingest.geo import haversine_km
from ingest.geocode import fill_missing_coordinates
from ingest.google_places import fill_from_google
from ingest.osm import fill_from_osm, normalize
from ingest.osm_places import places_from_osm
from ingest.schema import (
    Confidence,
    Connection,
    Entity,
    EntityType,
    Source,
    make_id,
)

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "processed"

NEAR_KM = 3.0  # straight-line radius for NEAR edges between places in one destination


# ---------- pure helpers (unit-tested) ----------
def add_near_edges(entities: list[Entity], radius_km: float = NEAR_KM) -> None:
    """Add symmetric NEAR edges (straight-line km) between located non-stay/eatery places
    and between each stay/eatery and the attractions around it, within one destination."""
    by_dest: dict[str, list[Entity]] = {}
    for e in entities:
        if e.lat is not None and e.lon is not None and e.destination_id and (
            e.type != EntityType.DESTINATION
        ):
            by_dest.setdefault(e.destination_id, []).append(e)
    for items in by_dest.values():
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                d = haversine_km(a.lat, a.lon, b.lat, b.lon)
                if d <= radius_km:
                    a.connections.append(Connection(relation="NEAR", target=b.id, distance_km=round(d, 2)))
                    b.connections.append(Connection(relation="NEAR", target=a.id, distance_km=round(d, 2)))


def add_membership_edges(entities: list[Entity]) -> None:
    for e in entities:
        if e.destination_id and e.type != EntityType.DESTINATION:
            e.connections.append(Connection(relation="IN_DESTINATION", target=e.destination_id))


def add_destination_links(destinations: list[Entity], max_km: float = 60.0) -> None:
    """Straight-line NEAR between nearby destinations. Road time comes later (Phase 3)."""
    for i, a in enumerate(destinations):
        for b in destinations[i + 1 :]:
            if None in (a.lat, a.lon, b.lat, b.lon):
                continue
            d = haversine_km(a.lat, a.lon, b.lat, b.lon)
            if d <= max_km:
                a.connections.append(Connection(relation="NEAR", target=b.id, distance_km=round(d, 1)))
                b.connections.append(Connection(relation="NEAR", target=a.id, distance_km=round(d, 1)))


def quality_report(entities: list[Entity]) -> str:
    total = len(entities)
    lines = ["# Data quality report", "", f"Generated {date.today()} - {total} entities", ""]
    by_type = Counter(e.type.value for e in entities)
    lines += ["## Entities by type", ""] + [f"- {t}: {n}" for t, n in sorted(by_type.items())] + [""]

    lines += ["## Per destination", ""]
    dests = sorted({e.destination_id for e in entities if e.destination_id})
    for d in dests:
        c = Counter(e.type.value for e in entities if e.destination_id == d)
        lines.append(f"- {d}: " + ", ".join(f"{t} {n}" for t, n in sorted(c.items())))
    lines.append("")

    placeable = [e for e in entities if e.type in (
        EntityType.ATTRACTION, EntityType.ACTIVITY, EntityType.EATERY, EntityType.STAY)]
    if placeable:
        no_coord = [e for e in placeable if e.lat is None]
        no_desc = [e for e in placeable if not e.description]
        bad_coord = [e for e in placeable if "coords_outside_uttarakhand" in e.tags]
        lines += [
            "## Completeness (places)", "",
            f"- Missing coordinates: {len(no_coord)}/{len(placeable)}",
            "- Coordinate sources: " + ", ".join(
                f"{k or 'none'} {v}"
                for k, v in sorted(Counter(e.coord_source for e in placeable).items())
            ),
            f"- Missing description: {len(no_desc)}/{len(placeable)}",
            f"- Coordinates outside Uttarakhand bounding box: {len(bad_coord)}",
            "",
        ]
        for e in bad_coord:
            lines.append(f"  - CHECK: {e.id} ({e.lat}, {e.lon})")
        stays = [e for e in entities if e.type == EntityType.STAY]
        if stays:
            tiers = Counter(e.tier.value if e.tier else "unknown" for e in stays)
            lines += ["", "## Stay tiers", ""] + [f"- {t}: {n}" for t, n in sorted(tiers.items())]
            priced = sum(1 for e in stays if e.price_text)
            lines.append(f"- With a price text: {priced}/{len(stays)}")
        lines.append("")

    conf = Counter(e.confidence.value for e in entities)
    lines += ["## Confidence", ""] + [f"- {k}: {v}" for k, v in sorted(conf.items())]
    lines += ["", "> Items marked `curated_unverified` must be checked against an official source",
              "> before release. NEAR distances are straight-line; road time is computed in Phase 3.", ""]
    return "\n".join(lines)


# ---------- pipeline ----------
def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def build_destination(cfg: dict, today: date) -> tuple[Entity, list[Entity], dict]:
    """Wikivoyage first (descriptions, prices, hours); towns with `osm_places: true` also get
    OpenStreetMap places. A town without a Wikivoyage page relies on OSM and its seed text."""
    page = cfg.get("wikivoyage_page")
    wt = ""
    if page:
        try:
            wt = wikivoyage.fetch_wikitext(page)
        except (KeyError, ValueError) as exc:
            log.warning("No Wikivoyage page %r for %s (%s)", page, cfg["name"], exc)
    description = (wikivoyage.extract_section(wt, "Understand")[:900] if wt else "") or \
        cfg.get("description", "")
    if wt:
        source = Source(name="Wikivoyage", url=wikivoyage.page_url(page),
                        license=wikivoyage.LICENSE, fetched_at=today)
    else:
        source = Source(name="OpenStreetMap", url=f"https://www.openstreetmap.org/#map=13/"
                        f"{cfg['lat']}/{cfg['lon']}", license="ODbL 1.0", fetched_at=today)
    dest = Entity(
        id=cfg["id"], type=EntityType.DESTINATION, name=cfg["name"], description=description,
        semantic_text=f"{cfg['name']}, Uttarakhand. {description}"[:700],
        lat=cfg.get("lat"), lon=cfg.get("lon"), region=cfg.get("region", ""),
        source=source, confidence=Confidence.SOURCED,
    )
    places = wikivoyage.parse_listings(
        wt, cfg["id"], cfg["name"], page, cfg.get("region", ""), today) if wt else []
    if cfg.get("osm_places"):
        known = {normalize(p.name) for p in places}
        extra = places_from_osm(cfg, today, known, radius_m=cfg.get("radius_m", 9000))
        log.info("  OSM added %d places", len(extra))
        places += extra
    notes = {"destination": cfg["id"], "source": dest.source.url,
             "get_in": wikivoyage.extract_section(wt, "Get in") if wt else "",
             "get_around": wikivoyage.extract_section(wt, "Get around") if wt else ""}
    return dest, places, notes


def curated_entities(destinations: list[Entity], today: date) -> list[Entity]:
    out: list[Entity] = []
    src = Source(name="Author curation (needs verification)", url="data/curated", fetched_at=today)
    dest_by_region: dict[str, list[Entity]] = {}
    for d in destinations:
        dest_by_region.setdefault(d.region, []).append(d)

    for item in load_yaml(DATA / "curated" / "dishes.yaml")["dishes"]:
        e = Entity(
            id=make_id(EntityType.DISH, "uttarakhand", item["name"]), type=EntityType.DISH,
            name=item["name"], description=item["description"],
            semantic_text=f"{item['name']}: {item['description']}",
            tags=["veg" if item.get("veg") else "non-veg"], region=",".join(item["regions"]),
            source=src, confidence=Confidence.CURATED_UNVERIFIED,
        )
        for region in item["regions"]:
            for d in dest_by_region.get(region, []):
                d.connections.append(Connection(relation="FAMOUS_FOR", target=e.id))
        out.append(e)

    known = {d.id for d in destinations}
    for g in load_yaml(DATA / "curated" / "gateways.yaml")["gateways"]:
        e = Entity(
            id=g["id"], type=EntityType.GATEWAY, name=g["name"],
            description=f"{g['mode']} gateway, code {g['code']}",
            semantic_text=f"{g['name']} ({g['code']}), {g['mode']} gateway to Uttarakhand",
            tags=[g["mode"], g["code"]], source=src, confidence=Confidence.CURATED_UNVERIFIED,
            connections=[Connection(relation="SERVES", target=t) for t in g["serves"] if t in known],
        )
        out.append(e)
    return out


def attach_elevations(entities: list[Entity]) -> None:
    located = [e for e in entities if e.lat is not None and e.lon is not None]
    elevations = fetch_elevations([(e.lat, e.lon) for e in located])
    for e, el in zip(located, elevations, strict=True):
        e.elevation_m = el


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="destination ids to ingest")
    ap.add_argument("--skip-elevation", action="store_true")
    ap.add_argument("--merge", action="store_true",
                    help="with --only: replace just those towns in the existing entities.json")
    ap.add_argument("--skip-geocode", action="store_true")
    ap.add_argument("--google", action="store_true",
                    help="also use Google Places (needs GOOGLE_PLACES_API_KEY; billable)")
    ap.add_argument("--google-max", type=int, default=100,
                    help="cap on billable Google API calls per run")
    args = ap.parse_args()
    load_dotenv()

    today = date.today()
    cfgs = load_yaml(DATA / "seeds" / "destinations.yaml")["destinations"]
    if args.only:
        cfgs = [c for c in cfgs if c["id"] in args.only]

    destinations: list[Entity] = []
    places: list[Entity] = []
    notes: list[dict] = []
    for cfg in cfgs:
        log.info("Ingesting %s", cfg["name"])
        d, p, n = build_destination(cfg, today)
        destinations.append(d)
        places += p
        notes.append(n)
        log.info("  %d listings", len(p))

    everything = destinations + places
    if not args.skip_geocode:
        stats = fill_from_osm(places, destinations)
        log.info("OSM matched %(filled)d of %(tried)d places without coordinates", stats)
        stats = fill_missing_coordinates(places, destinations)
        log.info("Nominatim found %(filled)d of %(tried)d remaining places", stats)
    if args.google:
        stats = fill_from_google(places, destinations, args.google_max)
        log.info("Google Places: %s", stats)
    if not args.skip_elevation:
        attach_elevations(everything)
    add_membership_edges(everything)
    add_near_edges(everything)
    add_destination_links(destinations)
    everything += curated_entities(destinations, today)

    OUT.mkdir(parents=True, exist_ok=True)
    if args.merge and (OUT / "entities.json").exists():
        rebuilt = {c["id"] for c in cfgs}
        old = json.loads((OUT / "entities.json").read_text())
        fresh = {e.id for e in everything}
        kept = [e for e in old if e["id"] not in fresh and e["id"] not in rebuilt
                and e.get("destination_id") not in rebuilt]
        log.info("Merge: keeping %d existing entities, adding %d", len(kept), len(everything))
        merged = kept + [e.model_dump(mode="json") for e in everything]
        (OUT / "entities.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False))
        log.info("Wrote %d entities to %s", len(merged), OUT)
        return
    (OUT / "entities.json").write_text(
        json.dumps([e.model_dump(mode="json") for e in everything], indent=2, ensure_ascii=False))
    (OUT / "getting_in_notes.json").write_text(json.dumps(notes, indent=2, ensure_ascii=False))
    (OUT / "quality_report.md").write_text(quality_report(everything))
    log.info("Wrote %d entities to %s", len(everything), OUT)


if __name__ == "__main__":
    main()
