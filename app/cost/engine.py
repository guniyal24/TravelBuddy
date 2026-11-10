"""Deterministic trip cost estimator. No LLM: the same input always gives the same output.

Every line item carries a `source` so the UI can say where a number came from:
  "listing"     parsed from a sourced listing price
  "comparable"  range taken from priced listings of the same type in the same destination
  "assumption"  a placeholder per-tier rate from ASSUMPTIONS (curated_unverified)
  "user"        supplied by the user or by a fare tool

Ranges (low, high) are returned instead of a single number because hill-trip prices vary
by season and negotiation. The buffer covers extras the model does not capture.
"""
from dataclasses import dataclass, field
from math import ceil

from app.cost.pricing import parse_price_range

# Placeholder INR rates. NOT sourced: replace with verified data as it is collected.
ASSUMPTIONS = {
    "stay_per_room_night": {"budget": (800, 1800), "mid": (2000, 4500), "premium": (6000, 14000)},
    "food_per_person_day": {"budget": (350, 600), "mid": (700, 1200), "premium": (1500, 3000)},
    "local_transport_per_day": {"budget": (150, 400), "mid": (600, 1500), "premium": (2000, 4500)},
}
BUFFER = (0.10, 0.15)
GUESTS_PER_ROOM = 2


@dataclass
class StayChoice:
    nights: int
    tier: str = "budget"
    price_text: str = ""  # listing price, if the user picked a specific stay
    name: str = ""
    comparable_range: tuple[float, float] | None = None  # from similar listings, same place
    comparable_note: str = ""


@dataclass
class TransportLeg:
    description: str
    fare_per_person: tuple[float, float]  # (low, high)
    people_override: int | None = None
    source: str = "user"


@dataclass
class TripInput:
    people: int
    days: int
    tier: str = "budget"
    stays: list[StayChoice] = field(default_factory=list)
    legs: list[TransportLeg] = field(default_factory=list)
    entry_fees_per_person: float = 0.0
    permits_total: float = 0.0


@dataclass
class LineItem:
    label: str
    low: float
    high: float
    source: str
    note: str = ""


@dataclass
class CostEstimate:
    items: list[LineItem]
    subtotal: tuple[float, float]
    total: tuple[float, float]
    per_person: tuple[float, float]


def rooms_needed(people: int) -> int:
    return max(1, ceil(people / GUESTS_PER_ROOM))


def _stay_nightly(stay: StayChoice) -> tuple[tuple[float, float], str]:
    parsed = parse_price_range(stay.price_text)
    if parsed:
        return parsed, "listing"
    if stay.comparable_range:
        return stay.comparable_range, "comparable"
    return ASSUMPTIONS["stay_per_room_night"][stay.tier], "assumption"


def _stay_note(stay: StayChoice, src: str) -> str:
    if src == "listing":
        return ""
    if src == "comparable":
        return stay.comparable_note or "from similar listings nearby"
    return "tier-average placeholder rate"


def estimate(trip: TripInput) -> CostEstimate:
    if trip.people < 1 or trip.days < 1:
        raise ValueError("people and days must be >= 1")
    for key in (trip.tier, *[s.tier for s in trip.stays]):
        if key not in ASSUMPTIONS["food_per_person_day"]:
            raise ValueError(f"unknown tier: {key!r}")

    items: list[LineItem] = []
    rooms = rooms_needed(trip.people)

    for stay in trip.stays:
        (lo, hi), src = _stay_nightly(stay)
        label = f"Stay: {stay.name or stay.tier} x {stay.nights} night(s) x {rooms} room(s)"
        items.append(LineItem(label, lo * stay.nights * rooms, hi * stay.nights * rooms, src,
                              _stay_note(stay, src)))

    flo, fhi = ASSUMPTIONS["food_per_person_day"][trip.tier]
    items.append(LineItem(f"Food: {trip.people} person(s) x {trip.days} day(s)",
                          flo * trip.people * trip.days, fhi * trip.people * trip.days,
                          "assumption", "tier-average placeholder rate"))

    tlo, thi = ASSUMPTIONS["local_transport_per_day"][trip.tier]
    items.append(LineItem(f"Local transport: {trip.days} day(s)", tlo * trip.days,
                          thi * trip.days, "assumption", "autos / shared taxis"))

    for leg in trip.legs:
        n = leg.people_override or trip.people
        items.append(LineItem(f"Travel: {leg.description} x {n}", leg.fare_per_person[0] * n,
                              leg.fare_per_person[1] * n, leg.source))

    if trip.entry_fees_per_person:
        fee = trip.entry_fees_per_person * trip.people
        items.append(LineItem("Entry fees", fee, fee, "user"))
    if trip.permits_total:
        items.append(LineItem("Permits / registration", trip.permits_total, trip.permits_total,
                              "user"))

    sub_lo = sum(i.low for i in items)
    sub_hi = sum(i.high for i in items)
    total = (round(sub_lo * (1 + BUFFER[0])), round(sub_hi * (1 + BUFFER[1])))
    return CostEstimate(
        items=items, subtotal=(round(sub_lo), round(sub_hi)), total=total,
        per_person=(round(total[0] / trip.people), round(total[1] / trip.people)))
