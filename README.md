# TravelBuddy (DevBhoomi Planner)

An agentic, end-to-end trip assistant for Uttarakhand (Devbhoomi, "land of the gods"): weather and season checks, a
validated day-by-day itinerary, cost estimate, assisted booking, and a live companion,
with a human decision at every step that costs money or affects safety.

**Status: Phase 0 (foundation).** Ported from the VietBot prototype and cleaned up.

## Roadmap

| Phase | Output |
|---|---|
| 0 | Clean structure, bug fixes, tests, Docker, CI (this commit) |
| 0.5 / 1 | Uttarakhand data pipeline (`ingest/`, `data/`) |
| 2 | Self-RAG as a LangGraph + eval baseline (`eval/`) |
| 3 | MCP server, cost engine, fare adapters (`mcp_server/`, `app/cost`, `app/rules`) |
| 4 | Multi-agent trip graph with human-in-the-loop interrupts (`app/graph`) |
| 5 | Trip persistence, monitor, companion |
| 6 | Frontend |
| 7 | CI/CD eval gate, deploy |

## Travel-buddy features

- **Specialist agents.** After research a supervisor step runs Stay, Food and Transport agents in
  parallel; a Safety agent reviews the validated plan (altitude and acclimatisation, high-altitude
  health, Char Dham registration and other advisories). All are deterministic and tested; the LLM
  only composes the plan.
- **Memory.** Preferences (budget, diet, pace, language, origin, interests) are stored per user
  and used as defaults; the planner learns from approved trips and never overrides what you set.
- **Mid-trip re-planning.** `POST /api/trips/{id}/replan` keeps the days already done, re-plans the
  rest with your reason (rain, cancelled bus...), re-validates it and asks for approval again.
- **Hindi / Hinglish.** Requests, prompts, itineraries and chat answers follow the traveller's
  language. The PDF and WhatsApp summary are English (the PDF font is Latin-1 only).
- **Timeline and map.** A suggested time-of-day schedule and a Leaflet/OpenStreetMap map.
- **Export.** WhatsApp text, PDF and calendar (.ics); a booking checklist whose ticks are saved.
- **Offline.** The app shell is cached by a service worker and opened trips are kept in the
  browser, so an itinerary opens without signal (map tiles need a connection).
- Saved trips, profiles and ticks live in SQLite at `TRIPS_PATH` (default `data/trips.sqlite`);
  like the checkpoint file it needs a persistent disk on hosts that wipe storage on redeploy.

## Architecture notes

- **Self-RAG** (`app/rag/self_rag.py`): retrieve, grade, rewrite, answer, verify, or decline.
- **Trip planner** (`app/graph/`): LangGraph multi-agent flow with human approval steps. Trip state
  is durable (SQLite checkpointer), so a plan paused for a decision survives a server restart.
- **MCP**: the planner calls its tools (budget, season, altitude, weather) through a real MCP
  client. `MCP_TRANSPORT=memory` runs the server in-process; `stdio` launches it as a subprocess.
  The same server can be used by any MCP host: `python -m mcp_server.server`.

## Layout

```
app/api      FastAPI routes, auth, rate limiting
app/db       Neo4j store
app/rag      Hybrid RAG (Phase 2 turns this into Self-RAG)
app/graph    LangGraph trip graph (Phase 4)
app/cost     Deterministic cost engine (Phase 3)
app/rules    Season / altitude / permit validators (Phase 3)
mcp_server/  Own MCP server (Phase 3)
ingest/      Data pipeline (Phase 1)
data/        Curated, sourced data (bus routes, gateways, dishes, permits)
eval/        Golden queries and metrics
tests/
```

## Run locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # fill in keys
pytest -q
uvicorn app.api.asgi:app --reload
```

## Fixed from the prototype

- Rate limiter swallowed its own 429 inside a broad `except`; now only Redis errors fail open.
- Redis host was hardcoded; now configurable.
- `<thinking>` instruction leaked reasoning into replies; removed.
- `SECRET_KEY` missing caused a runtime crash; now validated at startup.
- Deprecated `on_event` and `datetime.utcnow` replaced (lifespan, timezone-aware UTC).
- Services were created at import time; now created in the lifespan, so tests use fakes.

## Data

`data/processed/` is generated and git-ignored: run `python -m ingest.build` to produce it
(add `--google` with `GOOGLE_PLACES_API_KEY` set to fill remaining coordinates).
Google-sourced coordinates are subject to Google's terms and must not be committed or
published. Sources: Wikivoyage (CC BY-SA 4.0), OpenStreetMap contributors (ODbL), Open-Meteo.
