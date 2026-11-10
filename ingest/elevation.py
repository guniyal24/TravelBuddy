"""Elevation lookup via the free Open-Meteo elevation API (up to 100 points per call)."""
from ingest.http import get_json

API = "https://api.open-meteo.com/v1/elevation"
BATCH = 100


def fetch_elevations(points: list[tuple[float, float]]) -> list[float | None]:
    out: list[float | None] = []
    for i in range(0, len(points), BATCH):
        chunk = points[i : i + BATCH]
        data = get_json(
            API,
            {
                "latitude": ",".join(f"{lat:.5f}" for lat, _ in chunk),
                "longitude": ",".join(f"{lon:.5f}" for _, lon in chunk),
            },
        )
        out.extend(data.get("elevation", [None] * len(chunk)))
    return out
