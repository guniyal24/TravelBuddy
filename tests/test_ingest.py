from datetime import date

from ingest import wikivoyage
from ingest.build import (
    add_destination_links,
    add_membership_edges,
    add_near_edges,
    quality_report,
)
from ingest.geo import haversine_km
from ingest.schema import Confidence, Entity, EntityType, Source, Tier, in_uttarakhand, make_id

WIKITEXT = """
== Understand ==
Rishikesh is a small town on the Ganges, known as the yoga capital.

== See ==
* {{see | name=Laxman Jhula | lat=30.1263 | long=78.3294 | content=Iron suspension bridge.}}
* {{see | name=Ram Jhula | lat=30.1190 | long=78.3100 | content=Another bridge.}}
* {{see | name=Far Away Place | lat=12.0 | long=77.0 | content=Wrong coordinates.}}
* {{see | name= | content=No name, should be skipped}}

== Eat ==
* {{eat | name=Cafe One | lat=30.1260 | long=78.3290 | price=Rs 200-400 | content=Pancakes.}}

== Sleep ==
=== Budget ===
* {{sleep | name=Backpacker Hostel | lat=30.1250 | long=78.3280 | price=Rs 500}}
=== Splurge ===
* {{sleep | name=Ganga Resort | lat=30.1000 | long=78.3000 | price=Rs 15000}}

== Go next ==
Haridwar is nearby.
"""

SRC = Source(name="t", url="u")


def _parse():
    return wikivoyage.parse_listings(
        WIKITEXT, "destination_rishikesh", "Rishikesh", "Rishikesh", "Garhwal", date(2026, 1, 1)
    )


def test_parse_types_and_names():
    es = _parse()
    by_name = {e.name: e for e in es}
    assert "Laxman Jhula" in by_name and "Cafe One" in by_name
    assert by_name["Laxman Jhula"].type == EntityType.ATTRACTION
    assert by_name["Cafe One"].type == EntityType.EATERY
    assert all(e.name for e in es)  # nameless listing skipped


def test_stay_tiers_from_headings():
    by_name = {e.name: e for e in _parse()}
    assert by_name["Backpacker Hostel"].tier == Tier.BUDGET
    assert by_name["Ganga Resort"].tier == Tier.PREMIUM
    assert by_name["Laxman Jhula"].tier is None


def test_price_coords_and_provenance():
    by_name = {e.name: e for e in _parse()}
    cafe = by_name["Cafe One"]
    assert cafe.price_text == "Rs 200-400"
    assert (cafe.lat, cafe.lon) == (30.1260, 78.3290)
    assert cafe.source.license == "CC BY-SA 4.0"
    assert cafe.confidence == Confidence.SOURCED


def test_out_of_bbox_flagged():
    by_name = {e.name: e for e in _parse()}
    assert "coords_outside_uttarakhand" in by_name["Far Away Place"].tags
    assert not in_uttarakhand(12.0, 77.0) and in_uttarakhand(30.1, 78.3)


def test_extract_section():
    assert "yoga capital" in wikivoyage.extract_section(WIKITEXT, "Understand")
    assert wikivoyage.extract_section(WIKITEXT, "Nope") == ""


def test_ids_are_stable():
    assert make_id(EntityType.STAY, "Rishikesh", "Ganga Resort!") == "stay_rishikesh_ganga_resort"


def test_haversine_known_distance():
    # Haridwar -> Rishikesh is roughly 20-25 km in a straight line
    d = haversine_km(29.9457, 78.1642, 30.0869, 78.2676)
    assert 18 < d < 25


def test_edges_and_report():
    es = _parse()
    dest = Entity(
        id="destination_rishikesh", type=EntityType.DESTINATION, name="Rishikesh",
        lat=30.0869, lon=78.2676, source=SRC,
    )
    other = Entity(
        id="destination_haridwar", type=EntityType.DESTINATION, name="Haridwar",
        lat=29.9457, lon=78.1642, source=SRC,
    )
    allx = [dest, *es]
    add_membership_edges(allx)
    add_near_edges(allx, radius_km=3.0)
    add_destination_links([dest, other])

    laxman = next(e for e in es if e.name == "Laxman Jhula")
    rels = {c.relation for c in laxman.connections}
    assert {"IN_DESTINATION", "NEAR"} <= rels
    near_ids = {c.target for c in laxman.connections if c.relation == "NEAR"}
    assert next(e for e in es if e.name == "Ram Jhula").id in near_ids
    assert any(c.target == "destination_haridwar" for c in dest.connections)

    report = quality_report([dest, other, *es])
    assert "Entities by type" in report and "CHECK:" in report  # bad coords surfaced
