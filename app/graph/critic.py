"""Deterministic plan validation (the Critic). No LLM: every rule is checkable code.

A plan is:
  {"days": [{"day": 1, "destination": "destination_haridwar", "stops": [ids],
             "meals": [ids], "stay": id | None}, ...]}

`errors` send the plan back to the Planner; `warnings` are shown to the traveller.
"""
from ingest.geo import haversine_km

MAX_STOPS = 3
MAX_MEALS = 2
MAX_SAME_DAY_KM = 15.0  # straight-line spread between a day's stops
STOP_TYPES = {"Attraction", "Activity"}


def pretty(dest_id: str) -> str:
    return dest_id.removeprefix("destination_").replace("_", " ").title()


def _dist(a: dict, b: dict) -> float | None:
    if None in (a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon")):
        return None
    return haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])


def validate_plan(plan: dict, entities: dict[str, dict], request: dict, season_fn,
                  centres: dict[str, tuple[float, float]] | None = None,
                  transfer_fn=None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    days = plan.get("days") if isinstance(plan, dict) else None
    n_days = request["days"]
    if not isinstance(days, list) or not days:
        return ["Plan has no days."], warnings
    if [d.get("day") for d in days] != list(range(1, n_days + 1)):
        errors.append(f"Plan must have exactly days 1..{n_days} in order.")
        return errors, warnings

    seen_stops: set[str] = set()
    for d in days:
        n = d["day"]
        for key, allowed, cap in (("stops", STOP_TYPES, MAX_STOPS), ("meals", {"Eatery"}, MAX_MEALS)):
            ids = d.get(key) or []
            if len(ids) > cap:
                errors.append(f"Day {n}: at most {cap} {key}.")
            for i in ids:
                ent = entities.get(i)
                if ent is None:
                    errors.append(f"Day {n}: unknown id {i!r} (only use ids from the candidates).")
                elif ent.get("type") not in allowed:
                    errors.append(f"Day {n}: {i} is a {ent.get('type')}, not allowed in {key}.")
                elif ent.get("destination_id") and ent["destination_id"] != d.get("destination"):
                    errors.append(f"Day {n}: {i} ({ent.get('name', i)}) is in "
                                  f"{pretty(ent['destination_id'])}, not "
                                  f"{pretty(d.get('destination', ''))}; use only that day's "
                                  "destination.")
                elif key == "stops" and i in seen_stops:
                    errors.append(f"Day {n}: {i} is already visited on an earlier day.")
                seen_stops.add(i) if key == "stops" else None

        stay_id = d.get("stay")
        last_day = n == n_days
        if stay_id:
            stay = entities.get(stay_id)
            if stay is None or stay.get("type") != "Stay":
                errors.append(f"Day {n}: stay {stay_id!r} is not a known stay.")
            elif stay.get("destination_id") != d.get("destination"):
                errors.append(f"Day {n}: stay {stay_id} is not in {d.get('destination')}.")
            elif last_day:
                warnings.append(f"Day {n}: a stay is listed on the last day; it will not be priced.")
        elif not last_day:
            errors.append(f"Day {n}: a stay is required for the night.")

        located = [entities[i] for i in (d.get("stops") or []) if i in entities]
        worst = 0.0
        for a_i, a in enumerate(located):
            for b in located[a_i + 1:]:
                km = _dist(a, b)
                if km is not None:
                    worst = max(worst, km)
        if worst > MAX_SAME_DAY_KM:
            warnings.append(f"Day {n}: stops are up to {worst:.0f} km apart (straight line); "
                            "allow extra travel time.")

        status = season_fn(d.get("destination", ""), request["month"])
        if status.get("status") == "caution":
            warnings.append(f"Day {n}: {'; '.join(status.get('reasons', []))}")
        elif status.get("status") == "unknown":
            warnings.append(f"Day {n}: no season data for {pretty(d.get('destination', ''))}.")

    for prev, cur in zip(days, days[1:], strict=False):
        if prev.get("destination") != cur.get("destination"):
            note = "allow 1-2 hours by road"
            info = transfer_fn(prev["destination"], cur["destination"]) if transfer_fn else None
            if info and info.get("found"):
                lo, hi = info["hours"]
                note = (f"about {info['distance_km']} km by road, roughly {lo:g}-{hi:g} hours"
                        + (f". {info['note']}" if info.get("note") else ""))
            elif centres and prev["destination"] in centres and cur["destination"] in centres:
                km = haversine_km(*centres[prev["destination"]], *centres[cur["destination"]])
                note = f"about {km:.0f} km straight line; {note}"
            warnings.append(f"Day {cur['day']}: transfer from {pretty(prev['destination'])} to "
                            f"{pretty(cur['destination'])} ({note}).")
    return errors, warnings


def fallback_plan(request: dict, destinations: list[str], candidates: dict[str, dict]) -> dict:
    """Deterministic plan used if the LLM planner cannot produce a valid one."""
    n = request["days"]
    per = max(1, n // len(destinations))
    days = []
    used: set[str] = set()
    for day in range(1, n + 1):
        dest = destinations[min((day - 1) // per, len(destinations) - 1)]
        pool = candidates[dest]
        stops = [e["id"] for e in pool["stops"] if e["id"] not in used][:2]
        used.update(stops)
        meals = [e["id"] for e in pool["meals"]][:1]
        stay = pool["stays"][0]["id"] if pool["stays"] and day < n else None
        days.append({"day": day, "destination": dest, "stops": stops, "meals": meals,
                     "stay": stay})
    return {"days": days}
