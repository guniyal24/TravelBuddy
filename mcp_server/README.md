# TravelBuddy MCP server

Deterministic Uttarakhand travel tools over the [Model Context Protocol](https://modelcontextprotocol.io).
The trip planner uses them through a real MCP client; any MCP host (a desktop AI assistant, an
IDE such as Cursor, or your own agent) can use them too.

| tool | what it answers | needs |
|---|---|---|
| `estimate_budget` | trip cost as a low-high range in INR, every line labelled listing or assumption | nothing |
| `check_season` | is this month good, ok or a caution for a town, with reasons | nothing |
| `check_altitude_plan` | risky sleeping-altitude gains in a day-by-day plan | nothing |
| `check_conditions` | standing advisories for a town and month, with the official page to confirm | nothing |
| `get_transport` | road distance, calibrated hill-road time and fare ranges between towns or from Delhi, Chandigarh, Lucknow | nothing |
| `get_weather` | daily forecast (16 days) or a labelled typical estimate for any dates | nothing (Open-Meteo) |
| `place_reviews` | Google rating, review count and recent reviews for a hotel | `GOOGLE_PLACES_API_KEY` (billable, capped) |
| `web_search` | current web results for travel conditions | `TAVILY_API_KEY` (free tier) |

Towns are ids such as `destination_kausani`; the 27 known ones are in
[`data/seeds/destinations.yaml`](../data/seeds/destinations.yaml). Tools that would otherwise
guess say `unknown` or `assumption` instead.

## Use it from an MCP host

Clone the repository and install it once:

```bash
git clone https://github.com/guniyal24/TravelBuddy.git
cd TravelBuddy && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Then add the server to your host's MCP configuration file (its `mcpServers` section), with
your own absolute path:

```json
{
  "mcpServers": {
    "travelbuddy": {
      "command": "/absolute/path/to/TravelBuddy/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "env": { "PYTHONPATH": "/absolute/path/to/TravelBuddy" }
    }
  }
}
```

The six key-free tools work immediately. For hotel reviews or web search, add
`GOOGLE_PLACES_API_KEY` or `TAVILY_API_KEY` to `env`.

Try it: *"Is October a good month for Kedarnath, and how long is the drive from Rishikesh?"*

## Inspect it

```bash
npx @modelcontextprotocol/inspector .venv/bin/python -m mcp_server.server
```

## How the planner uses it

`mcp_server/client.py` has two clients with the same `call(name, **args)` interface:
`MCPTools` speaks MCP (in-process transport, or `stdio` to run this server as a subprocess,
exactly as a host does) and `LocalTools` calls the functions directly for fast unit tests.
Set `MCP_TRANSPORT=stdio` to run the app's agents against the server as a separate process.
