"""Town profiles: one short searchable summary per offered town.

The planner first searches these (in their own Pinecone namespace, so chat search never sees
them) to find towns that fit a request, and an LLM proposes circuits from the profiles alone.
Places are fetched only for the towns the traveller then picks.

    python -m ingest.town_profiles            # write data/curated/town_profiles.json
    python -m ingest.load towns               # embed and upsert them into Pinecone

A profile is built from the town registry (themes, region, elevation) and the places we hold
for that town (names and counts), so it describes what the planner can actually plan there.
Season is deliberately left out: it changes by month and is checked in code from seasons.yaml.
"""
import json
import re
from collections import Counter
from pathlib import Path

from ingest.schema import is_generic_name

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ROOT / "data" / "curated" / "town_profiles.json"
TOWN_NAMESPACE = "towns"
HIGHLIGHTS = 6
_MARKUP = re.compile(r"\b(?:thumb|right|left|upright)\|")


def _summary(description: str, max_chars: int = 220) -> str:
    """The first sentence or two of the town's description, without wiki markup."""
    text = " ".join(_MARKUP.sub("", description or "").split())
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if out and len(out) + len(sentence) > max_chars:
            break
        out = f"{out} {sentence}".strip()
    return out[:max_chars]


def build_profiles(entities: list[dict], towns: list[dict]) -> list[dict]:
    """One profile per offered town in the registry, in registry order."""
    by_town: dict[str, list[dict]] = {}
    described = {e["id"]: e for e in entities if e["type"] == "Destination"}
    for e in entities:
        if e.get("destination_id"):
            by_town.setdefault(e["destination_id"], []).append(e)
    profiles = []
    for t in towns:
        if not t.get("offer"):
            continue
        places = by_town.get(t["id"], [])
        sights = [e for e in places if e["type"] in ("Attraction", "Activity")
                  and not is_generic_name(e["name"])]
        # Landmarks before activities, then the best-described first (a fair proxy for how
        # notable a place is in the guide it came from).
        sights.sort(key=lambda e: (e["type"] != "Attraction", -len(e.get("description") or ""),
                                   e["name"]))
        tiers = Counter(e.get("tier") for e in places if e["type"] == "Stay" and e.get("tier"))
        counts = {"sights": len(sights),
                  "eateries": sum(e["type"] == "Eatery" for e in places),
                  "stays": sum(e["type"] == "Stay" for e in places)}
        elevation = t.get("elevation_m")
        head = f"{t['name']} ({t.get('region', '')}"
        head += f", {elevation:,.0f} m)." if elevation is not None else ")."
        parts = [head,
                 _summary((described.get(t["id"]) or {}).get("description", "")),
                 f"Good for: {', '.join(t.get('themes') or [])}.",
                 f"Highlights: {', '.join(e['name'] for e in sights[:HIGHLIGHTS])}."
                 if sights else "",
                 f"{counts['sights']} things to see and do, {counts['eateries']} eateries, "
                 f"{counts['stays']} stays"
                 + (f" ({', '.join(k for k in ('budget', 'mid', 'premium') if tiers[k])})."
                    if tiers else ".")]
        profiles.append({"id": t["id"], "name": t["name"], "region": t.get("region", ""),
                         "elevation_m": elevation, "themes": t.get("themes") or [],
                         "counts": counts, "text": " ".join(p for p in parts if p)})
    return profiles


def pinecone_town_record(profile: dict) -> dict:
    """Vector record for the towns namespace. `type: Town` keeps it apart even if it were
    ever queried together with places."""
    meta = {"name": profile["name"], "type": "Town", "city": profile["name"],
            "region": profile["region"], "semantic_text": profile["text"][:800]}
    if profile.get("elevation_m") is not None:
        meta["elevation_m"] = profile["elevation_m"]
    return {"id": profile["id"], "text": profile["text"], "metadata": meta}


def load_profiles(path: Path = PROFILES) -> dict[str, dict]:
    """Saved profiles by town id ({} if they were never built)."""
    if not path.exists():
        return {}
    return {p["id"]: p for p in json.loads(path.read_text())}


def main() -> None:
    from app.towns import towns
    from ingest.load import load_entities

    profiles = build_profiles(load_entities(), towns())
    PROFILES.write_text(json.dumps(profiles, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(profiles)} town profiles -> {PROFILES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
