"""End-to-end Skill Profiler tests with mocked GitHub + mocked LLM."""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agents.profiles.schemas import LLMSynthesis, RepoSignal
from app.agents.profiles.skill_profiler import (
    aggregate_frameworks,
    aggregate_languages,
    profile_user,
    upsert_user_and_skill,
)
from app.db.models import User
from app.tools.github.models import Repo
from app.tools.github.models import User as GHUser

# ---------------------------------------------------------------------------
# Pure aggregation tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_aggregate_languages_sums_bytes_across_repos():
    signals = [
        RepoSignal(full_name="a/b", languages={"Python": 1000, "TypeScript": 500}, html_url="x"),
        RepoSignal(full_name="a/c", languages={"Python": 2000, "Rust": 300}, html_url="x"),
    ]
    # Python:3000, TypeScript:500, Rust:300
    assert aggregate_languages(signals) == ["Python", "TypeScript", "Rust"]


@pytest.mark.unit
def test_aggregate_frameworks_counts_occurrences():
    signals = [
        RepoSignal(full_name="a/b", frameworks=["fastapi", "pytest"], html_url="x"),
        RepoSignal(full_name="a/c", frameworks=["fastapi", "pydantic"], html_url="x"),
        RepoSignal(full_name="a/d", frameworks=["pytest"], html_url="x"),
    ]
    result = aggregate_frameworks(signals)
    # fastapi:2, pytest:2, pydantic:1
    assert result[:2] == ["fastapi", "pytest"] or result[:2] == ["pytest", "fastapi"]
    assert "pydantic" in result


@pytest.mark.unit
def test_aggregate_languages_empty():
    assert aggregate_languages([]) == []


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_upsert_user_and_skill_creates_new(session):
    user = upsert_user_and_skill(
        session,
        github_login="newbie", github_id=999, name="Newbie",
        languages=["Python"], frameworks=["fastapi"],
        domains=["backend"], experience_signal="mid", summary="A backend dev.",
    )
    assert user.id is not None
    assert user.skill is not None
    assert user.skill.languages == ["Python"]
    assert user.skill.summary == "A backend dev."


@pytest.mark.unit
def test_upsert_user_and_skill_updates_existing(session):
    upsert_user_and_skill(
        session,
        github_login="dup", github_id=1, name=None,
        languages=["Python"], frameworks=[], domains=[], experience_signal=None, summary=None,
    )
    upsert_user_and_skill(
        session,
        github_login="dup", github_id=1, name="Now Has Name",
        languages=["Go", "Python"], frameworks=["echo"],
        domains=["backend"], experience_signal="senior", summary="Updated.",
    )
    users = session.execute(select(User).where(User.github_login == "dup")).scalars().all()
    assert len(users) == 1
    user = users[0]
    assert user.name == "Now Has Name"
    assert user.skill.languages == ["Go", "Python"]
    assert user.skill.summary == "Updated."


# ---------------------------------------------------------------------------
# End-to-end with mocks
# ---------------------------------------------------------------------------

class _FakeGH:
    """Mocks just the GitHubClient methods the profiler calls."""

    def __init__(self):
        self.get_user = AsyncMock(return_value=GHUser(
            id=42, login="testuser", name="Test User",
            html_url="https://github.com/testuser",
            public_repos=2, bio="I write code", company="Acme",
        ))
        repo1 = Repo(
            id=1, full_name="testuser/web-app", name="web-app",
            description="A FastAPI service",
            language="Python",
            html_url="https://github.com/testuser/web-app",
            stargazers_count=10, fork=False, archived=False,
            pushed_at=datetime(2025, 1, 1),
        )
        repo2 = Repo(
            id=2, full_name="testuser/cli-tool", name="cli-tool",
            description="A Go CLI",
            language="Go",
            html_url="https://github.com/testuser/cli-tool",
            stargazers_count=5, fork=False, archived=False,
            pushed_at=datetime(2024, 12, 1),
        )
        self.get_user_repos = AsyncMock(return_value=[repo1, repo2])
        self.get_repo_languages = AsyncMock(side_effect=[
            {"Python": 5000, "HTML": 200},
            {"Go": 3000},
        ])

        async def _get_repo_file(full_name, path, ref=None):
            if full_name == "testuser/web-app" and path == "pyproject.toml":
                return '[project]\ndependencies = ["fastapi", "sqlalchemy"]\n'
            if full_name == "testuser/cli-tool" and path == "go.mod":
                return "module x\nrequire github.com/spf13/cobra v1.8.0\n"
            return None

        self.get_repo_file = AsyncMock(side_effect=_get_repo_file)
        self.get_recent_commits = AsyncMock(return_value=[])


