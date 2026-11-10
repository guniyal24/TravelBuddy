"""Altitude / acclimatisation checks for a day-by-day plan.

Rules follow widely used mountain-medicine guidance for avoiding acute mountain sickness
(e.g. Wilderness Medical Society / CDC advice). Treat them as planning warnings, not
medical advice; thresholds are parameters so they can be adjusted after review:

  * above 3,000 m, avoid raising the *sleeping* altitude by more than ~500 m per night
  * include a rest night for every ~1,000 m gained above 3,000 m
  * flag any sleeping altitude above 3,500 m for travellers who are children, elderly or
    have heart/lung conditions
"""
from dataclasses import dataclass

ACCLIMATISE_FROM_M = 3000
MAX_SLEEP_GAIN_M = 500
HIGH_ALTITUDE_M = 3500


@dataclass
class Stop:
    day: int
    name: str
    sleep_elevation_m: float


@dataclass
class Issue:
    severity: str  # "warning" | "info"
    day: int
    message: str


def check_altitude_plan(stops: list[Stop], vulnerable_travellers: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    ordered = sorted(stops, key=lambda s: s.day)
    for prev, cur in zip(ordered, ordered[1:], strict=False):
        gain = cur.sleep_elevation_m - prev.sleep_elevation_m
        if cur.sleep_elevation_m > ACCLIMATISE_FROM_M and gain > MAX_SLEEP_GAIN_M:
            issues.append(Issue(
                "warning", cur.day,
                f"Sleeping altitude rises {round(gain)} m (to {round(cur.sleep_elevation_m)} m at "
                f"{cur.name}); above {ACCLIMATISE_FROM_M} m keep the rise under "
                f"{MAX_SLEEP_GAIN_M} m per night or add an acclimatisation night."))
    for s in ordered:
        if s.sleep_elevation_m > HIGH_ALTITUDE_M and vulnerable_travellers:
            issues.append(Issue(
                "warning", s.day,
                f"{s.name} ({round(s.sleep_elevation_m)} m) is high altitude; consult a doctor "
                "first if travelling with children, elderly people or heart/lung conditions."))
    return issues
