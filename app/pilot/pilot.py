"""Pilot Coordinator — the v3 autonomous pipeline wrapped in DB persistence.

Flow:
    1. Mark PilotRun as `running`, set started_at.
    2. Resolve the parent Investigation: repo + issue number, plus GitHub
       token (from the user's encrypted OAuth row).
    3. Create a sandbox workspace + clone the repo (shallow).
    4. Code Explorer picks candidate files.
    5. Reviewer loop runs Patch Writer → Test Runner → decide×N.
    6. Persist the full ReviewerResult to PilotRun.transcript_json, set
       status to accepted / rejected, set accepted_diff if applicable.
    7. Cleanup the workspace.

Each phase is wrapped in try/except so any failure becomes a `failed`
PilotRun row with `error` populated — never an unhandled exception
escaping to the FastAPI background task layer.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.agents.explorer import explore
from app.agents.reviewer import review_and_iterate
from app.auth.crypto import decrypt_token
from app.db.models import Investigation, OAuthToken, PilotRun
from app.llm import ProvidersExhaustedError
from app.pilot.schemas import PilotConfig
from app.sandbox import SandboxRunner, Workspace
from app.tools.github import GitHubClient

log = structlog.get_logger(__name__)


async def run_pilot(
    *,
    pilot_id: str,
    investigation_id: str,
    user_id: int,
    llm_router,
    session_factory,
    config: PilotConfig | None = None,
) -> None:
    """Run one Pilot end-to-end with DB persistence.

    Designed to be called from a background task — never raises (errors
    are persisted to the PilotRun row). The caller owns the session
    factory because the background task outlives the HTTP request.
    """
    cfg = config or PilotConfig()

    # ---- Phase 1: load context + mark running ----
    with session_factory() as session:
        pilot = session.get(PilotRun, pilot_id)
        if pilot is None:
            log.error("pilot_row_missing", pilot_id=pilot_id)
            return
        inv = session.get(Investigation, investigation_id)
        if inv is None or inv.user_id != user_id:
            _fail(pilot, session, "investigation not found or not owned by user")
            return
        if inv.issue is None or inv.issue.repo is None:
            _fail(pilot, session, "investigation has no issue/repo association")
            return

        token_row = session.execute(
            _select_oauth_for(user_id),
        ).scalar_one_or_none()
        if token_row is None:
            _fail(pilot, session, "user has no OAuth token — re-sign in")
            return

        try:
            github_token = decrypt_token(token_row.encrypted_access_token)
        except Exception as e:
            _fail(pilot, session, f"OAuth token decrypt failed: {e}")
            return

        repo_full_name = inv.issue.repo.full_name
        issue_title = inv.issue.title
        issue_body = inv.issue.body
        issue_labels = list(inv.issue.labels or [])
        github_login = inv.user.github_login

        pilot.status = "running"
        pilot.started_at = _now()
        session.commit()

    log.info(
        "pilot_starting",
        pilot_id=pilot_id, repo=repo_full_name, user=github_login,
    )

    # ---- Phase 2: clone + explore + review ----
    # The workspace + GitHub client live outside the DB session because
    # they're long-lived (minutes); we re-open sessions for writes.
    ws = Workspace.create(f"pilot-{pilot_id[:8]}")
    try:
        try:
            repo_dir = ws.clone(repo_full_name)
        except Exception as e:
            with session_factory() as s:
                _fail(s.get(PilotRun, pilot_id), s, f"clone failed: {e}")
            return

        # ---- Explore ----
        try:
            exploration = await explore(
                repo=repo_full_name,
                repo_path=repo_dir,
                issue_title=issue_title,
                issue_body=issue_body,
                issue_labels=issue_labels,
                router=llm_router,
                max_candidates=cfg.max_files,
                investigation_id=investigation_id,
                user_id=user_id,
                session=None,  # telemetry path uses the worker's own session
            )
        except ProvidersExhaustedError as e:
            # Every LLM provider was rate-limited during exploration — a
            # transient capacity wall, not a real failure. Mark rate_limited
            # (retry) rather than failed. Persist FIRST (see below).
            with session_factory() as s:
                _rate_limited(
                    s.get(PilotRun, pilot_id), s,
                    f"all LLM providers were rate-limited during exploration: {e}",
                )
            log.warning("pilot_explore_rate_limited", pilot_id=pilot_id)
            return
        except Exception as e:
            # Persist FIRST — a logging call that raises (e.g. Windows cp1252
            # choking on box-drawing chars from a litellm Rich panel) must
            # never prevent the row from being marked failed, or it wedges
            # at 'running' forever.
            with session_factory() as s:
                _fail(s.get(PilotRun, pilot_id), s, f"explorer failed: {e}")
            log.exception("pilot_explore_failed", pilot_id=pilot_id)
            return

        if not exploration.candidates:
            with session_factory() as s:
                p = s.get(PilotRun, pilot_id)
                p.status = "rejected"
                p.summary = "Code Explorer found no candidate files."
                p.completed_at = _now()
                s.commit()
            return

        # ---- Review loop ----
        # The Investigator pipeline shares its GitHubClient via the
        # background runner pattern; the Pilot doesn't actually need a
        # GH client during reviewing (only during clone + later push in
        # Batch 34), so we close it here.
        try:
            async with GitHubClient(token=github_token) as _gh:
                pass  # placeholder for future push integration
        except Exception:
            # GitHub client init failed — not fatal for review, but log.
            log.warning("pilot_gh_client_warm_failed", pilot_id=pilot_id)

        try:
            result = await review_and_iterate(
                repo=repo_full_name,
                repo_path=repo_dir,
                workspace=ws,
                issue_title=issue_title,
                issue_body=issue_body,
                issue_labels=issue_labels,
                candidates=exploration.candidates,
                router=llm_router,
                max_attempts=cfg.max_attempts,
                test_timeout_s=cfg.test_timeout_s,
                sandbox_runner=SandboxRunner(),
                investigation_id=investigation_id,
                user_id=user_id,
                session=None,  # call_llm uses its own session per call
            )
        except Exception as e:
            # Persist before logging (see explore handler above for why).
            with session_factory() as s:
                _fail(s.get(PilotRun, pilot_id), s, f"reviewer loop failed: {e}")
            log.exception("pilot_review_failed", pilot_id=pilot_id)
            return

        # ---- Phase 3: persist final state ----
        if result.rate_limited:
            final_status = "rate_limited"
        elif result.success:
            final_status = "accepted"
        else:
            final_status = "rejected"

        transcript = result.model_dump(mode="json")
        with session_factory() as s:
            p = s.get(PilotRun, pilot_id)
            if p is None:
                log.error("pilot_row_vanished", pilot_id=pilot_id)
                return
            p.status = final_status
            p.summary = result.summary
            p.attempts_made = len(result.attempts)
            p.accepted_attempt_number = result.accepted_attempt_number
            p.accepted_diff = result.final_diff or None
            p.transcript_json = _dump_transcript(transcript)
            p.completed_at = _now()
            s.commit()
        log.info(
            "pilot_finished",
            pilot_id=pilot_id,
            status=final_status,
            attempts=len(result.attempts),
        )
    finally:
        ws.cleanup()


# ---------------------------------------------------------------------------
# Startup reconciliation
# ---------------------------------------------------------------------------

def reconcile_orphaned_pilots(session_factory) -> int:
    """Mark any pilot wedged in queued/running as failed.

    Pilots run in in-process background tasks (see app.jobs.spawn), which
    do NOT survive a server restart. So any pilot still in a non-terminal
    state when the process boots was orphaned by the previous shutdown —
    its task is gone and it will never progress. We mark these failed at
    startup so the UI doesn't poll a dead row forever.

    Safe to call exactly once during lifespan startup, before any requests
    are served: at that point there are no live tasks to race with.

    Returns the number of pilots reconciled.
    """
    from sqlalchemy import select

    with session_factory() as session:
        orphans = session.execute(
            select(PilotRun).where(PilotRun.status.in_(("queued", "running"))),
        ).scalars().all()
        for p in orphans:
            p.status = "failed"
            p.error = (
                (p.error + " | " if p.error else "")
                + "orphaned by a server restart (background task did not "
                "survive shutdown) — start a new pilot to retry"
            )
            p.completed_at = _now()
        if orphans:
            session.commit()
            log.warning("pilot_orphans_reconciled", count=len(orphans))
        return len(orphans)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fail(pilot: PilotRun | None, session: Session, reason: str) -> None:
    """Mark a pilot as failed with a reason and commit."""
    if pilot is None:
        return
    pilot.status = "failed"
    pilot.error = reason
    pilot.completed_at = _now()
    session.commit()
    log.warning("pilot_failed", pilot_id=pilot.id, reason=reason)


def _rate_limited(pilot: PilotRun | None, session: Session, reason: str) -> None:
    """Mark a pilot as rate-limited (transient capacity wall) and commit.

    Distinct from `_fail`: the run didn't break, every LLM provider was just
    throttled/unavailable. The UI surfaces this as "retry shortly" rather than
    a genuine failure."""
    if pilot is None:
        return
    pilot.status = "rate_limited"
    pilot.error = reason
    pilot.summary = "All LLM providers were rate-limited — retry in a minute."
    pilot.completed_at = _now()
    session.commit()
    log.warning("pilot_rate_limited", pilot_id=pilot.id, reason=reason)


def _select_oauth_for(user_id: int):
    """Tiny indirection to keep the sqlalchemy import local."""
    from sqlalchemy import select
    return select(OAuthToken).where(OAuthToken.user_id == user_id)


def _dump_transcript(transcript: dict[str, Any]) -> str:
    """Pretty-printed JSON. We trade DB bytes for human-readability —
    pilots are small (a few KB each) and the transcript is the main UI
    payload, so cheap JSON beats compactness here."""
    import json
    return json.dumps(transcript, indent=2, default=str)
