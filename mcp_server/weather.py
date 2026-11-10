"""Weather via Open-Meteo (free, no key). Forecast when the dates are within 16 days,
otherwise the same dates one year earlier as a rough "typical" guide (clearly labelled)."""
import json
import threading
import time
from datetime import date, timedelta

import httpx

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"
MAX_FORECAST_DAYS = 16
CACHE_SECONDS = 3600  # a forecast does not change much within an hour
RETRY_STATUS = {429, 500, 502, 503, 504}

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def fetch_uncached(url: str, params: dict, attempts: int = 3, pause: float = 1.0) -> dict:
    """GET with retries: Open-Meteo rate-limits busy shared IPs (cloud hosts) with 429."""
    for attempt in range(attempts):
        try:
            r = httpx.get(url, params=params, timeout=15,
                          headers={"User-Agent": "TravelBuddy/1.0"})
            if r.status_code not in RETRY_STATUS or attempt == attempts - 1:
                r.raise_for_status()
                return r.json()
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
        time.sleep(pause * 2 ** attempt)
    raise RuntimeError("unreachable")


def _fetch(url: str, params: dict) -> dict:
    """Cached for an hour per (url, params), so repeated plans for the same town and dates
    make one request."""
    key = url + json.dumps(params, sort_keys=True)
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    data = fetch_uncached(url, params)
    with _cache_lock:
        if len(_cache) > 2000:  # bounded: drop everything rather than grow forever
            _cache.clear()
        _cache[key] = (time.monotonic(), data)
    return data


def get_weather(lat: float, lon: float, start: date, end: date, today: date | None = None,
                fetch=_fetch) -> dict:
    if end < start:
        raise ValueError("end must be on or after start")
    if (end - start).days > 30:
        raise ValueError("date range too long (max 31 days)")
    today = today or date.today()
    base = {"latitude": lat, "longitude": lon, "daily": DAILY, "timezone": "Asia/Kolkata"}

    if end <= today + timedelta(days=MAX_FORECAST_DAYS - 1) and start >= today:
        data = fetch(FORECAST, {**base, "start_date": start.isoformat(),
                                "end_date": end.isoformat()})
        kind = "forecast"
        note = "Weather forecast from Open-Meteo."
    else:
        ys, ye = _shift_year(start), _shift_year(end)
        while ye >= today:  # archive only has past dates
            ys, ye = _shift_year(ys, -1), _shift_year(ye, -1)
        data = fetch(ARCHIVE, {**base, "start_date": ys.isoformat(), "end_date": ye.isoformat()})
        kind = "typical"
        note = (f"Dates are beyond the forecast window. Showing {ys} to {ye} as a rough guide "
                "to typical conditions; not a forecast.")

    d = data.get("daily", {})
    days = [{"date": t, "max_c": mx, "min_c": mn, "rain_mm": rain}
            for t, mx, mn, rain in zip(d.get("time", []), d.get("temperature_2m_max", []),
                                       d.get("temperature_2m_min", []),
                                       d.get("precipitation_sum", []), strict=False)]
    rainy = sum(1 for x in days if (x["rain_mm"] or 0) >= 5)
    return {"kind": kind, "note": note, "days": days, "rainy_days": rainy,
            "source": "Open-Meteo"}


def _shift_year(d: date, years: int = -1) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + years, day=28)
