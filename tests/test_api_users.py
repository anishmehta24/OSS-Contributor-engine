"""Users endpoints — /me only after v2.

All endpoints require auth. Logged-in users can only operate on themselves.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import User, UserSkill
from app.tools.github.models import Repo as GHRepo
from app.tools.github.models import User as GHUser

NOW = datetime(2026, 5, 10)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_gh_user(login="dev") -> GHUser:
    return GHUser(
        id=42, login=login, name="Dev",
        html_url=f"https://github.com/{login}",
        public_repos=2, bio="I write code", company=None,
    )


def _fake_gh_repos(login="dev"):
    return [
        GHRepo(
            id=1, full_name=f"{login}/web", name="web",
            description="A FastAPI app", language="Python",
            html_url=f"https://github.com/{login}/web",
            stargazers_count=10, fork=False, archived=False,
            pushed_at=NOW,
        ),
    ]


def _patch_user_gh_dep(api_app, login="dev"):
    """Make the per-user GitHub client dep return a fake."""
    from app.api.dependencies import get_user_github_client

    fake_gh = SimpleNamespace()
    fake_gh.get_user = AsyncMock(return_value=_fake_gh_user(login=login))
    fake_gh.get_user_repos = AsyncMock(return_value=_fake_gh_repos(login=login))
    fake_gh.get_repo_languages = AsyncMock(return_value={"Python": 5000})
    fake_gh.get_repo_file = AsyncMock(return_value='[project]\ndependencies = ["fastapi"]\n')
    fake_gh.get_recent_commits = AsyncMock(return_value=[])
    fake_gh.close = AsyncMock(return_value=None)

    async def _override():
        yield fake_gh

    api_app.dependency_overrides[get_user_github_client] = _override
    return fake_gh


def _fake_router(json_str: str = '{"domains": ["backend"], "experience_signal": "mid", "summary": "ok"}'):
    return SimpleNamespace(
        model_list=[{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
        completion=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json_str))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=30),
            _hidden_params={"response_cost": 0.0001},
        ),
    )


# ---------------------------------------------------------------------------
# Auth-required behavior
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_all_me_endpoints_require_auth(client):
    """No session cookie → 401 across the board."""
    assert client.post("/users/me/profile").status_code == 401
    assert client.get("/users/me").status_code == 401
    assert client.get("/users/me/summary").status_code == 401
    assert client.delete("/users/me").status_code == 401


# ---------------------------------------------------------------------------
# POST /users/me/profile
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_profile_me_creates_and_returns_profile(client, api_app, make_logged_in_user):
    make_logged_in_user(github_login="dev", github_id=42)
    _patch_user_gh_dep(api_app, login="dev")
    api_app.state.llm_router = _fake_router()

    response = client.post("/users/me/profile")
    assert response.status_code == 201
    profile = response.json()["profile"]
    assert profile["github_login"] == "dev"
    assert "Python" in profile["languages"]
    assert profile["domains"] == ["backend"]


# ---------------------------------------------------------------------------
# GET /users/me
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_me_409_when_no_profile_yet(client, make_logged_in_user):
    make_logged_in_user()
    response = client.get("/users/me")
    assert response.status_code == 409


@pytest.mark.unit
def test_get_me_returns_cached_profile(client, session, make_logged_in_user):
    user = make_logged_in_user(github_login="cached", github_id=7)
    session.add(UserSkill(
        user_id=user.id,
        languages=["Go"], frameworks=["echo"], domains=["backend"],
        experience_signal="senior",
        summary="A Go backend developer.",
    ))
    session.commit()

    response = client.get("/users/me")
    assert response.status_code == 200
    profile = response.json()["profile"]
    assert profile["github_login"] == "cached"
    assert profile["experience_signal"] == "senior"


# ---------------------------------------------------------------------------
# GET /users/me/summary
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_summary_returns_basic_user_info(client, make_logged_in_user):
    make_logged_in_user(github_login="alice", github_id=11, name="Alice")
    response = client.get("/users/me/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["github_login"] == "alice"
    assert body["has_skill_profile"] is False


# ---------------------------------------------------------------------------
# DELETE /users/me
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_delete_me_removes_row(client, session, make_logged_in_user):
    from sqlalchemy import select

    make_logged_in_user(github_login="kill")
    response = client.delete("/users/me")
    assert response.status_code == 204

    found = session.execute(
        select(User).where(User.github_login == "kill")
    ).scalar_one_or_none()
    assert found is None
