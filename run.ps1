# PowerShell task runner (replaces Makefile on Windows).
# Usage:  .\run.ps1 <task>
#
# Tasks:
#   install       - install all deps (incl. dev) into .venv via uv
#   test          - run pytest
#   lint          - run ruff check
#   fmt           - run ruff format
#   smoke         - run all hello_*.py smoke tests
#   smoke-gh      - GitHub API smoke
#   smoke-db      - SQLite + sqlite-vec smoke
#   smoke-llm     - LiteLLM router smoke
#   db-init       - create tables + vec0 virtual tables (idempotent)
#   db-reset      - DROP everything and recreate (destructive; use --yes)
#   db-tables     - list tables in the DB
#   db-counts     - row counts per table
#   profile       - profile a GitHub user; -Login <name> [-NoPersist] [-Pretty]
#   hunt          - run the Issue Hunter; [-Languages py,go] [-Max 50]
#   rank          - rank issues for a user; -Login <name> [-Top 10] [-Difficulty any|easy|medium|hard] [-NoExplain] [-Pretty]
#   serve         - run the FastAPI server with --reload on port 8000
#   ui            - run the Streamlit UI (talks to http://localhost:8000)
#   investigate   - run the Investigator crew; -Login <name> -Repo <owner/name> -IssueNumber <n> [-Markdown]
#   pitch         - draft a comment from a completed investigation; -InvestigationId <uuid> [-Markdown]
#   clean         - remove caches and .venv

param(
    [Parameter(Mandatory=$true)][string]$Task,
    [switch]$Yes,
    [string]$Login,
    [switch]$NoPersist,
    [switch]$Pretty,
    [string]$Languages,
    [int]$Max = 50,
    [int]$Top = 10,
    [string]$Difficulty = "any",
    [switch]$NoExplain,
    [string]$Repo,
    [int]$IssueNumber,
    [switch]$Markdown,
    [string]$InvestigationId
)

$ErrorActionPreference = "Stop"

function Invoke-Smoke {
    param([string]$script)
    Write-Host ">>> $script" -ForegroundColor Cyan
    uv run python $script
    if ($LASTEXITCODE -ne 0) { throw "Smoke test failed: $script" }
}

switch ($Task) {
    "install"   { uv sync --extra dev }
    "test"      { uv run pytest }
    "lint"      { uv run ruff check . }
    "fmt"       { uv run ruff format . }
    "smoke-gh"  { Invoke-Smoke "scripts/hello_github.py" }
    "smoke-db"  { Invoke-Smoke "scripts/hello_db.py" }
    "smoke-llm" { Invoke-Smoke "scripts/hello_llm.py" }
    "smoke" {
        Invoke-Smoke "scripts/hello_github.py"
        Invoke-Smoke "scripts/hello_db.py"
        Invoke-Smoke "scripts/hello_llm.py"
    }
    "db-init"   { uv run python -m app.db init }
    "db-reset" {
        if ($Yes) { uv run python -m app.db reset --yes }
        else { uv run python -m app.db reset }
    }
    "db-tables" { uv run python -m app.db tables }
    "db-counts" { uv run python -m app.db counts }
    "profile" {
        if (-not $Login) { Write-Host "Pass -Login <github_username>"; exit 1 }
        $args = @($Login)
        if ($NoPersist) { $args += "--no-persist" }
        if ($Pretty)    { $args += "--pretty" }
        uv run python -m app.agents.profiles @args
    }
    "hunt" {
        $args = @("hunt", "--max", $Max)
        if ($Languages) { $args += @("--languages", $Languages) }
        uv run python -m app.workers @args
    }
    "rank" {
        if (-not $Login) { Write-Host "Pass -Login <github_username>"; exit 1 }
        $args = @("rank", $Login, "--top", $Top, "--difficulty", $Difficulty)
        if ($NoExplain) { $args += "--no-explain" }
        if ($Pretty)    { $args += "--pretty" }
        uv run python -m app.agents.triager @args
    }
    "serve" {
        uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    }
    "ui" {
        uv run streamlit run frontend/app.py
    }
    "investigate" {
        if (-not $Login)       { Write-Host "Pass -Login <github_username>"; exit 1 }
        if (-not $Repo)        { Write-Host "Pass -Repo owner/name"; exit 1 }
        if (-not $IssueNumber) { Write-Host "Pass -IssueNumber <int>"; exit 1 }
        $args = @($Login, $Repo, $IssueNumber)
        if ($Markdown) { $args += "--markdown" }
        uv run python -m app.agents.investigator @args
    }
    "pitch" {
        if (-not $InvestigationId) { Write-Host "Pass -InvestigationId <uuid>"; exit 1 }
        $args = @($InvestigationId)
        if ($Markdown) { $args += "--markdown" }
        uv run python -m app.agents.pitch @args
    }
    "clean" {
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
            .venv, .pytest_cache, .ruff_cache, __pycache__, `
            app/__pycache__, app/core/__pycache__, app/db/__pycache__, `
            app/tools/__pycache__, app/tools/github/__pycache__, `
            tests/__pycache__, scripts/__pycache__, *.db, smoke_test.db
        Write-Host "Cleaned."
    }
    default {
        Write-Host "Unknown task: $Task"
        Write-Host "Available: install, test, lint, fmt, smoke, smoke-gh, smoke-db, smoke-llm,"
        Write-Host "           db-init, db-reset, db-tables, db-counts, profile, hunt, rank,"
        Write-Host "           investigate, pitch, serve, ui, clean"
        exit 1
    }
}
