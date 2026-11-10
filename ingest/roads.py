"""Road distance and time between every pair of towns (and the main origin cities), from OSRM.

    python -m ingest.roads

One request to the OSRM table service (routing on OpenStreetMap data, ODbL) for all points at
once, saved to data/curated/road_matrix.json, so the app never calls a routing service at run
time. Curated routes in transport.yaml still win where they exist; the matrix fills every other
pair. OSRM's car speeds are generic, so app/transport/routes.py widens the times for hill roads.
"""
import json
from datetime import date
from pathlib import Path

import httpx

from app.towns import DESTINATIONS
from ingest.http import USER_AGENT

OSRM = "https://router.project-osrm.org/table/v1/driving/"
OUT = Path(__file__).resolve().parent.parent / "data" / "curated" / "road_matrix.json"
CITIES = {"city_delhi": (28.6139, 77.2090), "city_chandigarh": (30.7333, 76.7794),
          "city_lucknow": (26.8467, 80.9462)}


def build(client: httpx.Client | None = None) -> dict:
    points = {**{d: (v["lat"], v["lon"]) for d, v in DESTINATIONS.items()}, **CITIES}
    ids = list(points)
    coords = ";".join(f"{lon},{lat}" for lat, lon in points.values())
    http = client or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})
    r = http.get(OSRM + coords, params={"annotations": "duration,distance"})
    r.raise_for_status()
    data = r.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')}")
    km = [[round(x / 1000) if x is not None else None for x in row] for row in data["distances"]]
    hours = [[round(x / 3600, 2) if x is not None else None for x in row]
             for row in data["durations"]]
    return {"source": "OSRM table service, OpenStreetMap data (ODbL)",
            "fetched": date.today().isoformat(), "points": ids, "km": km, "hours": hours}


def main() -> None:
    matrix = build()
    OUT.write_text(json.dumps(matrix, indent=1))
    n = len(matrix["points"])
    print(f"Wrote {n} x {n} road matrix to {OUT}")


if __name__ == "__main__":
    main()
