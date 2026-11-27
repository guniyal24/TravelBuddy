<p align="center"><img src="frontend/public/logo.png" alt="TravelBuddy" height="72"></p>

<h1 align="center">TravelBuddy</h1>

<p align="center">
  An Uttarakhand trip planner with sourced places, live planning progress, and a plan you can review before saving.
</p>

<p align="center">
  <a href="https://travelbuddy-5md.pages.dev/"><img alt="Launch the TravelBuddy live demo" src="https://img.shields.io/badge/TravelBuddy-Launch_live_demo-0F766E?style=for-the-badge"></a>
  <br>
  <a href="https://travelbuddy-5md.pages.dev/"><strong>travelbuddy-5md.pages.dev</strong></a>
  <br>
  Try it as a guest, no sign-up needed.
</p>

<p align="center">
  <a href="https://github.com/guniyal24/TravelBuddy/actions/workflows/ci.yml"><img alt="GitHub Actions CI" src="https://github.com/guniyal24/TravelBuddy/actions/workflows/ci.yml/badge.svg"></a>
</p>

<p align="center">
  <a href="#try-a-trip">Try a trip</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#evaluation">Evaluation</a> ·
  <a href="#run-locally">Run locally</a> ·
  <a href="DEPLOY.md">Deploy</a>
</p>

TravelBuddy turns a request in English, Hindi, or Hinglish into a day-by-day trip through Garhwal or Kumaon. It retrieves hotels, restaurants, and activities from a regional knowledge base, checks the itinerary against travel rules, and shows price ranges with their assumptions. Travellers can try it as a guest, see which agents are working, and approve or edit the itinerary.

## Try a trip

