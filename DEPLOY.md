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
