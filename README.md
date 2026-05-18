# OSS Contributor Engine

Multi-agent system that profiles your skills from your GitHub history, hunts open-source issues that match, and drafts a contribution plan for each match.

> Status: **Batch 1 — scaffold.** Not functional yet. See `docs/PLAN.md` (TBD) for batch roadmap.

## Stack (Batch 1)

- Python 3.12 (managed by `uv`)
- SQLite + `sqlite-vec` (vector search, no DB server needed)
- LiteLLM Router (Gemini primary → Groq fallback)
- Pydantic Settings, structlog, pytest, ruff

External services (free tiers): GitHub API, Google AI Studio (Gemini), Groq, Voyage AI.

## Setup

```powershell
# 1. Install uv if you haven't:
#    winget install astral-sh.uv
#    (then restart terminal)

# 2. Install Python 3.12 + sync deps
uv python install 3.12
.\run.ps1 install

# 3. Copy .env.example to .env, paste your real keys
copy .env.example .env
notepad .env
```

Required keys (free tier signups):
- `GITHUB_TOKEN` — https://github.com/settings/personal-access-tokens (fine-grained, public-read)
- `GEMINI_API_KEY` — https://aistudio.google.com/apikey
- `GROQ_API_KEY` — https://console.groq.com/keys
- `VOYAGE_API_KEY` — https://www.voyageai.com (used in Batch 5)

## Verify the scaffold

```powershell
.\run.ps1 test         # pytest passes
.\run.ps1 lint         # ruff passes
.\run.ps1 smoke-gh     # GitHub API works
.\run.ps1 smoke-db     # SQLite + sqlite-vec works
.\run.ps1 smoke-llm    # LiteLLM router works (needs Gemini and/or Groq key)
.\run.ps1 smoke        # all of the above
```

If all five green, Batch 1 is done.

## Layout

```
proj1/
├── .env.example           # template — copy to .env
├── .python-version        # 3.12
├── pyproject.toml         # deps + ruff/pytest config
├── run.ps1                # task runner (Windows)
├── app/
│   ├── core/
│   │   ├── config.py      # Pydantic settings (singleton)
│   │   └── logging.py     # structlog setup
├── scripts/
│   ├── hello_github.py    # smoke: GitHub API
│   ├── hello_db.py        # smoke: SQLite + sqlite-vec
│   └── hello_llm.py       # smoke: LiteLLM router
└── tests/
    └── test_smoke.py      # sanity tests for config + logging
```

## Tasks

```
.\run.ps1 install       Install/sync deps into .venv
.\run.ps1 test          Run pytest
.\run.ps1 lint          ruff check
.\run.ps1 fmt           ruff format
.\run.ps1 smoke         Run all 3 smoke scripts
.\run.ps1 smoke-gh      GitHub smoke only
.\run.ps1 smoke-db      DB smoke only
.\run.ps1 smoke-llm     LLM smoke only
.\run.ps1 clean         Wipe caches and .venv
```
