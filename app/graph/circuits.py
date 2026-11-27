"""Circuits proposed by an LLM from town profiles, and the rule-based check they must pass.

The LLM sees only short town profiles and road times (not places), so the prompt stays small.
It suggests which towns to combine; code decides whether a suggestion is possible:

  - every town is one we can plan (offered, in the candidate list), none repeated
  - at most MAX_TOWNS towns, and enough days for the towns plus the driving between them
  - no single road leg longer than MAX_LEG_HOURS, and every leg has a known road route

The same principle as the plan Critic: the LLM suggests, code checks.
"""
import math
from collections.abc import Callable

MAX_TOWNS = 4
MAX_LEG_HOURS = 12.0

CIRCUIT_SYSTEM = (
    "You design trip circuits in Uttarakhand. From the candidate towns, propose up to 3 "
    "different circuits (ordered lists of town codes) that suit the traveller. Return JSON "
    'only: {"circuits":[{"towns":["code1","code2"],"why":"one short sentence"}]}. Rules: use '
    "only the given codes; include every town the traveller named in at least the first "
    "circuit; one town per 1-2 days is a comfortable pace; prefer towns that are close by "
    "road; avoid towns marked as a season caution unless the traveller named them; order "
    "towns so the route does not double back. Each circuit must be a different set of towns. "
    "A town needs at least one day, and long drives (see road times) use up time: for a "
    "1-2 day trip a single town is usually best."
)


def leg_days(hours_hi: float) -> float:
    """Days a road leg costs on top of the stay itself: a short hop is free, a half-day drive
    costs half a day, a long one a whole day or two. Calibrated so every curated circuit in
    destinations.yaml passes at its listed minimum days (tests/test_town_discovery.py)."""
    if hours_hi < 3.5:
        return 0.0
    if hours_hi < 6:
        return 0.5
    return 1.0 if hours_hi <= 10 else 2.0


def check_circuit(towns: list[str], days: int, allowed: set[str],
                  leg_fn: Callable[[str, str], dict | None]) -> list[str]:
    """Problems that make a circuit impossible; [] if it can be planned. `leg_fn(a, b)`
    returns {"hours": [low, high]} for the road between two towns, or None if unknown."""
    errors = []
    if not towns:
        return ["no towns"]
    unknown = [t for t in towns if t not in allowed]
    if unknown:
        errors.append(f"unknown or unavailable towns: {', '.join(unknown)}")
    if len(set(towns)) != len(towns):
        errors.append("a town is repeated")
    if len(towns) > MAX_TOWNS:
        errors.append(f"{len(towns)} towns; at most {MAX_TOWNS}")
    if errors:
        return errors
    needed = float(len(towns))
    for a, b in zip(towns, towns[1:], strict=False):
        leg = leg_fn(a, b)
        if not leg or not leg.get("hours"):
            errors.append(f"no known road route {a} -> {b}")
            continue
        hi = float(leg["hours"][1])
        if hi > MAX_LEG_HOURS:
            errors.append(f"{a} -> {b} is up to {hi:g} h by road; at most {MAX_LEG_HOURS:g} h")
        needed += leg_days(hi)
    if math.ceil(needed) > days:
        errors.append(f"needs at least {math.ceil(needed)} days for these towns and the "
                      f"driving between them; the trip has {days}")
    return errors


def parse_circuits(reply: dict, codes: dict[str, str]) -> list[dict]:
    """[{"towns": [destination ids], "why": str}] from the LLM reply. `codes` maps the short
    codes shown to the LLM back to destination ids; unknown codes are kept (as given) so the
    check can reject them, never silently dropped into a different route."""
    out = []
    for c in (reply or {}).get("circuits") or []:
        if not isinstance(c, dict):
            continue
        towns = [codes.get(str(t).strip().lower(), str(t)) for t in c.get("towns") or []]
        if towns:
            out.append({"towns": towns, "why": str(c.get("why") or "")[:200]})
    return out[:3]


def short_code(destination_id: str) -> str:
    return destination_id.removeprefix("destination_")