Open the [live demo](https://travelbuddy-5md.pages.dev/) or the [local app](http://localhost:5173) after starting both services. Choose **Try it now, no sign-up** and paste:

> Three days in Haridwar and Rishikesh for two people in March. We prefer vegetarian food, a budget hotel, and a relaxed pace.

1. **Describe and choose.** Answer any follow-up questions, then pick a circuit. Season guidance appears before you commit to the route.
2. **Review the itinerary.** Open the agent trace, timeline, and map. Check the budget breakdown, transfer estimates, and advisory notes. Ask for a change or approve the plan.
3. **Choose a stay.** When alternatives are available, compare hotels by town. With Google Places configured, cards show ratings and attributed review excerpts. Your hotel selection updates the cost estimate.
4. **Save and use the plan.** Open **My trips**, tick booking tasks, and export a PDF, text summary, or `.ics` calendar. Booking links take you to the relevant external sites.
5. **Teach the planner what matters to you.** In **Improve your next trip**, choose shorter road transfers or lower estimated bus fare and save your feedback. Start a new trip with the same account or guest session. The Choose screen indicates when feedback changed the circuit order. Reopen the saved trip to change or remove that vote.
6. **Replan from a future day.** Pick a day and describe what changed. The itinerary and hotel selection keep completed days fixed.

The **Ask** tab runs a separate Q&A workflow. Try “Where can I do yoga in Rishikesh?” and open a source link to inspect its listing.

## What the app covers

| Feature | How it works |
|---|---|
| Regional knowledge base | The planner covers 26 towns. An ingestion pipeline collects Wikivoyage and OpenStreetMap listings, records provenance, and builds geographic relationships. |
| Itinerary validation | A deterministic Critic checks day order, listing IDs and types, town membership, duplicate stops, and overnight stays. Failed drafts are retried. A rule-based fallback goes through the same checks. |
| Routing, weather, and cost | Inter-town routing uses curated routes or a calibrated OSRM matrix. Dated trips can get forecasts or a labelled historical guide. Costs use ranges marked with their source or assumption. |
| Hotel concierge | LangGraph fans out research by town and gathers optional Tavily travel notes. A code score combines available ratings, review counts, tier, price, and review analysis. The verifier checks that each displayed pro or con cites an excerpt from its attributed review. |
| Traveller memory | LangGraph keeps the state of an in-progress trip. Approved trips can update preferences and past-trip memories, which travellers can view and delete. |
| Feedback-driven circuit ranking | Each saved trip can contribute one vote. The planner turns votes into personal ranking weights and applies them to estimated road time and per-person bus fare between towns. |
| Exports and offline access | The itinerary can be exported as text, PDF, or calendar events. The production PWA can reopen trips cached in the current session’s account context. |

## Architecture

```mermaid
flowchart LR
    U[React app] --> API[FastAPI]
    API -->|Plan and resume| G[LangGraph trip planner]
    API -->|Ask a question| Q[Self-RAG workflow]
    G --> R[Retrieve listings]
    Q --> R
    R --> P[(Pinecone vectors)]
    R --> N[(Neo4j knowledge graph)]
    G --> C[Draft and validate itinerary]
    C --> A[Traveller approval]
    A --> H[Hotel research and selection]
    H --> S[(Saved trips and checkpoints)]
    G --> T[MCP tools]
    Q --> V[Grade evidence and verify answer]
```

- **Planner.** Intake collects trip dates, party size, interests, and constraints. The advisor searches short town profiles in Pinecone (their own namespace), an LLM proposes circuits from those profiles and road times, and code rejects circuits that need more days or longer drives than the trip allows; the curated circuit list is the fallback. Research retrieves places from Pinecone only for the chosen towns, grades them against the traveller's interests, and then looks up full Neo4j records. Stay, food, and transport specialists prepare the candidates before the LLM drafts an itinerary. The planner runs the Critic, season and altitude checks, weather lookup, and range-based pricing before asking for approval.
- **Human approval and live progress.** LangGraph interrupts pause the workflow for missing details, circuit choice, itinerary approval, and hotel selection. FastAPI streams step updates using Server-Sent Events. PostgreSQL or SQLite stores the checkpoint and approved trip.
- **Q&A.** The workflow retrieves and grades candidates, rewrites an unproductive query once, enriches the context with the graph, then drafts and checks the response. An unverified draft gets one retry before the workflow abstains. Source links come from the retrieved records.
- **Tooling.** A reusable MCP server exposes budget, season, altitude, weather, transport, conditions, review, and web-search tools. The application can use it in-process or via stdio. [MCP setup](mcp_server/README.md)

### How the planner learns from feedback

Each priority's weight is its vote count divided by the total vote count plus one. A traveller with one vote for shorter transfers has a time weight of 0.5. The advisor compares the midpoints of each route's estimate ranges and awards a bounded bonus to routes that better fit those weights. Without feedback, the advisor uses its baseline order.

Requested towns keep priority, and options with season cautions or missing transfer estimates keep their baseline positions. Estimates cover the legs between towns in a circuit. The itinerary still goes through the deterministic Critic. The learning happens in the ranker and leaves the language model weights fixed.

## Evaluation

The figures below come from the dated benchmark reports in the repository. The Q&A suite (last run 2026-11-27/28) has **104 questions**, including 79 answerable and 25 unanswerable questions in English, Hindi, and Hinglish. [Full Q&A report and confidence intervals](eval/RESULTS.md)

| System | Retrieval hit rate | Answers naming places outside the data | Answers answerable questions | Declines unanswerable questions |
|---|---:|---:|---:|---:|
| LLM only | — | 73% | 100% | 8% |
| Plain RAG | 86% | 3% | 66% | 100% |
| Self-RAG | 95% | 1% | 99% | 100% |

- **Planner validation.** All 30 scenarios reached review and passed the applicable plan checks (2026-11-27). The first draft passed the Critic in 93% of scenarios. Disabling the Critic let two errors through, an unknown place and a meal in the wrong town. [Plan report](eval/PLANS.md) · [Ablations](eval/ABLATIONS.md)
- **Circuit discovery.** On 15 open requests that name no town, the first circuit offered included a hand-labelled fitting town in 15 of 15, for both the town-search flow and the curated rule list; town search costs about twice the LLM calls. [Discovery report](eval/DISCOVERY.md)
- **Time and cost.** Median time to itinerary review was **19 seconds** (4 LLM calls), and median estimated LLM fees were **₹0.02**. These measurements cover the planner up to review. Optional hotel research and external provider charges have separate costs. [Plan report](eval/PLANS.md)
- **Judge reliability.** A checklist jury uses three model families, repeated votes, and cached verdicts. On 30 answers judged five times by five judge designs (one free-form call up to the three-model jury), the jury's headline verdicts changed on 0–3% of answers against up to 7% for a single free-form call, and two judges left 5% of item verdicts tied. The judges agree on concrete and declines (Fleiss' kappa 1.00) but not on on_topic (0.21), which is where verdicts still flip. [Judge reliability](eval/RELIABILITY.md)
- **Concierge and safeguards.** In the recorded hotel benchmark, 92% of proposed claims passed the quote check. In three consecutive runs of the 13-attack adversarial suite (2026-11-28), all 13 attacks were defended each time; code guards withhold answers that repeat a system prompt and strip text that poses as source data. [Hotel research](eval/CONCIERGE.md) · [Adversarial evaluation](eval/REDTEAM.md)
- **Circuit personalization.** In two controlled API regressions, feedback on a saved Haridwar–Rishikesh trip changes the order of new routes around Mussoorie and Almora using the bundled road data. The tests check that another traveller gets the baseline order and that removing feedback restores it. [Ranking tests](tests/test_api.py)

