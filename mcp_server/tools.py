"""Plain-Python tool implementations (JSON in, JSON out). The MCP server just wraps these,
so they can be unit-tested and reused by the agents directly."""
from dataclasses import asdict
from datetime import date

from app.cost.engine import StayChoice, TransportLeg, TripInput, estimate
from app.rules.altitude import Stop, check_altitude_plan
from app.rules.season import check_season
from mcp_server import weather


def estimate_budget(people: int, days: int, tier: str = "budget", stays: list[dict] | None = None,
                    legs: list[dict] | None = None, entry_fees_per_person: float = 0.0,
                    permits_total: float = 0.0) -> dict:
    trip = TripInput(
        people=people, days=days, tier=tier,
        stays=[StayChoice(nights=s["nights"], tier=s.get("tier", tier),
                          price_text=s.get("price_text", ""), name=s.get("name", ""),
                          comparable_range=(tuple(s["comparable_range"])
                                            if s.get("comparable_range") else None),
                          comparable_note=s.get("comparable_note", ""))
               for s in (stays or [])],
        legs=[TransportLeg(description=leg["description"],
                           fare_per_person=(leg["fare_low"], leg.get("fare_high", leg["fare_low"])),
                           source=leg.get("source", "user"))
              for leg in (legs or [])],
        entry_fees_per_person=entry_fees_per_person, permits_total=permits_total)
    est = estimate(trip)
    return {"items": [asdict(i) for i in est.items], "subtotal_inr": list(est.subtotal),
            "total_inr": list(est.total), "per_person_inr": list(est.per_person),
            "currency": "INR",
            "disclaimer": "Estimate only. Lines with source 'assumption' use placeholder rates."}


def season_check(place_id: str, month: int) -> dict:
    return asdict(check_season(place_id, month))


def altitude_check(stops: list[dict], vulnerable_travellers: bool = False) -> dict:
    issues = check_altitude_plan(
        [Stop(day=s["day"], name=s["name"], sleep_elevation_m=s["sleep_elevation_m"])
         for s in stops], vulnerable_travellers)
    return {"ok": not issues, "issues": [asdict(i) for i in issues],
            "disclaimer": "Planning guidance, not medical advice."}


def weather_for(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    return weather.get_weather(lat, lon, date.fromisoformat(start_date),
                               date.fromisoformat(end_date))


def transport_for(origin: str, destination: str, people: int = 1) -> dict:
    from app.transport.routes import transport_options
    return transport_options(origin, destination, people)


def conditions_for(place_id: str, month: int, lat: float | None = None,
                   lon: float | None = None, start_date: str | None = None,
                   end_date: str | None = None) -> dict:
    from app.rules.conditions import advisories_for, heavy_rain_flag
    out = advisories_for(place_id, month)
    if None not in (lat, lon, start_date, end_date):
        try:
            flag = heavy_rain_flag(weather_for(lat, lon, start_date, end_date))
        except Exception as exc:  # network/provider problem: say so, do not guess
            out["live_check"] = f"Forecast unavailable ({type(exc).__name__})."
        else:
            out["live_check"] = flag["text"] if flag else "No heavy rain in the forecast window."
            if flag:
                out["advisories"].append(flag)
    return out


def reviews_for(hotel: str, town: str, lat: float, lon: float, max_reviews: int = 5) -> dict:
    from mcp_server.places import place_reviews
    return place_reviews(hotel, town, lat, lon, max_reviews)


def search_web(query: str, max_results: int = 5) -> dict:
    from mcp_server.search import web_search
    return web_search(query, max_results)
