"""Tests for the agent_runs telemetry rollups."""
from __future__ import annotations

import pytest

from app.db.models import AgentRun, Investigation, Issue, Repo, User
from app.telemetry.rollup import (
    aggregate,
    global_cost,
    investigation_cost,
)

# ---------------------------------------------------------------------------
# Pure aggregation (no DB required)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_aggregate_empty_returns_zeros():
    summary = aggregate([], scope="empty")
    assert summary.total_calls == 0
    assert summary.total_tokens_in == 0
    assert summary.total_cost_usd == 0.0
    assert summary.per_agent == []
    assert summary.scope == "empty"


@pytest.mark.unit
def test_aggregate_sums_across_agents():
    runs = [
        AgentRun(
            agent_name="repo_mapper", provider="gemini", model="x",
            tokens_in=100, tokens_out=200, cost_usd=0.001,
            latency_ms=1000, status="success",
        ),
        AgentRun(
            agent_name="repo_mapper", provider="gemini", model="x",
            tokens_in=50, tokens_out=80, cost_usd=0.0005,
            latency_ms=800, status="success",
        ),
        AgentRun(
            agent_name="synthesizer", provider="groq", model="y",
            tokens_in=300, tokens_out=400, cost_usd=0.0,
            latency_ms=600, status="success",
        ),
    ]
    summary = aggregate(runs, scope="test")
    assert summary.total_calls == 3
    assert summary.total_tokens_in == 450
    assert summary.total_tokens_out == 680
    assert summary.total_cost_usd == pytest.approx(0.0015)
    assert summary.total_latency_ms == 2400
    assert summary.total_errors == 0
    assert len(summary.per_agent) == 2

    # Sorted alphabetically
    names = [a.agent_name for a in summary.per_agent]
    assert names == ["repo_mapper", "synthesizer"]
    rm = next(a for a in summary.per_agent if a.agent_name == "repo_mapper")
    assert rm.calls == 2
    assert rm.tokens_in == 150


@pytest.mark.unit
def test_aggregate_counts_errors():
    runs = [
        AgentRun(agent_name="a", provider="g", model="x",
                 tokens_in=10, tokens_out=10, status="success"),
        AgentRun(agent_name="a", provider="g", model="x",
                 tokens_in=0, tokens_out=0, status="error"),
        AgentRun(agent_name="b", provider="g", model="x",
                 tokens_in=0, tokens_out=0, status="error"),
    ]
    summary = aggregate(runs, scope="test")
    assert summary.total_errors == 2
    a_bucket = next(a for a in summary.per_agent if a.agent_name == "a")
    assert a_bucket.errors == 1


@pytest.mark.unit
def test_aggregate_handles_none_values_safely():
    runs = [
        AgentRun(
            agent_name="x", provider="g", model="x",
            tokens_in=None, tokens_out=None, cost_usd=None,
            latency_ms=None, status="success",
        ),
    ]
    summary = aggregate(runs, scope="test")
    assert summary.total_tokens_in == 0
    assert summary.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# DB-bound rollups
# ---------------------------------------------------------------------------

_seed_counter = {"n": 0}


def _seed_investigation(session) -> str:
    _seed_counter["n"] += 1
    n = _seed_counter["n"]
    user = User(github_login=f"dev{n}", github_id=n)
    repo = Repo(id=n, full_name=f"x/y{n}", name=f"y{n}", html_url="x")
    session.add_all([user, repo])
    session.flush()
    issue = Issue(
        id=n, repo_id=repo.id, number=1, title="t", html_url="x",
        issue_created_at=__import__("datetime").datetime(2026, 5, 10),
        issue_updated_at=__import__("datetime").datetime(2026, 5, 10),
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=user.id, issue_id=issue.id, status="completed")
    session.add(inv)
    session.commit()
    return inv.id


@pytest.mark.unit
def test_investigation_cost_filters_by_id(session):
    inv1 = _seed_investigation(session)
    inv2 = _seed_investigation(session)

    session.add_all([
        AgentRun(investigation_id=inv1, agent_name="a", provider="g", model="x",
                 tokens_in=100, tokens_out=100, cost_usd=0.01,
                 latency_ms=100, status="success"),
        AgentRun(investigation_id=inv2, agent_name="a", provider="g", model="x",
                 tokens_in=999, tokens_out=999, cost_usd=0.99,
                 latency_ms=999, status="success"),
    ])
    session.commit()

    s1 = investigation_cost(session, inv1)
    assert s1.total_tokens_in == 100  # only inv1's row
    assert s1.scope == f"investigation:{inv1}"


@pytest.mark.unit
def test_global_cost_includes_all_runs(session):
    inv = _seed_investigation(session)
    session.add_all([
        AgentRun(investigation_id=inv, agent_name="a", provider="g", model="x",
                 tokens_in=10, tokens_out=10, cost_usd=0.001,
                 latency_ms=10, status="success"),
        AgentRun(investigation_id=None, agent_name="standalone", provider="g", model="x",
                 tokens_in=20, tokens_out=20, cost_usd=0.002,
                 latency_ms=20, status="success"),
    ])
    session.commit()

    summary = global_cost(session)
    assert summary.total_calls == 2
    assert summary.total_tokens_in == 30
    assert summary.total_cost_usd == pytest.approx(0.003)
    assert summary.scope == "global"


@pytest.mark.unit
def test_investigation_cost_with_no_runs_returns_zeros(session):
    inv = _seed_investigation(session)
    summary = investigation_cost(session, inv)
    assert summary.total_calls == 0
    assert summary.per_agent == []
