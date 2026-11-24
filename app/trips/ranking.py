"""Personalize circuit order using explicit traveller feedback and road estimates."""
from itertools import groupby
from typing import Literal

from app.transport.routes import transport_options

RankingPriority = Literal["shorter_transfers", "lower_transfer_cost"]
METRICS = {"shorter_transfers": "hours", "lower_transfer_cost": "bus_per_person_inr"}
MAX_BONUS = 4


def transfer_estimate(towns: list[str]) -> dict | None:
    """Total ranges between towns on the circuit. A missing leg makes the total unknown."""
    hours = [0.0, 0.0]
    bus = [0, 0]
    for origin, destination in zip(towns, towns[1:], strict=False):
        leg = transport_options(origin, destination)
        if not leg["found"]:
            return None
        for bound in range(2):
            hours[bound] += leg["hours"][bound]
            bus[bound] += leg["fares"]["bus_per_person_inr"][bound]
    return {"hours": [round(v, 2) for v in hours], "bus_per_person_inr": bus}


def rank_routes(options: list[dict], wanted: set[str], weights: dict[str, float]) -> list[dict]:
    def town_fit(option):
        towns = set(option["destinations"])
        return -len(towns & wanted), len(towns - wanted) if wanted else 0

    ranked = sorted(options, key=lambda option: (*town_fit(option), -option["score"]))
    if not weights:
        return ranked

    for _, group in groupby(range(len(ranked)), key=lambda i: town_fit(ranked[i])):
        # Only adjust comparable routes. Keep the slots for routes with season cautions or
        # incomplete estimates, and never trade a requested town for a shorter trip.
        slots = [i for i in group if not ranked[i]["reasons"] and ranked[i]["transfers"]]
        if len(slots) < 2:
            continue
        comparable = [ranked[i] for i in slots]
        scores = [float(option["score"]) for option in comparable]
        for priority, metric in METRICS.items():
            weight = weights.get(priority, 0)
            if not weight:
                continue
            midpoints = [sum(option["transfers"][metric]) / 2 for option in comparable]
            low, high = min(midpoints), max(midpoints)
            if low != high:
                for i, midpoint in enumerate(midpoints):
                    scores[i] += MAX_BONUS * weight * (high - midpoint) / (high - low)
        for slot, index in zip(slots, sorted(range(len(scores)), key=lambda i: -scores[i]),
                               strict=True):
            ranked[slot] = comparable[index]
    return ranked
