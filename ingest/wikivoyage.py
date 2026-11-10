"""Fetch and parse Wikivoyage city pages (CC BY-SA 4.0).

Wikivoyage stores places as structured listing templates ({{see}}, {{do}}, {{eat}},
{{drink}}, {{sleep}}) with name, coordinates, hours, price and a description, which
makes it a good first source. Sleep listings sit under Budget / Mid-range / Splurge
headings, which we map to price tiers.
"""
from datetime import date

import mwparserfromhell as mwp

from ingest.http import get_json
from ingest.schema import (
    Confidence,
    Entity,
    EntityType,
    Source,
    Tier,
    in_uttarakhand,
    is_generic_name,
    make_id,
)

API = "https://en.wikivoyage.org/w/api.php"
LICENSE = "CC BY-SA 4.0"

LISTING_TYPES = {
    "see": EntityType.ATTRACTION,
    "do": EntityType.ACTIVITY,
    "eat": EntityType.EATERY,
    "drink": EntityType.EATERY,
    "sleep": EntityType.STAY,
}
TIER_HEADINGS = {"budget": Tier.BUDGET, "mid-range": Tier.MID, "splurge": Tier.PREMIUM}


def fetch_wikitext(page: str) -> str:
    data = get_json(
        API,
        {"action": "parse", "page": page, "prop": "wikitext", "format": "json",
         "formatversion": 2, "redirects": 1},
    )
    return data["parse"]["wikitext"]


def page_url(page: str) -> str:
    return f"https://en.wikivoyage.org/wiki/{page.replace(' ', '_')}"


def _clean(value) -> str:
    return " ".join(value.strip_code().split()) if value is not None else ""


def _to_float(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_listings(
    wikitext: str, destination_id: str, destination_name: str, page: str, region: str = "",
    fetched: date | None = None,
) -> list[Entity]:
    """Turn the listing templates on a Wikivoyage page into Entity objects."""
    fetched = fetched or date.today()
    source = Source(name="Wikivoyage", url=page_url(page), license=LICENSE, fetched_at=fetched)
    code = mwp.parse(wikitext)

    entities: list[Entity] = []
    seen: set[str] = set()
    tier: Tier | None = None

    for node in code.nodes:
        if isinstance(node, mwp.nodes.Heading):
            title = str(node.title).strip().lower()
            if title in TIER_HEADINGS:
                tier = TIER_HEADINGS[title]
            elif node.level <= 2:  # a new top-level section resets the tier
                tier = None
            continue
        if not isinstance(node, mwp.nodes.Template):
            continue
        tname = str(node.name).strip().lower()
        if tname not in LISTING_TYPES:
            continue

        def param(key: str, _node=node) -> str:
            return _clean(_node.get(key).value) if _node.has(key) else ""

        name = param("name")
        if not name or is_generic_name(name):  # "Temples nearby" is a heading, not a place
            continue
        etype = LISTING_TYPES[tname]
        eid = make_id(etype, destination_name, name)
        if eid in seen:
            continue
        seen.add(eid)

        lat, lon = _to_float(param("lat")), _to_float(param("long"))
        tags = [tname] + (["drink"] if tname == "drink" else [])
        if lat is not None and lon is not None and not in_uttarakhand(lat, lon):
            tags.append("coords_outside_uttarakhand")  # flagged in the quality report

        description = param("content")
        entities.append(
            Entity(
                id=eid,
                type=etype,
                name=name,
                destination_id=destination_id,
                description=description,
                semantic_text=f"{name} in {destination_name}: {description}".strip(": "),
                lat=lat,
                lon=lon,
                coord_source="wikivoyage" if lat is not None and lon is not None else "",
                tags=tags,
                tier=tier if etype == EntityType.STAY else None,
                price_text=param("price"),
                hours=param("hours"),
                address=param("address"),
                phone=param("phone"),
                url=param("url"),
                region=region,
                source=source,
                confidence=Confidence.SOURCED,
            )
        )
    return entities


def extract_section(wikitext: str, heading: str) -> str:
    """Plain text of one top-level section (e.g. 'Understand'); empty if missing."""
    code = mwp.parse(wikitext)
    for section in code.get_sections(levels=[2], matches=lambda h: str(h).strip() == heading,
                                     include_headings=False):
        return " ".join(section.strip_code().split())
    return ""