class _FakeLLMRouter:
    """Returns canned synthesis JSON; counts calls."""

    def __init__(self, json_str: str):
        self._json = json_str
        self.call_count = 0
        self.model_list = [{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}]

    def completion(self, **_):
        self.call_count += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._json))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80),
            _hidden_params={"response_cost": 0.0002},
        )


@pytest.mark.unit
async def test_profile_user_end_to_end_with_mocks(session):
    gh = _FakeGH()
    router = _FakeLLMRouter(
        '{"domains": ["backend"], "experience_signal": "mid", '
        '"summary": "A backend developer with FastAPI and Go experience."}'
    )

    profile = await profile_user("testuser", gh=gh, router=router, session=session)

    assert profile.github_login == "testuser"
    assert profile.github_id == 42
    assert profile.repos_analyzed == 2
    # Languages aggregated from /languages endpoint, ordered by bytes
    assert "Python" in profile.languages
    assert "Go" in profile.languages
    # Frameworks from manifests
    assert "fastapi" in profile.frameworks
    assert "github.com/spf13/cobra" in profile.frameworks
    # LLM-synthesized fields
    assert profile.domains == ["backend"]
    assert profile.experience_signal == "mid"
    assert profile.summary.startswith("A backend developer")

    # Persistence
    user = session.execute(select(User).where(User.github_login == "testuser")).scalar_one()
    assert user.skill is not None
    assert user.skill.domains == ["backend"]
    assert user.skill.summary.startswith("A backend developer")


@pytest.mark.unit
async def test_profile_user_handles_llm_parse_failure(session):
    gh = _FakeGH()
    router = _FakeLLMRouter("not valid json")

    profile = await profile_user("testuser", gh=gh, router=router, session=session)

    # Deterministic fields still populated
    assert profile.languages
    assert profile.frameworks
    # Synthesis fields fall back to defaults
    assert profile.domains == []
    assert profile.experience_signal is None
    assert profile.summary is None


@pytest.mark.unit
async def test_profile_user_skips_persistence_when_no_session():
    gh = _FakeGH()
    router = _FakeLLMRouter(
        '{"domains": ["backend"], "experience_signal": "mid", "summary": "ok"}'
    )
    profile = await profile_user("testuser", gh=gh, router=router, session=None)
    assert profile.summary == "ok"
    assert router.call_count == 1


@pytest.mark.unit
async def test_profile_user_filters_forks_and_archived(session):
    gh = _FakeGH()
    fork = Repo(
        id=3, full_name="testuser/forked", name="forked",
        html_url="x", fork=True, archived=False,
    )
    archived = Repo(
        id=4, full_name="testuser/old", name="old",
        html_url="x", fork=False, archived=True,
    )
    real_repo = Repo(
        id=5, full_name="testuser/real", name="real",
        html_url="x", fork=False, archived=False,
        language="Python",
    )
    gh.get_user_repos = AsyncMock(return_value=[fork, archived, real_repo])
    gh.get_repo_languages = AsyncMock(return_value={"Python": 100})
    gh.get_repo_file = AsyncMock(return_value=None)
    gh.get_recent_commits = AsyncMock(return_value=[])

    router = _FakeLLMRouter('{"domains": [], "experience_signal": "junior", "summary": "x"}')
    profile = await profile_user("testuser", gh=gh, router=router, session=session)
    assert profile.repos_analyzed == 1


@pytest.mark.unit
def test_llm_synthesis_schema_validates():
    LLMSynthesis(
        domains=["backend", "ML"],
        experience_signal="mid",
        summary="ok",
    )
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LLMSynthesis(
            domains=[], experience_signal="god-tier", summary="x",
        )
