"""Pilot routes — nested under /investigations/{id}/pilot.

POST creates a PilotRun row + spawns the background pilot. GET returns
the latest row. List returns all runs for the investigation.

A pilot can only be started for an investigation that's:
  - owned by the calling user, AND
  - in status='completed' (so we have a Report to base the fix on)

Concurrent pilots for the same investigation are refused with 409 —
running two LLM-driven write loops on the same workspace would race.
"""
from __future__ import annotations

import json
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.dependencies import RouterDep, SessionDep
from app.auth.dependencies import CurrentUserDep
from app.core.config import settings
from app.db.models import Investigation, PilotRun, User
from app.db.session import sessionmaker_factory
from app.jobs import spawn
from app.pilot import (
    CreatePilotResponse,
    OpenPRResponse,
    PilotConfig,
    PilotRunRow,
    PushPilotResponse,
    cost_cap_exceeded,
    is_repo_refused,
    open_pilot_pr,
    push_pilot_branch,
    run_pilot,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/investigations", tags=["pilot"])


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

async def _run_pilot_background(
    pilot_id: str,
    investigation_id: str,
    user_id: int,
    *,
    llm_router,
    session_factory,
    config: PilotConfig,
) -> None:
    """Async wrapper so app.jobs.spawn can hand us an awaitable.

    `run_pilot` already swallows its own exceptions (and writes them to
    the PilotRun row), but we double-wrap to keep the background task
    from ever propagating an unhandled exception.
    """
    try:
        await run_pilot(
            pilot_id=pilot_id,
            investigation_id=investigation_id,
            user_id=user_id,
            llm_router=llm_router,
            session_factory=session_factory,
            config=config,
        )
    except Exception:
        log.exception("pilot_background_unhandled", pilot_id=pilot_id)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/{investigation_id}/pilot",
    response_model=CreatePilotResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_pilot(
    investigation_id: str,
    body: PilotConfig | None = None,
    request: Request = None,  # type: ignore[assignment]
    me: User = CurrentUserDep,
    session: Session = SessionDep,
    router_=RouterDep,
) -> CreatePilotResponse:
    """Kick off an autonomous-pilot run for a completed investigation."""
    if not settings.pilot_enabled:
        # Hosted free-tier deploys disable the pilot (no Docker daemon, no
        # persistent disk for git clones). Tell the user how to use it.
        raise HTTPException(
            status_code=503,
            detail=(
                "Autonomous Pilot is disabled in this deployment — it needs "
                "a Docker sandbox and persistent disk that free PaaS tiers "
                "don't provide. Clone the repo and run it locally to use "
                "the pilot."
            ),
        )
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        # Don't leak existence to other users.
        raise HTTPException(status_code=404, detail="Investigation not found")
    if inv.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Investigation status is {inv.status!r}; "
                f"need 'completed' to start a pilot"
            ),
        )

    # --- Safety rail: per-user cost cap (Batch 37) ---
    # Fail before spending more LLM budget if the user is already over.
    exceeded, spent, cap = cost_cap_exceeded(session, me.id)
    if exceeded:
        raise HTTPException(
            status_code=402,  # Payment Required — semantically apt
            detail=(
                f"LLM cost cap reached (${spent:.4f} spent / ${cap:.2f} cap). "
                f"Raise MAX_USER_COST_USD to continue."
            ),
        )

    # --- Safety rail: refuse-list (Batch 37) ---
    # Reject early so we don't spend an LLM run on a repo we'll never push to.
    repo_full = (
        inv.issue.repo.full_name if inv.issue and inv.issue.repo else None
    )
    if repo_full and is_repo_refused(repo_full):
        raise HTTPException(
            status_code=403,
            detail=(
                f"{repo_full} is on the pilot refuse-list — its maintainers "
                f"have opted out of AI-generated contributions."
            ),
        )

    # Refuse if another pilot is already running for this investigation.
    in_flight = session.execute(
        select(PilotRun).where(
            PilotRun.investigation_id == investigation_id,
            PilotRun.status.in_(("queued", "running")),
        ),
    ).scalar_one_or_none()
    if in_flight is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Pilot {in_flight.id} is already running for this investigation",
        )

    pilot_id = str(uuid.uuid4())
    pilot = PilotRun(
        id=pilot_id,
        investigation_id=investigation_id,
        user_id=me.id,
        status="queued",
    )
    session.add(pilot)
    session.commit()

    session_factory = getattr(
        request.app.state, "session_factory", None,
    ) or sessionmaker_factory()

    cfg = body or PilotConfig()
    spawn(
        _run_pilot_background(
            pilot_id, investigation_id, me.id,
            llm_router=router_,
            session_factory=session_factory,
            config=cfg,
        ),
        name=f"pilot:{pilot_id[:8]}",
    )
    log.info(
        "pilot_queued",
        pilot_id=pilot_id, investigation_id=investigation_id, user_id=me.id,
    )
    return CreatePilotResponse(pilot_id=pilot_id, status="queued")