GitHub Actions runs Python tests with PostgreSQL, frontend builds, a Docker build, and live evaluation gates when the required provider secrets are available. [Evaluation commands](eval/README.md) · [CI workflow](.github/workflows/ci.yml)

## Run locally

Use Python 3.11 or newer and Node.js. For live planning, have a Neo4j database, a Pinecone index, and a DeepInfra key or compatible model provider. AuraDB Free can host the project’s travel graph. An idle Free instance may need to be resumed in the Aura console. If Neo4j is unavailable at startup, the API uses a bundled snapshot for guest planning and Q&A. Account sign-in requires the live graph.

### Set up the backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
test -f .env || cp .env.example .env
```

| Set in `.env` | Purpose |
|---|---|
| `SECRET_KEY` | Private key used to sign account and guest tokens. |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | URI and database credentials for the same Neo4j instance. Use `NEO4J_DATABASE=neo4j` for the default Aura database. |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME` | Vector search credentials and index. The default embedding model uses 1,024 dimensions. |
| `DEEPINFRA_API_KEY` | Model and embedding calls with the default provider configuration. |
| `DATABASE_URL` | Optional PostgreSQL URL for trips, profiles, checkpoints, and memory. Local development defaults to SQLite. |
| `GOOGLE_PLACES_API_KEY`, `TAVILY_API_KEY` | Optional hotel reviews and current travel notes. Review lookups can incur provider charges. |

### Load the knowledge base

Reuse `data/processed/entities.json` if you already have the generated dataset. A fresh checkout can build it with `python -m ingest.build`.

```bash
python -m ingest.load neo4j --dry-run
python -m ingest.load neo4j
python -m ingest.load pinecone
```

If you are replacing only Neo4j and Pinecone already contains embeddings for the same dataset, run the Neo4j commands and keep the existing index. The loader upserts the travel graph. On a fresh instance, account records from another Neo4j database require a backup restore. [Deployment and recovery](DEPLOY.md)

### Start both services

```bash
# Terminal 1, from the repository root
.venv/bin/python -m uvicorn app.api.asgi:app --reload --port 8000
```

```bash
# Terminal 2, from the repository root
cd frontend
npm ci
npm run dev
```

- [Website](http://localhost:5173) · [API documentation](http://localhost:8000/docs)
- `GET /health` checks whether the API is running. `GET /health/deps` probes the configured graph, vector index, models, trip storage, and weather service. A weather outage is reported as optional.

### Run checks

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
npm --prefix frontend run build
```

Set `TEST_DATABASE_URL` to a dedicated UTF-8 test database to include PostgreSQL storage and restart tests. The live evaluation commands use the configured model and retrieval providers. [Evaluation instructions](eval/README.md)

## Repository map

| Path | What to look for |
|---|---|
| [`frontend/`](frontend/) | React interface, Leaflet, planner trace, saved trips, and PWA assets |
| [`app/api/`](app/api/) | FastAPI, guest sessions, rate limits, ownership checks, and streaming |
| [`app/graph/`](app/graph/) | LangGraph workflow, specialists, Critic, hotel research, and timelines |
| [`app/rag/`](app/rag/) | Vector search, graph enrichment, and Self-RAG |
| [`app/rules/`](app/rules/) and [`app/cost/`](app/cost/) | Deterministic altitude, season, advisory, and budget rules |
| [`ingest/`](ingest/) | Source collection, geocoding, provenance, graph and vector loaders |
| [`mcp_server/`](mcp_server/) | Travel tools and MCP transports |
| [`eval/`](eval/) and [`tests/`](tests/) | Benchmarks, quality gates, and automated regressions |

[Portfolio notes and walkthrough](docs/PORTFOLIO.md) · [Engineering write-up](docs/blog-draft.md) · [Deployment guide](DEPLOY.md)

## Data and attribution

Listings draw on Wikivoyage (CC BY-SA 4.0) and OpenStreetMap contributors (ODbL). Weather uses Open-Meteo with a MET Norway fallback. The source pipeline stores attribution, and the landing page includes credits for its town photography.

TravelBuddy is a planning aid. Confirm departure times, fares, opening hours, permits, and current travel advisories with the relevant operators.
