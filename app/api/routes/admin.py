"""Admin endpoints — DB stats, manual hunt trigger.

Not authenticated yet (single-tenant). In Batch 11+ we'd lock these behind
an API key or remove them in favor of scheduled jobs (Batch 9).
"""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.hunter.schemas import HunterConfig
from app.api.dependencies import GHDep, RouterDep, SessionDep, VoyageDep
from app.api.schemas import DbStats, HuntRequest, HuntResponse
from app.telemetry import CostSummary, global_cost
from app.workers.issue_hunter import hunt

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=DbStats)
async def db_stats(session: Session = SessionDep) -> DbStats:
    def _count(table: str) -> int:
        return session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0

    return DbStats(
        users=_count("users"),
        user_skills=_count("user_skills"),
        repos=_count("repos"),
        issues=_count("issues"),
        investigations=_count("investigations"),
        agent_runs=_count("agent_runs"),
        issues_with_embeddings=_count("issues_vec"),
    )


@router.post("/hunt", response_model=HuntResponse)
async def trigger_hunt(
    body: HuntRequest,
    session: Session = SessionDep,
    gh=GHDep,
    router_=RouterDep,
    voyage=VoyageDep,
) -> HuntResponse:
    """Trigger an Issue Hunter run synchronously.

    Note: this can take 1-5 minutes depending on `max_total_issues`. Batch 9
    wraps this in a background job so the HTTP request doesn't block.
    """
    kwargs: dict = dict(
        mode=body.mode,
        max_total_issues=body.max_total_issues,
        enable_difficulty_llm=body.enable_difficulty_llm,
        enable_embeddings=body.enable_embeddings,
    )
    # GSoC mode loosens defaults — smaller orgs, longer-lived issues.
    if body.mode == "gsoc":
        kwargs.setdefault("min_stars", 10)
        kwargs.setdefault("updated_since_days", 60)
    config = HunterConfig(**kwargs)
    if body.languages:
        config = config.model_copy(update={"languages": body.languages})

    stats = await hunt(
        gh=gh, router=router_, embedder=voyage,
        session=session, config=config,
    )
    return HuntResponse(stats=stats)


@router.get("/cost", response_model=CostSummary)
async def get_global_cost(session: Session = SessionDep) -> CostSummary:
    """Token / cost / latency rollup across all LLM calls ever made."""
    return global_cost(session)
