import pytest

from app.graph.critic import validate_plan
from app.transport.routes import _load, fares, find_route, transport_options
from mcp_server.client import LocalTools, ToolError


def test_route_is_symmetric_and_has_distance_and_hours():
    fwd = transport_options("delhi", "destination_haridwar", people=3)
    assert fwd["found"] and fwd["distance_km"] == 215
    assert fwd["hours"][0] < fwd["hours"][1]
    assert fwd["rail_station"] == "HW"
    assert find_route("destination_haridwar", "city_delhi") is find_route(
        "city_delhi", "destination_haridwar")


def test_fares_are_labelled_assumptions_and_shared_by_taxi_seats():
    f = fares(100, people=2)
    assert f["source"] == "assumption"
    assert f["taxi_per_person_inr"][0] == f["taxi_per_vehicle_inr"][0] // 2
    # more than 4 people still only split a single 4-seat vehicle
    assert fares(100, people=9)["taxi_per_person_inr"][0] == f["taxi_per_vehicle_inr"][0] // 4


def test_unknown_pair_is_not_invented():
    r = transport_options("mumbai", "destination_nainital")
    assert r["found"] is False and "No curated route" in r["message"]


def test_no_departure_times_are_stored():
    r = transport_options("delhi", "destination_nainital")
    assert "Not stored" in r["departure_times"]
    assert all("depart" not in k for route in _load()["routes"] for k in route)


def test_every_route_endpoint_is_known():
    from app.graph.trip_graph import DESTINATIONS
    cities = set(_load()["cities"])
    for r in _load()["routes"]:
        for end in (r["a"], r["b"]):
            assert end in DESTINATIONS or end in cities, end


def test_local_tools_exposes_transport_and_rejects_bad_args():
    t = LocalTools()
    assert t.call("get_transport", origin="delhi", destination="destination_dehradun")["found"]
    with pytest.raises(ToolError):
        t.call("get_transport", origin="delhi")


def test_critic_quotes_road_distance_for_transfers():
    plan = {"days": [
        {"day": 1, "destination": "destination_nainital", "stops": [], "meals": [], "stay": None},
        {"day": 2, "destination": "destination_almora", "stops": [], "meals": [], "stay": None}]}
    _, warnings = validate_plan(
        plan, {}, {"days": 2, "month": 10}, lambda d, m: {"status": "good"},
        transfer_fn=lambda a, b: transport_options(a, b))
    text = " ".join(warnings)
    assert "67 km by road" in text


def test_unpriced_stay_uses_comparable_listings_and_says_so():
    from app.cost.engine import StayChoice, TripInput, estimate
    from app.graph.trip_graph import TripPlanner

    dest = "destination_nainital"
    ents = {f"s{i}": {"id": f"s{i}", "type": "Stay", "destination_id": dest, "name": f"S{i}",
                      "price_text": f"₹{p}"} for i, p in enumerate([1000, 2000, 3000, 4000])}
    ents["x"] = {"id": "x", "type": "Stay", "destination_id": dest, "name": "Unpriced",
                 "price_text": ""}
    line = TripPlanner._stay_line("x", 2, "mid", ents)
    assert line["comparable_range"] == [2000, 4000] and "4 priced stays" in line["comparable_note"]
    est = estimate(TripInput(people=2, days=3, tier="mid", stays=[StayChoice(
        nights=2, tier="mid", name="Unpriced", comparable_range=(2000, 4000))]))
    assert est.items[0].source == "comparable" and est.items[0].low == 4000
    # too few comparables: no invented range
    assert "comparable_range" not in TripPlanner._stay_line(
        "x", 1, "mid", {"x": ents["x"], "s0": ents["s0"]})


def test_conditions_warn_for_closed_shrine_and_point_to_official_page():
    from app.rules.conditions import advisories_for, heavy_rain_flag
    r = advisories_for("destination_kedarnath", 1)
    assert any("closed in winter" in a["text"] for a in r["advisories"])
    assert all(a["verify"].startswith("https://") for a in r["advisories"])
    assert advisories_for("destination_kedarnath", 6)["advisories"][0]["verify_name"]
    assert advisories_for("destination_dehradun", 6)["advisories"] == []  # no invented ones
    with pytest.raises(ValueError):
        advisories_for("destination_kedarnath", 13)
    assert heavy_rain_flag({"kind": "typical", "days": [{"date": "x", "rain_mm": 99}]}) is None
    flag = heavy_rain_flag({"kind": "forecast", "days": [
        {"date": "2026-07-01", "rain_mm": 40}, {"date": "2026-07-02", "rain_mm": 2}]})
    assert "2026-07-01" in flag["text"] and "2026-07-02" not in flag["text"]


def test_conditions_tool_degrades_when_forecast_fails(monkeypatch):
    from mcp_server import tools

    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(tools, "weather_for", boom)
    r = tools.conditions_for("destination_auli", 8, 30.5, 79.5, "2026-08-01", "2026-08-03")
    assert "unavailable" in r["live_check"] and r["advisories"]


def test_planner_never_offers_destinations_without_data():
    from app.graph.trip_graph import CIRCUITS, DESTINATIONS, NOT_READY
    assert NOT_READY <= set(DESTINATIONS)
    offered_circuits = [c for c, _ in CIRCUITS if not NOT_READY.intersection(c)]
    assert ["destination_nainital", "destination_almora"] in offered_circuits
    assert all(d not in NOT_READY for c in offered_circuits for d in c)


def test_booking_links_use_the_right_airport_and_road_info():
    from app.booking.links import build_booking_links
    plan = {"days": [{"day": 1, "destination": "destination_nainital", "stay": None}]}
    links = build_booking_links({"origin": "Delhi", "people": 2}, plan, {})
    assert "PGH" in links["flights"][0]["url"] and "Pantnagar" in links["flights"][0]["label"]
    assert "(KGM)" in links["trains"][0]["label"]
    assert "305 km" in links["buses"][0]["note"] and "Departure times" in links["buses"][0]["note"]
    hw = build_booking_links({"origin": "Delhi"}, {"days": [
        {"day": 1, "destination": "destination_haridwar", "stay": None}]}, {})
    assert "DED" in hw["flights"][0]["url"]
