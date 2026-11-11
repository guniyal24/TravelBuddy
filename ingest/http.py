"""Polite HTTP client with retry/backoff and an on-disk cache for raw API responses."""
import hashlib
import json
import logging
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "TravelBuddy/1.0 (https://github.com/guniyal24/TravelBuddy; trip planner data build)"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def get_json(url: str, params: dict | None = None, retries: int = 4, pause: float = 1.0) -> dict:
    """GET JSON with a disk cache so re-runs do not hit the APIs again."""
    key = hashlib.sha256(
        (url + json.dumps(params or {}, sort_keys=True)).encode()
    ).hexdigest()[:20]
    cache = RAW_DIR / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text())

    delay = 2.0
    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=30,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.json()
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data))
            time.sleep(pause)  # be polite to public APIs
            return data
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")
