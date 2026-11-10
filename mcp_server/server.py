"""MCP server for the Uttarakhand planner.

Run over stdio (for an MCP client / the agents):   python -m mcp_server.server
Inspect interactively:  npx @modelcontextprotocol/inspector python -m mcp_server.server
"""
from mcp.server.mcpserver import MCPServer

from mcp_server import tools

server = MCPServer(
    name="uttarakhand-planner",
    instructions=(
        "Deterministic trip-planning tools for Uttarakhand: budget estimates, season and "
        "altitude checks, and weather. Prefer these over guessing numbers. Results that say "
        "'assumption' or 'unknown' must be shown to the user as such."
    ),
)


@server.tool()
def estimate_budget(people: int, days: int, tier: str = "budget", stays: list[dict] | None = None,
                    legs: list[dict] | None = None, entry_fees_per_person: float = 0.0,
                    permits_total: float = 0.0) -> dict:
    """Estimate total trip cost in INR as a low-high range with a line-item breakdown.

    tier: budget | mid | premium. stays: [{nights, tier?, price_text?, name?}].
    legs: [{description, fare_low, fare_high?}] fares per person.
    """
    return tools.estimate_budget(people, days, tier, stays, legs, entry_fees_per_person,
                                 permits_total)


@server.tool()
def check_season(place_id: str, month: int) -> dict:
    """Is this month a good time to visit a destination (e.g. destination_rishikesh)?
    Returns status good | ok | caution | unknown, with reasons and data confidence."""
    return tools.season_check(place_id, month)


@server.tool()
def check_altitude_plan(stops: list[dict], vulnerable_travellers: bool = False) -> dict:
    """Check a plan's sleeping altitudes for risky ascents.
    stops: [{day, name, sleep_elevation_m}]."""
    return tools.altitude_check(stops, vulnerable_travellers)


@server.tool()
def get_weather(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    """Daily temperature and rain. Forecast within 16 days, otherwise a labelled
    'typical' estimate from last year. Dates are YYYY-MM-DD."""
    return tools.weather_for(lat, lon, start_date, end_date)


@server.tool()
def get_transport(origin: str, destination: str, people: int = 1) -> dict:
    """Road distance, typical duration and fare estimates between a city (e.g. 'delhi') or a
    destination id and a destination id (e.g. destination_nainital). Fares are assumptions
    computed per km; departure times are not available and must come from the operator."""
    return tools.transport_for(origin, destination, people)


@server.tool()
def check_conditions(place_id: str, month: int, lat: float | None = None,
                     lon: float | None = None, start_date: str | None = None,
                     end_date: str | None = None) -> dict:
    """Recurring road/landslide/closure/crowd advisories for a destination in a month, with the
    official page to confirm on. With lat/lon and dates inside the 16-day forecast window it
    also flags heavy rain. This is not live road status."""
    return tools.conditions_for(place_id, month, lat, lon, start_date, end_date)


if __name__ == "__main__":
    server.run()
