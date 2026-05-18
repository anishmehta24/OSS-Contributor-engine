"""End-to-end Investigator pipeline tests (mocked GitHub + mocked LLM)."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents.investigator.investigator import investigate
from app.db.models import AgentRun, Investigation, User
from app.tools.github.models import (
    Commit,
    IssueLabel,
)
from app.tools.github.models import (
    Issue as GHIssue,
)
from app.tools.github.models import (
    Repo as GHRepo,
)

NOW = datetime(2026, 5, 10)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _gh_issue(**overrides):
    defaults = dict(
        id=999, number=42, title="Add metrics endpoint",
        body="We need a /metrics endpoint for Prometheus.",
        state="open",
        labels=[IssueLabel(name="enhancement")],
        comments=1,
        html_url="https://github.com/acme/web/issues/42",
        created_at=NOW, updated_at=NOW,
    )
    defaults.update(overrides)
    return GHIssue(**defaults)


def _gh_repo(**overrides):
    defaults = dict(
        id=100, full_name="acme/web", name="web",
        description="A web app", language="Python",
        html_url="https://github.com/acme/web",
        stargazers_count=500,
    )
    defaults.update(overrides)
    return GHRepo(**defaults)


def _fake_gh(issue=None, repo=None, tree=None, comments=None, commits=None):
    gh = SimpleNamespace()
    gh.get_issue = AsyncMock(return_value=issue or _gh_issue())
    gh.get_issue_comments = AsyncMock(return_value=comments or [])
    gh.get_repo_tree = AsyncMock(return_value=tree or [
        {"path": "src/api.py", "type": "blob", "size": 500},
        {"path": "src/metrics.py", "type": "blob", "size": 200},
    ])
    gh.get_recent_commits = AsyncMock(return_value=commits or [
        Commit(sha="abc", message="Add health endpoint", html_url="x"),
    ])
    gh.get_repo = AsyncMock(return_value=repo or _gh_repo())
    return gh


class _ScriptedRouter:
    """Returns the next response in `responses` on each call.

    Used to give each LLM agent its own canned answer (4 agents, 4 responses).
    """
    def __init__(self, responses: list[str]):
        self._queue = list(responses)
        self.call_count = 0
        self.model_list = [{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}]

    def completion(self, **_):
        self.call_count += 1
        body = self._queue.pop(0) if self._queue else "{}"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=body))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
            _hidden_params={"response_cost": 0.0001},
        )


def _good_responses():
    return [
        # 1. Issue Analyst
        '{"summary": "Add metrics endpoint", "requirements": ["expose /metrics"],'
        ' "acceptance_criteria": ["returns 200"], "open_questions": ["format?"],'
        ' "technical_keywords": ["metrics", "prometheus"]}',
        # 2. Repo Mapper
        '{"repo_summary": "A web app", "candidate_files": ['
        '{"path": "src/api.py", "reason": "routes live here"},'
        '{"path": "src/metrics.py", "reason": "obvious target"}'
        ']}',
        # 3. History Detective
        '{"recent_themes": ["routes"], "notable_commits": ["Add health endpoint"],'
        ' "summary": "Active routing work recently."}',
        # 4. Synthesizer
        '{"issue_summary": "Add /metrics for Prometheus.",'
        ' "candidate_files": [{"path": "src/api.py", "reason": "routes"}],'
        ' "suggested_approach": "Add a /metrics route and a unit test.",'
        ' "open_questions": ["Auth required?"],'
        ' "risks": ["Avoid leaking labels with PII"],'
        ' "estimated_effort": "few-hours"}',
    ]


def _seed_user(session, login="dev"):
    user = User(github_login=login, github_id=1)
    session.add(user)
    session.commit()
    return user


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_investigate_end_to_end_happy_path(session):
    _seed_user(session)
    gh = _fake_gh()
    router = _ScriptedRouter(_good_responses())

    result = await investigate(
        user_login="dev",
        repo_full_name="acme/web",
        issue_number=42,
        gh=gh, router=router, session=session,
    )

    assert result.status == "completed"
    assert result.investigation_id is not None
    assert result.report is not None
    assert result.report.estimated_effort == "few-hours"
    assert result.markdown_report and "acme/web#42" in result.markdown_report

    # 4 LLM calls = 4 agent_runs
    runs = session.execute(select(AgentRun)).scalars().all()
    assert len(runs) == 4
    agent_names = {r.agent_name for r in runs}
    assert agent_names == {
        "issue_analyst", "repo_mapper", "history_detective", "synthesizer",
    }

    # Investigation row finalized
    inv = session.execute(select(Investigation)).scalar_one()
    assert inv.status == "completed"
    assert inv.report_md is not None
    assert inv.completed_at is not None


@pytest.mark.unit
async def test_investigate_raises_for_unknown_user(session):
    gh = _fake_gh()
    router = _ScriptedRouter(_good_responses())
    with pytest.raises(ValueError, match="not found"):
        await investigate(
            user_login="ghost",
            repo_full_name="acme/web",
            issue_number=42,
            gh=gh, router=router, session=session,
        )


@pytest.mark.unit
async def test_investigate_fetches_data_in_parallel(session):
    _seed_user(session)
    gh = _fake_gh()
    router = _ScriptedRouter(_good_responses())

    await investigate(
        user_login="dev", repo_full_name="acme/web", issue_number=42,
        gh=gh, router=router, session=session,
    )

    # All five GH endpoints hit exactly once
    gh.get_issue.assert_awaited_once_with("acme/web", 42)
    gh.get_issue_comments.assert_awaited_once()
    gh.get_repo_tree.assert_awaited_once_with("acme/web")
    gh.get_recent_commits.assert_awaited_once()
    gh.get_repo.assert_awaited_once_with("acme/web")


@pytest.mark.unit
async def test_investigate_persists_when_llm_partially_fails(session):
    """If one LLM call returns garbage, we still get an investigation row +
    a report (just with degraded content)."""
    _seed_user(session)
    gh = _fake_gh()
    responses = _good_responses()
    responses[1] = "not json"  # break the repo_mapper response
    router = _ScriptedRouter(responses)

    result = await investigate(
        user_login="dev", repo_full_name="acme/web", issue_number=42,
        gh=gh, router=router, session=session,
    )
    # Still completed (synthesizer succeeded with degraded inputs)
    assert result.status == "completed"
    assert result.report is not None


@pytest.mark.unit
async def test_investigate_marks_failed_when_synthesizer_raises(session, monkeypatch):
    _seed_user(session)
    gh = _fake_gh()
    router = _ScriptedRouter(_good_responses())

    def _blow_up(*_, **__):
        raise RuntimeError("synthesizer down")

    monkeypatch.setattr("app.agents.investigator.investigator.run_synthesizer", _blow_up)

    result = await investigate(
        user_login="dev", repo_full_name="acme/web", issue_number=42,
        gh=gh, router=router, session=session,
    )
    assert result.status == "failed"
    assert "synthesizer down" in (result.error or "")

    inv = session.execute(select(Investigation)).scalar_one()
    assert inv.status == "failed"
    assert inv.error is not None
