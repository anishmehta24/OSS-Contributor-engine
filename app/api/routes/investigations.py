"""Investigations endpoints — async pattern with SSE progress streaming.

Lifecycle:
    POST   /investigations               202  -> {job_id, status: "queued"}  (spawns background task)
    GET    /investigations/{id}          200  -> current state (poll-friendly)
    GET    /investigations/{id}/stream   text/event-stream — live progress events
    POST   /investigations/{id}/pitch    draft (or refresh) a comment for the issue
    GET    /investigations/{id}/cost     token/cost/latency rollup
    GET    /investigations               list recent
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agents.investigator.investigator import investigate
from app.agents.pitch.pitch_writer import run_pitch_writer
from app.agents.pitch.schemas import PitchDraft
from app.api.dependencies import RouterDep, SessionDep
from app.auth.dependencies import CurrentUserDep, current_user_github_token
from app.db.models import Investigation, User
from app.db.session import sessionmaker_factory
from app.jobs import spawn
from app.streaming import publish, subscribe, unsubscribe
from app.telemetry import CostSummary, investigation_cost
from app.tools.github import GitHubClient

# Module-level dep singletons (keep ruff B008 happy)
_UserTokenDep = Depends(current_user_github_token)

# Tests override this on app.state to inject the test engine's sessionmaker.
SESSION_FACTORY_STATE_KEY = "session_factory"

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/investigations", tags=["investigations"])


# ---------------------------------------------------------------------------
# Request/response shapes
# ---------------------------------------------------------------------------

class CreateInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str = Field(min_length=3, max_length=128, description="owner/repo")
    issue_number: int = Field(ge=1)


class JobAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str
    status: str = "queued"


class InvestigationRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    status: str
    repo: str | None
    issue_number: int | None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    markdown_report: str | None = None


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

async def _run_investigation_background(
    investigation_id: str,
    user_login: str,
    repo: str,
    issue_number: int,
    *,
    github_token: str,
    llm_router,
    session_factory,
) -> None:
    """Fresh DB session + fresh GitHubClient per background task — never share.

    Background tasks outlive the HTTP request, so dependency-injected clients
    would be closed by the time the task uses them. We create our own here
    using the same OAuth token.
    """
    async with GitHubClient(token=github_token) as gh:
        with session_factory() as session:
            try:
                await investigate(
                    user_login=user_login,
                    repo_full_name=repo,
                    issue_number=issue_number,
                    gh=gh, router=llm_router, session=session,
                    investigation_id=investigation_id,
                )
            except Exception:  # logged inside investigate(); ensure we don't leak
                log.exception(
                    "background_investigation_unhandled",
                    repo=repo, issue=issue_number,
                )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=JobAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_investigation(
    body: CreateInvestigationRequest,
    request: Request,
    me: User = CurrentUserDep,
    github_token: str = _UserTokenDep,
    router_=RouterDep,
) -> JobAcceptedResponse:
    """Accept a job and run it in the background for the logged-in user.

    Poll `GET /investigations/{job_id}` for status, or subscribe to
    `GET /investigations/{job_id}/stream` for live agent progress.
    """
    if "/" not in body.repo:
        raise HTTPException(status_code=422, detail="`repo` must be in 'owner/name' form")

    # Make sure the user has a profile — otherwise the Investigator's
    # ranking-based context is empty.
    if me.skill is None:
        raise HTTPException(
            status_code=409,
            detail="No profile yet — POST /users/me/profile first",
        )

    # Allocate the investigation id now so we can return it from POST and
    # SSE subscribers can subscribe before the background task even runs.
    inv_id = str(uuid.uuid4())

    session_factory = getattr(
        request.app.state, SESSION_FACTORY_STATE_KEY, None,
    ) or sessionmaker_factory()

    spawn(
        _run_investigation_background(
            inv_id, me.github_login, body.repo, body.issue_number,
            github_token=github_token, llm_router=router_,
            session_factory=session_factory,
        ),
        name=f"investigation:{body.repo}#{body.issue_number}",
    )

    publish(inv_id, {"type": "queued", "repo": body.repo, "issue_number": body.issue_number})

    return JobAcceptedResponse(job_id=inv_id, status="queued")


@router.get("/{investigation_id}", response_model=InvestigationRow)
async def get_investigation(
    investigation_id: str,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> InvestigationRow:
    inv = session.get(Investigation, investigation_id)
    if inv is None:
        # In async mode this is common right after POST — the row may not
        # exist yet until the background task starts. Return a synthetic
        # "queued" so polling is well-defined.
        return InvestigationRow(
            id=investigation_id, status="queued", repo=None, issue_number=None,
        )
    if inv.user_id != me.id:
        # Don't leak existence to other users — return 404
        raise HTTPException(status_code=404, detail="Investigation not found")
    return InvestigationRow(
        id=inv.id,
        status=inv.status,
        repo=inv.issue.repo.full_name if inv.issue and inv.issue.repo else None,
        issue_number=inv.issue.number if inv.issue else None,
        error=inv.error,
        started_at=inv.started_at.isoformat() if inv.started_at else None,
        completed_at=inv.completed_at.isoformat() if inv.completed_at else None,
        markdown_report=inv.report_md,
    )


@router.get("/{investigation_id}/stream")
async def stream_investigation(
    investigation_id: str,
    request: Request,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> StreamingResponse:
    """SSE stream of progress events. Closes after a terminal event arrives,
    or after STREAM_TIMEOUT_S if nothing happens (idle disconnect).

    Returns 404 if the investigation belongs to a different user (don't
    leak existence). For a brand-new job (row not yet created), we allow
    the stream — the user just told us this id via POST.
    """
    inv_check = session.get(Investigation, investigation_id)
    if inv_check is not None and inv_check.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")
    STREAM_TIMEOUT_S = 5 * 60   # 5 min hard cap
    HEARTBEAT_S = 15            # keep the connection alive through proxies

    q = subscribe(investigation_id)

    async def event_iter() -> AsyncIterator[str]:
        terminal = {"investigation_completed", "investigation_failed"}
        started = datetime.now(UTC)
        try:
            # If the row already exists and is terminal, emit it once and exit.
            inv = session.get(Investigation, investigation_id)
            if inv is not None and inv.status in ("completed", "failed"):
                payload = {
                    "type": f"investigation_{inv.status}",
                    "investigation_id": inv.id,
                    "from_cache": True,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                return

            while True:
                if await request.is_disconnected():
                    return
                if (datetime.now(UTC) - started).total_seconds() > STREAM_TIMEOUT_S:
                    yield f"data: {json.dumps({'type': 'stream_timeout'})}\n\n"
                    return
                try:
                    event = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                except TimeoutError:
                    # Heartbeat to keep proxies from closing the connection.
                    yield ": heartbeat\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") in terminal:
                    return
        finally:
            unsubscribe(investigation_id, q)

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )


class PitchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    investigation_id: str
    comment_md: str
    asks_questions: bool
    estimated_timeline: str | None = None
    tone: str = "respectful"
    cached: bool = False


@router.post("/{investigation_id}/pitch", response_model=PitchResponse)
async def draft_pitch(
    investigation_id: str,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
    router_=RouterDep,
    force: bool = False,
) -> PitchResponse:
    """Draft (or refresh, with ?force=true) a comment for the investigation.

    Requires the investigation to be in `completed` state and owned by you.
    """
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if inv.status != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Investigation status is {inv.status!r}; need 'completed'",
        )
    if not inv.report_md:
        raise HTTPException(status_code=409, detail="Investigation has no report yet")

    if inv.pitch_md and not force:
        return PitchResponse(
            investigation_id=inv.id,
            comment_md=inv.pitch_md,
            asks_questions="?" in inv.pitch_md,
            estimated_timeline=None,
            cached=True,
        )

    repo_full_name = inv.issue.repo.full_name if inv.issue and inv.issue.repo else "?"
    issue_number = inv.issue.number if inv.issue else 0
    issue_url = inv.issue.html_url if inv.issue else ""

    pitch: PitchDraft = run_pitch_writer(
        router_,
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        issue_url=issue_url,
        markdown_report=inv.report_md,
        investigation_id=inv.id,
        user_id=inv.user_id,
        session=session,
    )
    inv.pitch_md = pitch.comment_md
    session.commit()

    return PitchResponse(
        investigation_id=inv.id,
        comment_md=pitch.comment_md,
        asks_questions=pitch.asks_questions,
        estimated_timeline=pitch.estimated_timeline,
        tone=pitch.tone,
        cached=False,
    )


@router.get("/{investigation_id}/cost", response_model=CostSummary)
async def get_investigation_cost(
    investigation_id: str,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> CostSummary:
    """Token / cost / latency rollup for one of your investigations."""
    inv = session.get(Investigation, investigation_id)
    if inv is None or inv.user_id != me.id:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation_cost(session, investigation_id)


@router.get("", response_model=list[InvestigationRow])
async def list_my_investigations(
    limit: int = 20,
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> list[InvestigationRow]:
    """Recent investigations belonging to the logged-in user."""
    limit = max(1, min(100, limit))
    rows = session.execute(
        select(Investigation)
        .where(Investigation.user_id == me.id)
        .order_by(desc(Investigation.created_at))
        .limit(limit)
    ).scalars().all()
    return [
        InvestigationRow(
            id=r.id,
            status=r.status,
            repo=r.issue.repo.full_name if r.issue and r.issue.repo else None,
            issue_number=r.issue.number if r.issue else None,
            error=r.error,
            started_at=r.started_at.isoformat() if r.started_at else None,
            completed_at=r.completed_at.isoformat() if r.completed_at else None,
            markdown_report=None,
        )
        for r in rows
    ]
