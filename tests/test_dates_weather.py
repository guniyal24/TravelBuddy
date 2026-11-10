"""Travel dates and the weather agent."""
from datetime import date

import pytest
from test_trip_graph import GOOD, HW, REQ, RK, FakeLLM, FakeRetriever, FakeStore

import app.graph.trip_graph as tgm
from app.graph.render import day_date, weather_line
from app.graph.trip_graph import TripPlanner, valid_start
from mcp_server.client import LocalTools

TODAY = date(2026, 11, 10)
BOTH = f"{HW}+{RK}"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(tgm, "_today", lambda: TODAY)


def test_valid_start_rejects_past_far_future_and_junk():
    assert valid_start("2026-11-14", TODAY) == date(2026, 11, 14)
    assert valid_start("2026-11-09", TODAY) is None  # past
    assert valid_start("2028-01-01", TODAY) is None  # more than a year out
    assert valid_start("next friday", TODAY) is None


class WeatherTools(LocalTools):
    def __init__(self, kind="forecast", rain=(2.0, 45.0, 0.0)):
        self.kind, self.rain, self.calls = kind, list(rain), []

    def call(self, name, **kw):
        if name == "get_weather":
            self.calls.append(kw)
            s, e = date.fromisoformat(kw["start_date"]), date.fromisoformat(kw["end_date"])
            n = (e - s).days + 1
            return {"kind": self.kind, "days": [
                {"date": str(s), "max_c": 22, "min_c": 9, "rain_mm": self.rain.pop(0)}
                for _ in range(n)]}
        return super().call(name, **kw)


def _plan(start_date=None, tools=None, text="x"):
    req = {**REQ, "start_date": start_date}
    tp = TripPlanner(FakeLLM([req, GOOD]), FakeRetriever(), FakeStore(), "s", "b",
                     tools=tools or WeatherTools())
    tp.start("w", text)
    r = tp.resume("w", BOTH)
    return tp, r, tp.graph.get_state({"configurable": {"thread_id": "w"}}).values


def test_start_date_sets_the_month_and_dates_the_timeline_and_itinerary():
    tp, r, vals = _plan("2026-11-20")
    assert vals["request"]["start_date"] == "2026-11-20"
    assert vals["request"]["month"] == 11
    days = r["prompt"]["timeline"]["days"]
    assert [d["date"] for d in days] == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert "## Day 1 - Haridwar · Friday 20 Nov" in r["prompt"]["preview"]
    assert "Weather: 9-22 °C, rain 2 mm (forecast)" in r["prompt"]["preview"]


def test_weather_is_fetched_per_town_block_and_heavy_rain_warns():
    tools = WeatherTools(rain=(2.0, 45.0, 0.0))
    _, r, vals = _plan("2026-11-12", tools)
    # Haridwar is day 1, Rishikesh days 2-3: two calls, one per consecutive town block
    assert [(c["start_date"], c["end_date"]) for c in tools.calls] == [
        ("2026-11-12", "2026-11-12"), ("2026-11-13", "2026-11-14")]
    warn = [w for w in r["prompt"]["warnings"] if w.startswith("Weather")]
    assert warn == ["Weather, day 2 (Friday 13 Nov, Rishikesh): heavy rain forecast (45 mm). "
                    "Hill roads can close; consider re-planning from day 2."]
    assert vals["weather"]["kind"] == "forecast"


def test_typical_weather_is_labelled_and_never_raises_rain_warnings():
    _, r, vals = _plan("2027-03-01", WeatherTools(kind="typical", rain=(60.0, 60.0, 60.0)))
    assert not [w for w in r["prompt"]["warnings"] if w.startswith("Weather")]
    assert "not a forecast" in vals["weather"]["note"]
    assert "typical for these dates, not a forecast" in r["prompt"]["preview"]


def test_without_dates_nothing_is_fetched():
    tools = WeatherTools()
    _, r, vals = _plan(None, tools)
    assert tools.calls == [] and vals["weather"] == {}
    assert r["prompt"]["timeline"]["days"][0]["date"] is None


def test_a_weather_outage_is_said_not_mistaken_for_missing_dates():
    from app.graph.trace import _end
    from mcp_server.client import ToolError

    class DownTools(WeatherTools):
        def call(self, name, **kw):
            if name == "get_weather":
                raise ToolError("HTTP 429")
            return super().call(name, **kw)

    _, r, vals = _plan("2026-11-12", DownTools())
    assert vals["weather"]["unavailable"] == 2 and vals["weather"]["days"] == []
    assert any(w.startswith("Live weather was unavailable") for w in r["prompt"]["warnings"])
    message, _, tone = _end("weather", vals, {"weather": vals["weather"]})
    assert "did not respond" in message and tone == "warn"


def test_weather_requests_retry_rate_limits_and_are_cached(monkeypatch):
    import httpx

    import mcp_server.weather as wm
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append(url)
        status = 429 if len(calls) == 1 else 200
        return httpx.Response(status, json={"daily": {}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(wm.httpx, "get", fake_get)
    monkeypatch.setattr(wm.time, "sleep", lambda s: None)
    monkeypatch.setattr(wm, "_cache", {})
    params = {"latitude": 1, "longitude": 2}
    assert wm._fetch(wm.FORECAST, params) == {"daily": {}}
    assert len(calls) == 2  # one 429, then success
    wm._fetch(wm.FORECAST, params)
    assert len(calls) == 2  # second call served from the cache


def test_a_past_date_from_the_model_is_dropped():
    _, _, vals = _plan("2020-01-01")
    assert vals["request"]["start_date"] is None and vals["request"]["month"] == 11


def test_the_model_is_told_today_to_resolve_relative_dates():
    llm = FakeLLM([{**REQ}])
    tp = TripPlanner(llm, FakeRetriever(), FakeStore(), "s", "b", tools=WeatherTools())
    tp.start("t", "next friday, 3 days")
    assert llm.prompts[0].startswith("TODAY: 2026-11-10 (Tuesday)")


def test_render_helpers():
    assert day_date({"start_date": "2026-11-20"}, 3) == date(2026, 11, 22)
    assert day_date({}, 1) is None
    assert weather_line(None) == ""
