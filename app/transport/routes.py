"""Curated road links with approximate distance, duration and fares.

Distances and durations come from data/curated/transport.yaml (curated_unverified).
Fares are NOT stored: they are computed from the per-km assumptions below and labelled
'assumption'. Departure times are never invented; the caller is pointed to the operator.
"""
from functools import lru_cache
from pathlib import Path

import yaml

FILE = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "transport.yaml"

# INR per km. Placeholder rates: bus is per person, taxi is per vehicle (up to 4 passengers).
BUS_PER_KM = (1.5, 3.0)
TAXI_PER_KM = (12.0, 18.0)
TAXI_SEATS = 4
MIN_TAXI = 500


@lru_cache(maxsize=1)
def _load() -> dict:
    return yaml.safe_load(FILE.read_text())


def _round(value: float, step: int) -> int:
    return int(round(value / step) * step)


def find_route(a: str, b: str) -> dict | None:
    for r in _load()["routes"]:
        if {r["a"], r["b"]} == {a, b}:
            return r
    return None


def fares(km: float, people: int = 1) -> dict:
    bus = (_round(km * BUS_PER_KM[0], 10), _round(km * BUS_PER_KM[1], 10))
    taxi = (max(MIN_TAXI, _round(km * TAXI_PER_KM[0], 100)),
            max(MIN_TAXI, _round(km * TAXI_PER_KM[1], 100)))
    seats = max(1, min(people, TAXI_SEATS))
    return {"bus_per_person_inr": list(bus), "taxi_per_vehicle_inr": list(taxi),
            "taxi_per_person_inr": [round(taxi[0] / seats), round(taxi[1] / seats)],
            "source": "assumption"}


def transport_options(origin: str, destination: str, people: int = 1) -> dict:
    """Road options between two ids (a destination id or a city id such as city_delhi)."""
    data = _load()
    origin = origin.strip().lower()
    if not origin.startswith(("city_", "destination_")):
        origin = "city_" + origin.replace(" ", "_")
    route = find_route(origin, destination)
    if route is None:
        return {"found": False, "origin": origin, "destination": destination,
                "message": "No curated route for this pair. Check the operator or a maps app.",
                "confidence": data["confidence"]}
    lo, hi = route["hours"]
    out = {"found": True, "origin": origin, "destination": destination,
           "distance_km": route["km"], "hours": [lo, hi], "fares": fares(route["km"], people),
           "confidence": data["confidence"],
           "departure_times": "Not stored. Check the operator for current timings.",
           "verify_bus": data["sources"]["bus"], "note": route.get("note", "")}
    if route.get("rail"):
        out["rail_station"] = route["rail"]
        out["verify_rail"] = data["sources"]["rail"]
    return out
