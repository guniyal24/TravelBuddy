"""Standing advisories (from data/curated/advisories.yaml) plus an optional live rain check.

This is NOT live road status: no free, permitted API exists for closures. It returns recurring
conditions for the month, the official page to confirm them on, and (when real dates within the
forecast window are given) a forecast-based heavy-rain flag.
"""
from functools import lru_cache
from pathlib import Path

import yaml

FILE = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "advisories.yaml"
HEAVY_RAIN_MM = 30.0  # a single day at or above this counts as heavy rain


@lru_cache(maxsize=1)
def _load() -> dict:
    return yaml.safe_load(FILE.read_text())


def advisories_for(place_id: str, month: int) -> dict:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    data = _load()
    items = []
    for a in data["destinations"].get(place_id, []):
        if a["months"] == "all" or month in a["months"]:
            src = data["official"][a["link"]]
            items.append({"text": a["text"], "verify": src["url"], "verify_name": src["name"]})
    return {"place_id": place_id, "month": month, "advisories": items,
            "confidence": data["confidence"],
            "disclaimer": "Standing advisories, not live road status. Confirm on the official "
                          "page before you travel."}


def heavy_rain_flag(weather: dict) -> dict | None:
    """A warning from a forecast result of mcp_server.weather.get_weather, else None."""
    if weather.get("kind") != "forecast":
        return None
    heavy = [d for d in weather.get("days", []) if (d.get("rain_mm") or 0) >= HEAVY_RAIN_MM]
    if not heavy:
        return None
    return {"text": f"Forecast shows heavy rain (at least {HEAVY_RAIN_MM:g} mm) on "
                    + ", ".join(d["date"] for d in heavy) + ". Expect road delays or closures.",
            "verify": _load()["official"]["disaster"]["url"],
            "verify_name": _load()["official"]["disaster"]["name"]}
