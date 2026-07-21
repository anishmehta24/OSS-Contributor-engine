# Demo Runbook — Local, full flow through a real PR

Everything below is already set up as of this session. This file is the on-the-day
checklist + how to restart if something stops.

## Current state (verified)
- `.env` fully configured: Gemini + Groq keys, GitHub OAuth app, GITHUB_TOKEN (from `gh`), SESSION_SECRET
- Docker sandbox image built: `oss-engine-sandbox:latest`
- DB seeded: 30 GSoC orgs, 39 repos, 39 issues, 39 issue vectors
- Backend running on **http://localhost:8001**
- Frontend running on **http://localhost:3001**
- `PILOT_ENABLED=true` (full Pilot + real PR available locally)

## Ports (IMPORTANT — not the README's 8000/3000)
- Backend: **8001**
- Frontend: **3001**
- GitHub OAuth App callback MUST be exactly: `http://localhost:8001/auth/callback`

## Start the servers (if not already running)
```powershell
# Terminal 1 — backend
uv run uvicorn app.main:app --reload --reload-dir app --port 8001

# Terminal 2 — frontend
cd web ; npm run dev -- -p 3001
```

## Re-seed data (only if the DB is empty/reset)
```powershell
uv run python -m app.db init
uv run python -m app.db seed-gsoc
uv run python -m app.workers hunt --max 40
# If /matches is empty, embeddings didn't land — backfill:
uv run python scripts/backfill_embeddings.py   # (see note below)
```
> Note: on a cold machine the local embedding model takes ~25s to load the first
> time; if the hunt's embed batch gets cut short, `issues_vec` ends up empty and
> matches return nothing. Backfilling re-embeds all issues in one pass.

## Direct Pilot (demo shortcut — recommended for the PR finale)
A **Direct Pilot** tab (top nav) lets you skip hunt → match → investigate and
point the pilot straight at any issue:

1. Nav → **Direct Pilot**.
2. Paste a GitHub issue URL — `https://github.com/owner/repo/issues/123`,
   `owner/repo/issues/123`, or `owner/repo#123`.
3. **Start pilot** → it fetches the issue+repo, then runs the normal pilot
   (progress → review diff → Push → open PR), reusing the same UI.

Use this to target **your own repo with a small, planted good-first-issue** so
the patch reliably applies. Backend route: `POST /investigations/from-url`.

> Reliability notes:
> - The Patch Writer builds exact search/replace edits, so it succeeds most
>   reliably on a *small, unambiguous* change in a repo you control. On a
>   large/unfamiliar repo it may hallucinate the snippet and the run is rejected
>   — and a failed-to-apply patch currently gives up after 1 attempt (no retry).
>   Keep the demo issue tiny.
> - The Test Runner runs real tests for **Python** projects. For **JS/TS/Go/Rust**
>   it accepts the applied patch with a "tests not run — review the diff" caveat
>   (so verse/other TS repos reach the Push + PR step). Python targets give the
>   fuller "it actually ran the tests" story.

Prepared demo target: **anishmehta24/verse#4** (a real one-line typo fix in
`server/src/responses/index.ts`). Paste
`https://github.com/anishmehta24/verse/issues/4` into Direct Pilot.

## On-camera sequence
1. Open **http://localhost:3001** → **Sign in with GitHub** (consent once).
2. **/profile** → **Profile me** — Skill Profiler reads your repos (~30–90s).
3. **/matches** — ranked issues with score breakdown + why-it-fits.
4. Click **Investigate** on your target → live SSE timeline (Issue Analyst →
   Repo Mapper → History Detective → Synthesizer) → markdown report + cost table.
5. **Draft pitch** → copy-paste-ready comment.
6. **Start Autonomous Pilot** → clones in sandbox, writes patch, runs tests,
   opens the PR → switch to the GitHub tab and show the live PR.

## Live-PR safety (recommended)
- Point the Pilot at **your own repo with a planted good-first-issue**, not a
  random maintainer's project (reliable patch, no spam, re-runnable takes).
- Keep Gemini as router primary (best patch quality); Groq is the fallback.
- Screen-record a full successful run as backup before going live.

## Quick health checks
```powershell
curl http://localhost:8001/health      # {"status":"ok",...}
curl http://localhost:8001/features    # {"pilot_enabled":true}
uv run python -m app.db counts
```
