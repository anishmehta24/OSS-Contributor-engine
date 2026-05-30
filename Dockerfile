# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Backend image — FastAPI (uv-managed) for Render / Fly / any Docker host.
#
# Free-tier sizing (Render 512 MB RAM): we deliberately EXCLUDE the
# `local-embeddings` extra so torch + sentence-transformers (~2 GB) never
# land in the image. Set EMBEDDER_BACKEND=voyage at runtime — VoyageClient
# is wired and uses Voyage's hosted API for embeddings.
#
# Pilot sandbox: not used in this image. The deployed app sets
# PILOT_ENABLED=false because free PaaS doesn't expose a Docker daemon
# (and you can't nest privileged Docker inside a Render container).
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# git: needed by the investigation pipeline for repo intelligence (NOT the
# pilot sandbox, which is disabled in this image). curl: healthcheck.
# build-essential + libpq-dev: a few transitive wheels (e.g. uvloop on some
# musl/glibc combos) fall back to a source build, and psycopg sometimes
# wants libpq headers even with the binary wheel. Cheap insurance — the
# packages add ~150 MB to the build layer but nothing to the runtime layer
# we ship (the venv is what matters).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git ca-certificates curl \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy ONLY the lock + project metadata first so this layer caches across
# code edits — Docker only rebuilds the deps layer when these two files
# change, not on every Python edit.
COPY pyproject.toml uv.lock ./

# --no-dev: skip pytest/ruff/respx. NO --extra local-embeddings: skip torch.
RUN uv sync --frozen --no-dev

# App code
COPY app ./app

# Render injects $PORT; default to 8000 for local `docker run` parity.
ENV PORT=8000
EXPOSE 8000

# Healthcheck → /health (Render uses its own; this is for `docker run` use)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/health || exit 1

# Shell form so $PORT expands. One worker on free tier (512 MB RAM).
CMD uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
