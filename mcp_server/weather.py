"""Weather via Open-Meteo (free, no key). Forecast when the dates are within 16 days,
otherwise the same dates one year earlier as a rough "typical" guide (clearly labelled)."""
from datetime import date, timedelta

import httpx

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum"
MAX_FORECAST_DAYS = 16


def _fetch(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, timeout=20, headers={"User-Agent": "UttarakhandPlanner/0.1"})
    r.raise_for_status()
    return r.json()


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