@router.get(
    "/{investigation_id}/pilot",
    response_model=PilotRunRow,
)
async def get_latest_pilot(
    investigation_id: str,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> PilotRunRow:
    """Return the most recent pilot run for this investigation."""
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")

    row = session.execute(
        select(PilotRun)
        .where(PilotRun.investigation_id == investigation_id)
        .order_by(desc(PilotRun.created_at))
        .limit(1),
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No pilot run for this investigation yet",
        )
    return _to_pilot_row(row)


@router.get(
    "/{investigation_id}/pilot/all",
    response_model=list[PilotRunRow],
)
async def list_pilots(
    investigation_id: str,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> list[PilotRunRow]:
    """Every pilot run for this investigation, newest first."""
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")

    rows = session.execute(
        select(PilotRun)
        .where(PilotRun.investigation_id == investigation_id)
        .order_by(desc(PilotRun.created_at)),
    ).scalars().all()
    return [_to_pilot_row(r) for r in rows]


# ---------------------------------------------------------------------------
# Push endpoint (Batch 34)
# ---------------------------------------------------------------------------

async def _run_push_background(
    pilot_id: str,
    *,
    session_factory,
) -> None:
    """Wrapper so spawn() gets an awaitable + we swallow any final escape."""
    try:
        await push_pilot_branch(
            pilot_id=pilot_id, session_factory=session_factory,
        )
    except Exception:
        log.exception("pilot_push_background_unhandled", pilot_id=pilot_id)


@router.post(
    "/{investigation_id}/pilot/{pilot_id}/push",
    response_model=PushPilotResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def push_pilot(
    investigation_id: str,
    pilot_id: str,
    request: Request,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> PushPilotResponse:
    """Push the accepted diff for `pilot_id` to the user's GitHub fork.

    Pre-flight here is intentionally redundant with pusher.py — we want
    to 4xx the obvious cases synchronously before spawning a background
    task. The pusher then re-validates inside the worker because the
    state could have changed between the HTTP request and the task run.
    """
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        # 404, not 403 — no existence leak.
        raise HTTPException(status_code=404, detail="Investigation not found")

    pilot = session.get(PilotRun, pilot_id)
    if pilot is None or pilot.investigation_id != investigation_id:
        raise HTTPException(status_code=404, detail="Pilot not found")
    if pilot.user_id != me.id:
        raise HTTPException(status_code=404, detail="Pilot not found")

    if pilot.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pilot status is {pilot.status!r}; "
                f"can only push 'accepted' pilots"
            ),
        )
    if pilot.pushed_at is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pilot already pushed to {pilot.branch_ref!r}; "
                f"won't clobber the existing branch"
            ),
        )

    session_factory = getattr(
        request.app.state, "session_factory", None,
    ) or sessionmaker_factory()

    spawn(
        _run_push_background(pilot_id, session_factory=session_factory),
        name=f"pilot-push:{pilot_id[:8]}",
    )
    log.info("pilot_push_queued", pilot_id=pilot_id, user_id=me.id)
    return PushPilotResponse(pilot_id=pilot_id)


# ---------------------------------------------------------------------------
# Open-PR endpoint (Batch 35)
# ---------------------------------------------------------------------------

async def _run_pr_background(
    pilot_id: str,
    *,
    session_factory,
) -> None:
    try:
        await open_pilot_pr(
            pilot_id=pilot_id, session_factory=session_factory,
        )
    except Exception:
        log.exception("pilot_pr_background_unhandled", pilot_id=pilot_id)


@router.post(
    "/{investigation_id}/pilot/{pilot_id}/pr",
    response_model=OpenPRResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def open_pr(
    investigation_id: str,
    pilot_id: str,
    request: Request,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> OpenPRResponse:
    """Open a draft PR upstream from the user's pushed pilot branch.

    Like the push endpoint, we pre-flight the obvious failure modes here
    (synchronously, with 4xx) and let the background task re-validate
    when it actually runs.
    """
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")

    pilot = session.get(PilotRun, pilot_id)
    if (
        pilot is None
        or pilot.investigation_id != investigation_id
        or pilot.user_id != me.id
    ):
        raise HTTPException(status_code=404, detail="Pilot not found")

    if pilot.status != "accepted":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Pilot status is {pilot.status!r}; "
                f"can only open PRs for 'accepted' pilots"
            ),
        )
    if pilot.pushed_at is None or not pilot.branch_ref:
        raise HTTPException(
            status_code=409,
            detail="Pilot hasn't been pushed yet — POST .../push first",
        )
    if pilot.pr_url is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"PR already opened at {pilot.pr_url} (#{pilot.pr_number}); "
                f"won't reopen"
            ),
        )

    session_factory = getattr(
        request.app.state, "session_factory", None,
    ) or sessionmaker_factory()

    spawn(
        _run_pr_background(pilot_id, session_factory=session_factory),
        name=f"pilot-pr:{pilot_id[:8]}",
    )
    log.info("pilot_pr_queued", pilot_id=pilot_id, user_id=me.id)
    return OpenPRResponse(pilot_id=pilot_id)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _to_pilot_row(p: PilotRun) -> PilotRunRow:
    transcript: dict | None = None
    if p.transcript_json:
        try:
            transcript = json.loads(p.transcript_json)
        except json.JSONDecodeError:
            # Corrupt JSON in DB — log + return None instead of 500ing
            # since the rest of the row is still useful.
            log.warning("pilot_transcript_json_decode_failed", pilot_id=p.id)
            transcript = None

    return PilotRunRow(
        id=p.id,
        investigation_id=p.investigation_id,
        status=p.status,  # type: ignore[arg-type]
        summary=p.summary,
        attempts_made=p.attempts_made,
        accepted_attempt_number=p.accepted_attempt_number,
        accepted_diff=p.accepted_diff,
        transcript=transcript,
        error=p.error,
        started_at=p.started_at.isoformat() if p.started_at else None,
        completed_at=p.completed_at.isoformat() if p.completed_at else None,
        fork_url=p.fork_url,
        branch_ref=p.branch_ref,
        pushed_at=p.pushed_at.isoformat() if p.pushed_at else None,
        push_error=p.push_error,
        pr_url=p.pr_url,
        pr_number=p.pr_number,
        pr_opened_at=p.pr_opened_at.isoformat() if p.pr_opened_at else None,
        pr_error=p.pr_error,
    )
