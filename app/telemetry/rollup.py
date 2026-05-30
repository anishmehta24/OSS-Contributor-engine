"""Cost / token / latency rollups from the agent_runs table.

We aggregate in Python rather than SQL so this code stays the same when
we eventually swap SQLite for Postgres. For our scale (hundreds of runs)
the overhead is negligible.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AgentRun


class CostBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_name: str
    calls: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    errors: int = 0


class CostSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str                   # "investigation:<id>" or "global"
    total_calls: int
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    total_latency_ms: int
    total_errors: int
    per_agent: list[CostBreakdown]


# ---------------------------------------------------------------------------
# Pure aggregation (testable without a DB)
# ---------------------------------------------------------------------------

def aggregate(runs: Iterable[AgentRun], *, scope: str) -> CostSummary:
    per_agent_acc: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {"calls": 0, "tokens_in": 0, "tokens_out": 0,
                 "cost_usd": 0.0, "latency_ms": 0, "errors": 0}
    )
    total_calls = total_in = total_out = total_lat = total_errors = 0
    total_cost = 0.0

    for r in runs:
        bucket = per_agent_acc[r.agent_name]
        bucket["calls"] += 1
        bucket["tokens_in"] += r.tokens_in or 0
        bucket["tokens_out"] += r.tokens_out or 0
        bucket["cost_usd"] += float(r.cost_usd or 0.0)
        bucket["latency_ms"] += r.latency_ms or 0
        if r.status != "success":
            bucket["errors"] += 1
            total_errors += 1
        total_calls += 1
        total_in += r.tokens_in or 0
        total_out += r.tokens_out or 0
        total_lat += r.latency_ms or 0
        total_cost += float(r.cost_usd or 0.0)

    per_agent = [
        CostBreakdown(
            agent_name=name,
            calls=int(b["calls"]),
            tokens_in=int(b["tokens_in"]),
            tokens_out=int(b["tokens_out"]),
            cost_usd=round(float(b["cost_usd"]), 6),
            latency_ms=int(b["latency_ms"]),
            errors=int(b["errors"]),
        )
        for name, b in sorted(per_agent_acc.items())
    ]

    return CostSummary(
        scope=scope,
        total_calls=total_calls,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
        total_cost_usd=round(total_cost, 6),
        total_latency_ms=total_lat,
        total_errors=total_errors,
        per_agent=per_agent,
    )


# ---------------------------------------------------------------------------
# DB-bound rollups
# ---------------------------------------------------------------------------

def investigation_cost(session: Session, investigation_id: str) -> CostSummary:
    """Cost for a single investigation."""
    runs = session.execute(
        select(AgentRun).where(AgentRun.investigation_id == investigation_id)
    ).scalars().all()
    return aggregate(runs, scope=f"investigation:{investigation_id}")


def global_cost(session: Session) -> CostSummary:
    """Cost across every LLM call we've ever made."""
    runs = session.execute(select(AgentRun)).scalars().all()
    return aggregate(runs, scope="global")


def user_cost_usd(session: Session, user_id: int) -> float:
    """Lifetime LLM spend for one user, in USD.

    Aggregated in SQL (a single SUM) rather than pulling rows — this is on
    the hot path for the cost-cap check, so we keep it cheap even as
    agent_runs grows.
    """
    total = session.execute(
        select(func.coalesce(func.sum(AgentRun.cost_usd), 0.0))
        .where(AgentRun.user_id == user_id),
    ).scalar()
    return float(total or 0.0)
