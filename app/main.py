"""FastAPI app factory + lifespan.

Run with:
    uv run uvicorn app.main:app --reload --port 8000

External resources (GitHub client, embedder, LLM router) are opened once
at startup and closed cleanly at shutdown. Per-request routes pull them
from app.state via dependencies.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.routes import (
    admin,
    auth,
    health,
    investigations,
    matches,
    pilot,
    users,
)
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import init_db
from app.llm.router import build_router
from app.tools.embedder import make_embedder
from app.tools.github import GitHubClient

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("app_starting")

    # Ensure schema exists (idempotent).
    init_db()

    # Reconcile pilots orphaned by the previous shutdown — in-process
    # background tasks don't survive a restart, so anything still queued/
    # running at boot is dead and gets marked failed (else the UI polls it
    # forever).
    from app.db.session import sessionmaker_factory
    from app.pilot import reconcile_orphaned_pilots
    n_orphans = reconcile_orphaned_pilots(sessionmaker_factory())
    if n_orphans:
        log.warning("reconciled_orphaned_pilots_at_startup", count=n_orphans)

    # GitHub client (only if configured)
    app.state.github = (
        GitHubClient(token=settings.github_token) if settings.has_github else None
    )
    if app.state.github is None:
        log.warning("github_not_configured")

    # Embedder — backend chosen via EMBEDDER_BACKEND env var (local | voyage)
    if settings.embedder_ready:
        try:
            app.state.embedder = make_embedder()
            # Keep `voyage` as a back-compat alias so existing dependencies
            # that still reference app.state.voyage keep working.
            app.state.voyage = app.state.embedder
            log.info("embedder_ready", backend=settings.embedder_backend)
        except Exception as e:
            log.warning("embedder_build_failed", error=str(e))
            app.state.embedder = None
            app.state.voyage = None
    else:
        app.state.embedder = None
        app.state.voyage = None
        log.warning("embedder_not_configured", backend=settings.embedder_backend)

    # LLM router
    if settings.has_any_llm:
        try:
            app.state.llm_router = build_router()
        except Exception as e:
            log.warning("llm_router_build_failed", error=str(e))
            app.state.llm_router = None
    else:
        app.state.llm_router = None
        log.warning("llm_not_configured")

    log.info(
        "app_started",
        github=app.state.github is not None,
        embedder=app.state.embedder is not None,
        llm=app.state.llm_router is not None,
    )
    try:
        yield
    finally:
        log.info("app_shutting_down")
        if app.state.github is not None:
            await app.state.github.close()
        if app.state.embedder is not None:
            await app.state.embedder.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OSS Contributor Engine",
        version="0.1.0",
        description=(
            "Multi-agent system that profiles a developer's GitHub history, "
            "hunts open-source issues that match their skills, and ranks them."
        ),
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(matches.router)
    app.include_router(investigations.router)
    app.include_router(pilot.router)
    app.include_router(admin.router)
    return app


app = create_app()
