# OSS Contributor Engine

A multi-agent system that **profiles your GitHub skills, hunts matching open-source issues, investigates them end-to-end, drafts a contribution comment — and can autonomously write the fix and open the pull request for you.**

Built batch-by-batch as a portfolio project. Specialist agents collaborate across two phases: **discovery** — Skill Profiler → Issue Hunter → Triager → Investigator (a crew of four sub-agents) → Pitch Writer — and **contribution** — the **Autonomous Pilot** (Code Explorer → Patch Writer → Test Runner → Reviewer) which patches the code in a Docker sandbox and opens a PR. A **Direct Pilot** entry point lets you skip discovery and point the pilot straight at any GitHub issue URL.

## Stack

**Backend** (`app/`)
- Python 3.12 (managed by [`uv`](https://docs.astral.sh/uv/))
- FastAPI + SQLAlchemy (sync) + SQLite with [`sqlite-vec`](https://github.com/asg017/sqlite-vec) for vector search
- [LiteLLM Router](https://github.com/BerriAI/litellm) — 3-tier provider fallback (Gemini 2.5 Flash → Groq Llama 3.3 70B → Groq Llama 3.1 8B Instant)
- Local embeddings via `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim)
- GitHub OAuth (signed httpOnly cookies via `itsdangerous`; tokens encrypted at rest with Fernet)
- Server-Sent Events for live agent progress

**Frontend** (`web/`)
- Next.js 16 (App Router, Turbopack, RSC + streaming Suspense)
- TypeScript + Tailwind v4 + shadcn/ui (base-nova preset on `@base-ui/react`)
- `next-themes` for dark mode (default), `sonner` for toasts, `react-markdown` + `remark-gfm` for report rendering
- All API calls proxied via Next rewrites → same-origin httpOnly cookies, no CORS gymnastics

## Run it locally

```powershell
# 1. Install uv (one-time, then restart terminal):
winget install astral-sh.uv

# 2. Install Node 20+ if you haven't (one-time):
#    https://nodejs.org/

# 3. Backend deps
uv python install 3.12
.\run.ps1 install

# 4. Frontend deps
cd web ; npm install ; cd ..

# 5. Config
copy .env.example .env
notepad .env   # paste real keys (see "Required keys" below)
```

### Required keys

All free tier — sign up takes a couple of minutes each.

| Key | Where | Why |
|---|---|---|
| `GITHUB_TOKEN` | [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens) (fine-grained, public-read) | Used by background workers — Issue Hunter, GSoC scraper |
| `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET` | [github.com/settings/developers](https://github.com/settings/developers) → New OAuth App. Callback URL: `http://localhost:8000/auth/callback` | Sign-in flow |
| `SESSION_SECRET` | `uv run python scripts/gen_session_secret.py` | Signs the session cookie; Fernet-encodes OAuth tokens at rest |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Primary LLM (free tier: 1500 RPD) |
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | Fallback LLM (separate quota bucket) |

### Bring up the system

Three terminals:

```powershell
# Terminal 1 — FastAPI backend on :8000
# --reload-dir app keeps the reload watcher off .sandbox/ (the pilot clones
# hundreds of files there; without this the watcher SIGINTs git mid-clone).
uv run uvicorn app.main:app --reload --reload-dir app

# Terminal 2 — Next.js frontend on :3000
cd web ; npm run dev

# Terminal 3 — initial data
uv run python -m app.db init               # create tables
uv run python -m app.db seed-gsoc          # load 30 bundled GSoC orgs
uv run python -m app.workers hunt --max 50 # populate ~50 candidate issues
```

Then open `http://localhost:3000` → click **Sign in with GitHub** → land on `/dashboard`.

## What it does, in one demo flow

1. **Sign in** with GitHub → OAuth callback sets an encrypted session cookie under the Next.js origin.
2. Land on `/dashboard` — empty profile / matches / investigations / cost cards.
3. Go to `/profile` → click **Profile me** → the **Skill Profiler** agent reads your top ~12 repos, extracts languages and frameworks from manifests, asks an LLM to infer domains + experience level + write a 2-3 sentence summary. (~30-90s)
4. Go to `/matches` → ranked candidate issues from the Hunter pool. Toggle **🎓 GSoC** to restrict to orgs that have shipped GSoC projects in the last 3 years. Each card shows a score breakdown (skill / health / freshness / difficulty / impact) and a `why-it-fits` line.
5. Click **Investigate** on any match → routes to `/investigations/<id>` with a **live SSE timeline**: data fetch → Issue Analyst → Repo Mapper → History Detective → Synthesizer.
6. When the run completes, the **markdown report** and a **per-agent cost table** appear inline. Click **Draft pitch** → the Pitch Writer agent produces a tone-guarded comment you can copy-paste straight into the GitHub issue.
7. Click **Start Autonomous Pilot** → the Pilot Coordinator clones the repo into a Docker sandbox, the **Code Explorer** picks candidate files, and a **Reviewer loop** runs **Patch Writer → Test Runner** (up to N attempts). You review the resulting diff, then **Push** and **Open PR** — all on your own GitHub token.

### Direct Pilot — skip straight to the fix

Don't want to run the whole discovery pipeline? Open the **Direct Pilot** tab (`/direct-pilot`), paste a GitHub issue URL (`https://github.com/owner/repo/issues/123`, `owner/repo/issues/123`, or `owner/repo#123`), and hit **Start pilot**. It fetches the issue + repo, runs the same patch → review → push → PR flow, and opens a pull request. Handy for demos and for targeting a specific issue you already have in mind.

> Notes: the Pilot needs Docker (run locally — it's disabled on free hosted tiers). The Test Runner runs real tests for **Python** projects; for **JS/TS/Go/Rust** it accepts the applied patch with a "tests not run — review the diff" caveat so the flow still reaches a PR.

## Architecture cheat-sheet

```
                   ┌──────────────────┐
                   │   Skill Profiler │  reads top repos, infers profile
                   └────────┬─────────┘
                            │
                   ┌────────▼─────────┐
                   │   Issue Hunter   │  cross-GitHub search (general
                   │   (background)   │  mode) OR gsoc_orgs scoped (gsoc mode)
                   └────────┬─────────┘
                            │ populates issues_vec
                            │
                   ┌────────▼─────────┐
        user───────►     Triager      │  vector search + 5-component score
                   └────────┬─────────┘
                            │ /matches
                            │
                   ┌────────▼─────────┐
                   │   Investigator   │ ┌──────────────┐
                   │ (orchestrator)   │ │ Issue Analyst│
                   │                  │ │ Repo Mapper  │
                   │                  │ │ History Det. │
                   │                  │ │ Synthesizer  │
                   │                  │ └──────────────┘
                   └────────┬─────────┘
                            │ markdown_report → investigation completed
                 ┌──────────┴───────────┐
                 │                      │
        ┌────────▼─────────┐   ┌────────▼──────────┐
        │   Pitch Writer   │   │  Autonomous Pilot │ ◄─ Direct Pilot: paste a
        │  draft comment   │   │  (Docker sandbox) │    GitHub issue URL and
        └──────────────────┘   └────────┬──────────┘    skip straight to here
                                        │ shallow-clones the repo
                               ┌────────▼──────────┐
                               │   Code Explorer   │  picks candidate files
                               └────────┬──────────┘
                                        │
                               ┌────────▼──────────┐   ┌──────────────┐
                               │   Reviewer loop   │──▶│ Patch Writer │
                               │  ×N: accept /     │◀──│ Test Runner  │
                               │  retry / give_up  │   └──────────────┘
                               └────────┬──────────┘
                                        │ accepted diff (human reviews it)
                               ┌────────▼──────────┐
                               │   Push → Open PR  │  fork, push a branch,
                               │  (user's token)   │  open the pull request
                               └───────────────────┘
```

**Two entry points into the Pilot:** the normal flow reaches it from a
**completed investigation**; **Direct Pilot** (`/direct-pilot`) lets you paste a
GitHub issue URL and run the pilot straight away, skipping hunt → match →
investigate. Both share the same review → push → PR machinery.

## CLI reference

```powershell
# Backend tasks (via run.ps1)
.\run.ps1 install              # uv sync
.\run.ps1 test                 # pytest
.\run.ps1 lint                 # ruff check
.\run.ps1 fmt                  # ruff format

# Database
uv run python -m app.db init           # create tables (idempotent)
uv run python -m app.db reset --yes    # DROP everything + recreate
uv run python -m app.db counts         # row counts per table

# GSoC org data
uv run python -m app.db seed-gsoc      # load bundled 30-org JSON
uv run python -m app.db scrape-gsoc    # scrape current + past 3 years
uv run python -m app.db scrape-gsoc --year 2025 --dry-run

# Issue Hunter
uv run python -m app.workers hunt                              # general mode
uv run python -m app.workers hunt --mode gsoc --languages python
uv run python -m app.workers hunt --max 30                     # cap total issues
```

## Repo layout

```
proj1/
├── app/                   FastAPI backend, all agents, DB, telemetry
│   ├── api/               HTTP routes + dependencies
│   ├── auth/              OAuth + sessions + Fernet token encryption
│   ├── agents/            5 agents + sub-agents (profile, hunter, triager,
│   │                      investigator, pitch)
│   ├── db/                models, vec tables, CLI (`python -m app.db ...`)
│   ├── gsoc/              GSoC org seed loader + scraper + queries
│   ├── llm/               LiteLLM router + 3-tier fallback
│   ├── tools/             GitHub client, embedder factory
│   └── workers/           background hunt worker
├── web/                   Next.js 16 frontend
│   ├── src/app/           App Router pages (marketing + authed app)
│   ├── src/components/    UI components (shadcn ui/, page-specific)
│   ├── src/lib/api/       server + client FastAPI wrappers + TS types
│   └── src/proxy.ts       auth guard (Next 16's renamed middleware)
├── tests/                 Python test suite (~340 tests)
├── scripts/               smoke scripts + helpers
└── docs/                  (TBD — internal plans live here)
```

## v3 — Autonomous Contribution Pilot (built)

The engine no longer stops at "draft a comment" — the **Autonomous Contribution Pilot** takes it through **submitting the contribution**: it forks the repo, writes a patch in a sandboxed Docker workspace, runs the project's test suite against it, and opens a PR via the user's OAuth token. Agents: Code Explorer, Patch Writer, Test Runner, Reviewer, plus the push/PR steps. There's a human-in-the-loop review of the diff before any PR is opened. A **Direct Pilot** entry point (`/direct-pilot`) runs the whole thing from a pasted issue URL.

### v3 setup (additional)

The autonomous pilot needs a Docker-based sandbox to run untrusted target-repo
code (their test suites, build steps, etc.). Install [Docker Desktop](https://www.docker.com/products/docker-desktop/),
then build the sandbox image once:

```powershell
uv run python -m app.sandbox build         # ~3 min on first build
uv run python -m app.sandbox info          # check status
uv run python scripts/sandbox_smoke.py     # end-to-end smoke
```

The sandbox runs with `--network=none`, `--read-only`, capped memory + CPU,
and a non-root user. Per-investigation workspaces are scratch dirs under
`.sandbox/` (gitignored); each is created fresh and removed on completion.

## License

MIT — see `LICENSE`.
