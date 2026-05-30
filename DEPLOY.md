# Deploying OSS Contributor Engine to free tiers

Target stack: **Vercel** (web) + **Render** (API) + **Neon** (Postgres+pgvector) + **Voyage** (embeddings). All free.

> **The Pilot is disabled in the hosted demo.** It needs a Docker daemon + persistent disk that no free PaaS provides. The deployed app still showcases profiling, matching, and the multi-agent investigation; the Pilot stays a "run locally" feature. See [Why the Pilot is off](#why-the-pilot-is-off) at the end.

---

## Prerequisites — 5 free accounts

1. **GitHub** (you already have this)
2. **Neon** — [neon.tech](https://neon.tech) — Postgres
3. **Voyage AI** — [voyageai.com](https://www.voyageai.com) — embeddings
4. **Render** — [render.com](https://render.com) — API hosting
5. **Vercel** — [vercel.com](https://vercel.com) — frontend hosting

Plus API keys you should already have for local dev: **Gemini** (`aistudio.google.com/apikey`) and **Groq** (`console.groq.com/keys`).

---

## Step 1 — Neon Postgres + pgvector

1. Neon dashboard → **New Project** → pick the region closest to where Render will live.
2. Once created, open the **SQL Editor** (left nav) and run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Click **Connection Details** → copy the connection string. It looks like:
   ```
   postgresql://USER:PASS@ep-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
   ```
   Save it — that's your `DATABASE_URL`. (The app auto-rewrites it to the `postgresql+psycopg://` form psycopg needs.)

That's it for the DB. `init_db()` at API startup creates every table + the `*_vec` tables with `vector(384)` columns automatically.

---

## Step 2 — Voyage API key

1. Voyage dashboard → **API Keys** → **Create** → copy.
2. Save it as `VOYAGE_API_KEY`.

The hosted image sets `EMBEDDER_BACKEND=voyage`, so this is what produces every embedding. Voyage's free tier is generous enough for a portfolio demo.

---

## Step 3 — GitHub OAuth app

[github.com/settings/developers](https://github.com/settings/developers) → **New OAuth App**.

You don't have your Render/Vercel URLs yet, so fill placeholders for now and edit after Steps 4 and 5:

- **Application name** — `OSS Contributor Engine`
- **Homepage URL** — `https://placeholder.vercel.app` (edit after Step 5)
- **Authorization callback URL** — `https://placeholder.onrender.com/auth/callback` (edit after Step 4)

Click **Register**, then **Generate a new client secret**. Copy both `Client ID` and `Client secret` somewhere safe — you'll paste them into Render.

---

## Step 4 — Render API service

Render reads [`render.yaml`](./render.yaml) in this repo as a Blueprint.

1. Render dashboard → **New** → **Blueprint** → connect your GitHub fork of this repo.
2. Render auto-detects `render.yaml`, names the service **oss-engine-api**, and starts the first build (from the [`Dockerfile`](./Dockerfile) at repo root).
3. While it builds (~3 min the first time), click into the service → **Environment** → fill the secrets:

   | Variable | Value |
   |---|---|
   | `DATABASE_URL` | The Neon connection string from Step 1 |
   | `SESSION_SECRET` | A new Fernet key — see the snippet below |
   | `GITHUB_OAUTH_CLIENT_ID` | From Step 3 |
   | `GITHUB_OAUTH_CLIENT_SECRET` | From Step 3 |
   | `OAUTH_REDIRECT_URI` | `https://<your-render-url>/auth/callback` (you'll see the URL in the dashboard) |
   | `OAUTH_POST_LOGIN_REDIRECT` | placeholder for now — set after Step 5 |
   | `VOYAGE_API_KEY` | From Step 2 |
   | `GEMINI_API_KEY` | Your Gemini key |
   | `GROQ_API_KEY` | Your Groq key |
   | `GITHUB_TOKEN` | Optional fine-grained PAT for server-side reads |

   Generate `SESSION_SECRET`:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

4. Once env vars are saved, trigger a redeploy (Render usually does this automatically). Watch the logs for `app_started github=true embedder=true llm=true`.
5. Smoke-test:
   ```bash
   curl https://<your-render-url>/health
   curl https://<your-render-url>/features   # should report pilot_enabled: false
   ```
6. Go back to the GitHub OAuth app (Step 3) and update **Authorization callback URL** to the real `https://<your-render-url>/auth/callback`.

---

## Step 5 — Vercel frontend

1. Vercel dashboard → **Add New** → **Project** → import your repo.
2. **Configure Project:**
   - **Root Directory:** `web`  ← critical
   - **Framework Preset:** Next.js (auto-detected)
   - Build / install commands: leave defaults
3. **Environment Variables** — add one:
   - `FASTAPI_URL` = `https://<your-render-url>`
4. **Deploy.** First build ≈ 90 s.
5. Copy the assigned `<your-app>.vercel.app` URL.
6. Go back to GitHub OAuth (Step 3) and set **Homepage URL** to it.
7. Go back to Render env (Step 4) and set:
   - `OAUTH_POST_LOGIN_REDIRECT` = `https://<your-app>.vercel.app/auth/handoff`
   Render will auto-redeploy.

---

## Step 6 — Smoke test the full flow

1. Open `https://<your-app>.vercel.app`.
2. Click **Sign in with GitHub** → consent → you should land back on the dashboard with your handle in the navbar.
3. The dashboard fetches your profile, runs matching, and renders the investigation page. The Pilot panel on an investigation should show the **"Autonomous Pilot — disabled in this deployment"** card.

If sign-in 404s on `/auth/callback`, the OAuth callback URL doesn't match `OAUTH_REDIRECT_URI` — recheck both ends of Step 3 + Step 4.

---

## Step 7 (optional) — keep Render warm

Render free spins down after 15 min idle; the cold start is ~50 s and SSR fetches from Vercel will look hung during it.

Free fix: at [cron-job.org](https://cron-job.org), create a job that GETs `https://<your-render-url>/health` every 14 minutes. Costs nothing, keeps the API warm during your demo windows.

---

## What got changed for this to work

- [`pyproject.toml`](./pyproject.toml) — `sentence-transformers` moved to an optional `local-embeddings` extra (so the hosted image stays under 512 MB RAM). `pgvector` + `psycopg[binary]` added as base deps.
- [`app/db/session.py`](./app/db/session.py) — dialect-aware: loads sqlite-vec only on SQLite, runs `CREATE EXTENSION vector` + parallel pgvector DDL on Postgres.
- [`app/db/vector.py`](./app/db/vector.py) — dispatches on `session.bind.dialect.name`: `MATCH` blob path for SQLite, `<=>` cosine operator for Postgres.
- [`app/core/config.py`](./app/core/config.py) + [`app/api/routes/pilot.py`](./app/api/routes/pilot.py) + [`app/api/routes/health.py`](./app/api/routes/health.py) — `PILOT_ENABLED` flag, route guard returns 503 when off, `/features` endpoint exposes it.
- [`web/src/components/investigations/pilot-panel.tsx`](./web/src/components/investigations/pilot-panel.tsx) + [`pilot-disabled.tsx`](./web/src/components/investigations/pilot-disabled.tsx) — server-side flag check, renders disabled card when off.
- [`Dockerfile`](./Dockerfile), [`.dockerignore`](./.dockerignore), [`render.yaml`](./render.yaml) — deploy artifacts.

Local dev keeps working unchanged: SQLite + sqlite-vec + local sentence-transformers, with the Pilot fully enabled.

---

## Why the Pilot is off

The Autonomous Pilot:
- Spawns a Docker container (`--network=none --read-only --user sandbox`) and runs untrusted repo test suites inside it
- `git clone`s arbitrary public repos to a persistent workspace dir
- Holds a multi-minute background asyncio task per run

Each one breaks on free PaaS:

| Need | Vercel | Render free | Fly.io free |
|---|---|---|---|
| Docker daemon to spawn containers | ✗ (serverless) | ✗ (you ARE a container) | ✗ (no `--privileged`) |
| Persistent disk for git clones | ✗ | ✗ ephemeral | ✗ ephemeral |
| Long background tasks survive | ✗ (10 s timeout) | ✗ (spin-down kills) | ⚠ (auto-stop) |

To deploy with a working Pilot: rent a $5/mo VPS (DigitalOcean / Hetzner), `git clone`, `docker compose up`, point Vercel at it. Out of scope for free.

---

## Cost recap (monthly)

| Service | Tier | Cost |
|---|---|---|
| Vercel Hobby | Free | $0 |
| Render Web Service | Free (512 MB, spins down) | $0 |
| Neon Postgres | Free (3 GB, always-on) | $0 |
| Voyage AI | Free tier (50M tokens) | $0 |
| Gemini API | Free tier | $0 |
| Groq API | Free tier | $0 |
| **Total** | | **$0** |
