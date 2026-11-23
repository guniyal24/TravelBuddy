# Deploying TravelBuddy

Three free services: **Neon** (Postgres), **Render** (API, Docker), **Vercel** (frontend).
About 20 minutes. You need the same keys as your local `.env` (DeepInfra, Pinecone, Neo4j).

```
Browser ──> Vercel (React app) ──> Render (FastAPI + LangGraph) ──> Neon Postgres
                                          ├──> Neo4j Aura, Pinecone (knowledge base)
                                          └──> DeepInfra (LLM + embeddings)
```

## 1. Database: Neon

1. Create a free project at neon.tech (region: closest to your Render region, e.g. Singapore
   or Frankfurt).
2. On the project dashboard, copy the **direct** connection string (turn *Connection pooling*
   off; the app keeps its own small pool). It looks like
   `postgresql://user:password@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require`.

Tables are created automatically on the API's first start.

## 2. API: Render

1. render.com → **New → Blueprint** → connect `guniyal24/TravelBuddy`. Render reads
   `render.yaml` and creates the `travelbuddy-api` service.
2. Fill in the secrets it asks for:

   | Key | Value |
   |---|---|
   | `DATABASE_URL` | the Neon string from step 1 |
   | `DEEPINFRA_API_KEY`, `PINECONE_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | same as your `.env` |
   | `CORS_ORIGINS` | leave as `http://localhost:5173` for now; set in step 4 |
   | `GOOGLE_PLACES_API_KEY` | optional: hotel reviews in the Concierge step (billable, capped by `PLACES_DAILY_CAP`) |
   | `TAVILY_API_KEY` | optional: live travel notes (free tier at tavily.com) |

3. Deploy, then open `https://<your-service>.onrender.com/health`. It should return
   `{"status":"ok"}`.

The free plan sleeps when idle; the first request after a sleep takes up to a minute. The
frontend shows a "waking up the server" notice while that happens.

## 3. Frontend: Vercel

1. vercel.com → **Add New → Project** → import `guniyal24/TravelBuddy`.
2. **Root Directory:** `frontend`. Framework preset: **Vite** (build `npm run build`, output
   `dist`).
3. Environment variable: `VITE_API_URL` = your Render URL, e.g.
   `https://travelbuddy-api.onrender.com` (no trailing slash).
4. Deploy and note the URL, e.g. `https://travelbuddy.vercel.app`.

## 4. Connect them

In Render → service → **Environment**, set `CORS_ORIGINS` to the Vercel URL (comma-separate
several, e.g. a custom domain too) and save. Render redeploys.

## 5. Smoke test

- [ ] Open the Vercel URL → **Try it now, no sign-up**.
- [ ] Plan "3 days in Rishikesh for 2 people in March": the live agent trace appears, a
      circuit choice, then the plan for review.
- [ ] Approve: the booking checklist appears; **My trips** lists it.
- [ ] Redeploy the API from Render, reload the page: the trip is still in **My trips**
      (it is in Postgres, not on the wiped disk).
- [ ] **Ask** tab: "Where can I do yoga in Rishikesh?" answers with real places.

Then put the URL in the README's *Live demo* line.

## 6. Optional: deploy from CI

The `deploy` job in `.github/workflows/ci.yml` calls a Render deploy hook after tests, the Docker
build and the eval gate pass on `main`.

1. Render → service → **Settings → Deploy Hook** → copy the URL.
2. GitHub → repo → **Settings → Secrets and variables → Actions**, add:
   - `RENDER_DEPLOY_HOOK_URL`
   - for the eval gate: `DEEPINFRA_API_KEY`, `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`,
     `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
3. Turn off Render's own auto-deploy so only CI-approved commits ship.

## Cost guards

- Set a monthly spend limit in your DeepInfra account.
- Guest mode is capped per IP (`GUEST_SESSIONS_PER_IP_PER_HOUR`) and globally
  (`GUEST_SESSIONS_PER_DAY`, default 300). Set `GUEST_ENABLED=false` to turn it off.
- Neon, Render and Vercel free tiers are enough for a portfolio demo.

## Replace an expired Neo4j Aura trial

1. Open the [Aura console](https://console.neo4j.io/) and create an **AuraDB Free** instance or
   resume an existing one. Save its database credentials when Neo4j offers the download.
2. If you need the old account records, check the suspended instance for an exportable snapshot.
   Restore it into an empty instance before importing. The TravelBuddy importer loads places and
   relationships. Account records and chat logs are stored separately in Neo4j.
3. Set the new `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD` in your local `.env`. Run
   `python -m ingest.load neo4j --dry-run`, then `python -m ingest.load neo4j` to load the existing
   `data/processed/entities.json`. If the Pinecone index already contains vectors for that
   dataset, keep using it.
4. Update the same Neo4j settings in Render and in GitHub Actions secrets if you use the live
   eval job. Redeploy the API, then check `/health/deps` and complete a guest itinerary.

AuraDB Free can pause after 72 hours of inactivity. Resume it in the console before a demo if
the status shows **Paused**. [Neo4j instance actions](https://neo4j.com/docs/aura/managing-instances/instance-actions/)

### Guest planning during an Aura outage

The API image bundles an attributed listing snapshot. If Aura is unreachable or rejects the
database login at startup, guest planning and Q&A can use this snapshot with the configured
Pinecone index and model provider. In `/health/deps`, `graph.mode` reports `snapshot` and
`graph.accounts_available` is false. Restart the API after restoring Aura credentials to return
to the live graph.

After refreshing the live dataset, run `python -m ingest.snapshot` to update the bundled copy.
The snapshot retains source URLs and excludes Google-sourced coordinates and their derived
distances. The Render Free API can still cold start after an idle period.
