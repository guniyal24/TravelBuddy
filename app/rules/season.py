"""Season check backed by data/curated/seasons.yaml. Never guesses for unknown places."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SEASONS_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "curated" / "seasons.yaml"


@dataclass
class SeasonCheck:
    place_id: str
    month: int
    status: str  # "good" | "ok" | "caution" | "unknown"
    reasons: list[str] = field(default_factory=list)
    confidence: str = ""


def load_seasons(path: Path = SEASONS_FILE) -> dict:
    return yaml.safe_load(path.read_text())["destinations"]


def check_season(place_id: str, month: int, seasons: dict | None = None) -> SeasonCheck:
    if not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    seasons = seasons if seasons is not None else load_seasons()
    entry = seasons.get(place_id)
    if entry is None:
        return SeasonCheck(place_id, month, "unknown",
                           ["No season data for this place; check official sources."])
    caution = {int(k): v for k, v in (entry.get("caution_months") or {}).items()}
    conf = entry.get("confidence", "")
    if month in caution:
        return SeasonCheck(place_id, month, "caution", [caution[month]], conf)
    if month in (entry.get("best_months") or []):
        return SeasonCheck(place_id, month, "good", ["Generally a good time to visit."], conf)
    return SeasonCheck(place_id, month, "ok", [], conf)
