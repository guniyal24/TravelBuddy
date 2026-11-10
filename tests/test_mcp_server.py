import asyncio
from datetime import date

import pytest

from mcp_server import tools, weather
from mcp_server.server import server

FORECAST = {"daily": {"time": ["2026-11-10", "2026-11-11"], "temperature_2m_max": [28, 27],
                      "temperature_2m_min": [14, 13], "precipitation_sum": [0, 8.2]}}


def test_estimate_budget_tool_json_shape():
    out = tools.estimate_budget(2, 3, "mid", stays=[{"nights": 2, "price_text": "₹2000-3000"}],
                                legs=[{"description": "Delhi-Haridwar", "fare_low": 400}])
    assert out["currency"] == "INR" and out["total_inr"][0] < out["total_inr"][1]
    assert any(i["source"] == "listing" for i in out["items"])


def test_season_and_altitude_tools():
    assert tools.season_check("destination_rishikesh", 7)["status"] == "caution"
    plan = [{"day": 1, "name": "A", "sleep_elevation_m": 2000},
            {"day": 2, "name": "B", "sleep_elevation_m": 3600}]
    out = tools.altitude_check(plan)
    assert out["ok"] is False and out["issues"][0]["day"] == 2


def test_weather_uses_forecast_inside_window():
    seen = {}

    def fake(url, params):
        seen["url"] = url
        return FORECAST

    out = weather.get_weather(30.0, 78.0, date(2026, 11, 10), date(2026, 11, 11),
                              today=date(2026, 11, 8), fetch=fake)
    assert out["kind"] == "forecast" and seen["url"] == weather.FORECAST
    assert out["rainy_days"] == 1 and out["days"][1]["rain_mm"] == 8.2


def test_weather_far_dates_are_labelled_typical_and_use_past_year():
    seen = {}

    def fake(url, params):
        seen.update(url=url, params=params)
        return FORECAST

    out = weather.get_weather(30.0, 78.0, date(2027, 6, 10), date(2027, 6, 12),
                              today=date(2026, 11, 8), fetch=fake)
    assert out["kind"] == "typical" and "not a forecast" in out["note"]
    assert seen["url"] == weather.ARCHIVE and seen["params"]["start_date"] == "2026-06-10"


def test_weather_validates_range():
    with pytest.raises(ValueError):
        weather.get_weather(0, 0, date(2026, 11, 12), date(2026, 11, 10), fetch=lambda *a: {})
    with pytest.raises(ValueError):
        weather.get_weather(0, 0, date(2026, 1, 1), date(2026, 3, 1), fetch=lambda *a: {})


def test_server_registers_all_tools_and_calls_one():
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"estimate_budget", "check_season", "check_altitude_plan", "get_weather",
                     "get_transport", "check_conditions", "place_reviews", "web_search"}
    res = asyncio.run(server.call_tool("check_season",
                                       {"place_id": "destination_haridwar", "month": 11}))
    assert "good" in str(res)


def _met(*steps):
    return {"properties": {"timeseries": [
        {"time": t, "data": {"instant": {"details": {"air_temperature": temp}},
                             key: {"details": {"precipitation_amount": rain}}}}
        for t, temp, key, rain in steps]}}


def test_met_steps_become_indian_dates_without_double_counting_rain():
    data = _met(("2026-11-12T18:00:00Z", 9.0, "next_1_hours", 1.0),   # 23:30 IST, 12 Nov
                ("2026-11-12T19:00:00Z", 8.0, "next_1_hours", 2.0),   # 00:30 IST, 13 Nov
                ("2026-11-13T06:00:00Z", 21.0, "next_6_hours", 4.0),  # 11:30 IST, 13 Nov
                ("2026-11-14T06:00:00Z", 20.0, "next_6_hours", 0.0))  # outside the range
    days = weather.met_daily(data, date(2026, 11, 12), date(2026, 11, 13))
    assert days == [
        {"date": "2026-11-12", "max_c": 9.0, "min_c": 9.0, "rain_mm": 1.0},
        {"date": "2026-11-13", "max_c": 21.0, "min_c": 8.0, "rain_mm": 6.0}]


def test_a_rate_limited_forecast_falls_back_to_met_norway():
    import httpx

    def limited(url, params):
        req = httpx.Request("GET", url)
        raise httpx.HTTPStatusError("429", request=req, response=httpx.Response(429, request=req))

    met = _met(("2026-11-11T06:00:00Z", 20.0, "next_6_hours", 0.5))
    out = weather.get_weather(30.0, 78.0, date(2026, 11, 11), date(2026, 11, 11),
                              today=date(2026, 11, 10), fetch=limited,
                              fetch_met=lambda lat, lon: met)
    assert out["source"] == "MET Norway" and out["kind"] == "forecast"
    assert out["days"][0]["max_c"] == 20.0
    with pytest.raises(httpx.HTTPStatusError):  # MET does not reach these dates: say so
        weather.get_weather(30.0, 78.0, date(2026, 11, 22), date(2026, 11, 23),
                            today=date(2026, 11, 10), fetch=limited,
                            fetch_met=lambda lat, lon: met)
