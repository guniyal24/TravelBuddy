"""The town registry (data/seeds/destinations.yaml), loaded once for the whole app.

Before this, the nine offered towns were hard-coded in five places (planner, name matching,
safety elevations, booking stations, circuits). Now a town is added in one YAML file.
"""
from functools import lru_cache
from pathlib import Path

import yaml

SEEDS = Path(__file__).resolve().parent.parent / "data" / "seeds" / "destinations.yaml"


@lru_cache(maxsize=1)
def _load() -> dict:
    return yaml.safe_load(SEEDS.read_text())


def towns() -> list[dict]:
    return _load()["destinations"]


DESTINATIONS: dict[str, dict] = {
    t["id"]: {"name": t["name"], "lat": t["lat"], "lon": t["lon"],
              "themes": t.get("themes") or [], "region": t.get("region", "")}
    for t in towns()}
# Offered by the planner (enough places and stays in the data); the rest are known by name, so
# a traveller who asks for one is told it cannot be planned yet.
NOT_READY: set[str] = {t["id"] for t in towns() if not t.get("offer")}
PLACE_ALIASES: dict[str, list[str]] = {
    t["id"]: list(dict.fromkeys([t["name"].lower(), *[a.lower() for a in t.get("aliases") or []]]))
    for t in towns()}
ELEVATION_M: dict[str, float] = {t["id"]: t["elevation_m"] for t in towns()
                                 if t.get("elevation_m") is not None}
STATIONS: dict[str, tuple[str, str]] = {t["id"]: tuple(t["station"]) for t in towns()
                                        if t.get("station")}
KUMAON: set[str] = {t["id"] for t in towns() if t.get("region") == "Kumaon"}
ACCESS_NOTES: dict[str, str] = {t["id"]: t["access_note"] for t in towns() if t.get("access_note")}
CIRCUITS: list[tuple[list[str], int]] = [(list(c[0]), int(c[1]))
                                         for c in _load().get("circuits") or []]
