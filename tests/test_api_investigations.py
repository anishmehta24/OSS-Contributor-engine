"""HTTP-level tests for /investigations — async + SSE + ownership."""
from __future__ import annotations

import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import Investigation, Issue, Repo, User, UserSkill
from app.streaming.events import clear_all
from app.tools.github.models import Issue as GHIssue
from app.tools.github.models import IssueLabel
from app.tools.github.models import Repo as GHRepo

NOW = datetime(2026, 5, 10)


@pytest.fixture(autouse=True)
def _wipe_streaming():
    clear_all()
    yield
    clear_all()


def _scripted_router(responses: list[str]):
    queue = list(responses)
    return SimpleNamespace(
        model_list=[{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
        completion=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=queue.pop(0) if queue else "{}"
            ))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            _hidden_params={"response_cost": 0.0001},
        ),
    )


def _good_responses():
    return [
        '{"summary":"x","requirements":[],"acceptance_criteria":[],"open_questions":[],"technical_keywords":[]}',
        '{"repo_summary":"x","candidate_files":[]}',
        '{"recent_themes":[],"notable_commits":[],"summary":"x"}',
        '{"issue_summary":"x","candidate_files":[],"suggested_approach":"do x","open_questions":[],"risks":[],"estimated_effort":"few-hours"}',
    ]


class _FakeGitHubClient:
    """Class-based fake (SimpleNamespace can't impl async context manager)."""

    def __init__(self, *args, **kwargs):
        self.get_issue = AsyncMock(return_value=GHIssue(
            id=1, number=10, title="t", state="open",
            labels=[IssueLabel(name="bug")],
            html_url="https://x/y/issues/10",
            created_at=NOW, updated_at=NOW,
        ))
        self.get_issue_comments = AsyncMock(return_value=[])
        self.get_repo_tree = AsyncMock(return_value=[
            {"path": "src/a.py", "type": "blob", "size": 100},
        ])
        self.get_recent_commits = AsyncMock(return_value=[])
        self.get_repo = AsyncMock(return_value=GHRepo(
            id=10, full_name="acme/web", name="web",
            html_url="https://x/y",
        ))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def close(self):
        return None


def _patch_global_gh_for_background(api_app):
    """The background task constructs its own GitHubClient; patch the module
    reference so the constructor yields our fake."""
    from app.api.routes import investigations as inv_module

    inv_module.GitHubClient = _FakeGitHubClient


def _poll_until_terminal(client, job_id, *, attempts=30, interval=0.05) -> dict:
    for _ in range(attempts):
        resp = client.get(f"/investigations/{job_id}")
        body = resp.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(interval)
    raise AssertionError(f"Job {job_id} did not finish; last status: {body['status']}")


def _seed_logged_in_with_skill(make_logged_in_user, session, **kw) -> User:
    user = make_logged_in_user(**kw)
    session.add(UserSkill(
        user_id=user.id,
        languages=["Python"], frameworks=["FastAPI"],
        domains=["backend"], experience_signal="mid", summary="x",
    ))
    session.commit()
    return user


# ---------------------------------------------------------------------------
# POST /investigations
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_post_investigation_requires_auth(client):
    response = client.post("/investigations", json={"repo": "a/b", "issue_number": 1})
    assert response.status_code == 401


@pytest.mark.unit
def test_post_investigation_validates_repo_format(
    client, api_app, session, make_logged_in_user,
):
    _seed_logged_in_with_skill(make_logged_in_user, session)
    api_app.state.llm_router = _scripted_router(_good_responses())
    response = client.post("/investigations", json={
        "repo": "bad-no-slash", "issue_number": 1,
    })
    assert response.status_code == 422


@pytest.mark.unit
def test_post_investigation_409_without_profile(
    client, api_app, make_logged_in_user,
):
    make_logged_in_user()  # no skill
    api_app.state.llm_router = _scripted_router(_good_responses())
    response = client.post("/investigations", json={
        "repo": "acme/web", "issue_number": 10,
    })
    assert response.status_code == 409


@pytest.mark.unit
def test_post_investigation_returns_202_with_job_id(
    client, api_app, session, make_logged_in_user,
):
    _seed_logged_in_with_skill(make_logged_in_user, session)
    api_app.state.llm_router = _scripted_router(_good_responses())
    _patch_global_gh_for_background(api_app)

    response = client.post("/investigations", json={
        "repo": "acme/web", "issue_number": 10,
    })
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert len(body["job_id"]) >= 32


@pytest.mark.unit
def test_post_investigation_eventually_completes(
    client, api_app, session, make_logged_in_user,
):
    _seed_logged_in_with_skill(make_logged_in_user, session, github_login="dev")
    api_app.state.llm_router = _scripted_router(_good_responses())
    _patch_global_gh_for_background(api_app)

    post = client.post("/investigations", json={
        "repo": "acme/web", "issue_number": 10,
    })
    job_id = post.json()["job_id"]
    final = _poll_until_terminal(client, job_id)
    assert final["status"] == "completed"
    assert final["markdown_report"]


# ---------------------------------------------------------------------------
# GET /investigations/{id} — ownership
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_unknown_id_returns_synthetic_queued_when_authed(client, make_logged_in_user):
    make_logged_in_user()
    response = client.get("/investigations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"


@pytest.mark.unit
def test_get_investigation_requires_auth(client):
    response = client.get("/investigations/abc")
    assert response.status_code == 401


@pytest.mark.unit
def test_get_investigation_owned_by_me_returns_row(client, session, make_logged_in_user):
    user = make_logged_in_user()
    repo = Repo(id=1, full_name="x/y", name="y", html_url="https://...")
    session.add(repo)
    session.flush()
    issue = Issue(
        id=1, repo_id=repo.id, number=10, title="t",
        html_url="https://...", issue_created_at=NOW, issue_updated_at=NOW,
    )
    session.add(issue)
    session.flush()
    inv = Investigation(
        user_id=user.id, issue_id=issue.id,
        status="completed", report_md="# Report\nbody",
    )
    session.add(inv)
    session.commit()
    response = client.get(f"/investigations/{inv.id}")
    assert response.status_code == 200
    assert "Report" in response.json()["markdown_report"]


@pytest.mark.unit
def test_get_investigation_owned_by_another_user_returns_404(
    client, session, make_logged_in_user,
):
    make_logged_in_user(github_login="me", github_id=1)
    other = User(github_login="other", github_id=2)
    repo = Repo(id=1, full_name="x/y", name="y", html_url="https://...")
    session.add_all([other, repo])
    session.flush()
    issue = Issue(
        id=1, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=NOW, issue_updated_at=NOW,
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=other.id, issue_id=issue.id, status="completed")
    session.add(inv)
    session.commit()

    response = client.get(f"/investigations/{inv.id}")
    assert response.status_code == 404  # don't leak existence


# ---------------------------------------------------------------------------
# Listing — scoped to current user
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_list_investigations_empty(client, make_logged_in_user):
    make_logged_in_user()
    assert client.get("/investigations").json() == []


@pytest.mark.unit
def test_list_investigations_only_returns_mine(client, session, make_logged_in_user):
    me = make_logged_in_user(github_login="me", github_id=1)
    other = User(github_login="other", github_id=2)
    repo = Repo(id=1, full_name="x/y", name="y", html_url="https://...")
    session.add_all([other, repo])
    session.flush()
    issue = Issue(
        id=1, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=NOW, issue_updated_at=NOW,
    )
    session.add(issue)
    session.flush()
    session.add(Investigation(user_id=me.id, issue_id=issue.id, status="completed"))
    session.add(Investigation(user_id=other.id, issue_id=issue.id, status="completed"))
    session.commit()

    rows = client.get("/investigations").json()
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_stream_requires_auth(client):
    with client.stream("GET", "/investigations/abc/stream") as r:
        assert r.status_code == 401


@pytest.mark.unit
def test_stream_returns_terminal_event_for_already_completed(
    client, session, make_logged_in_user,
):
    user = make_logged_in_user()
    repo = Repo(id=1, full_name="x/y", name="y", html_url="https://...")
    session.add(repo)
    session.flush()
    issue = Issue(
        id=1, repo_id=repo.id, number=10, title="t",
        html_url="https://...", issue_created_at=NOW, issue_updated_at=NOW,
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=user.id, issue_id=issue.id, status="completed")
    session.add(inv)
    session.commit()

    with client.stream("GET", f"/investigations/{inv.id}/stream") as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert "investigation_completed" in body


@pytest.mark.unit
def test_stream_404s_for_other_users_investigation(
    client, session, make_logged_in_user,
):
    make_logged_in_user(github_login="me", github_id=1)
    other = User(github_login="other", github_id=2)
    repo = Repo(id=1, full_name="x/y", name="y", html_url="https://...")
    session.add_all([other, repo])
    session.flush()
    issue = Issue(
        id=1, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=NOW, issue_updated_at=NOW,
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=other.id, issue_id=issue.id, status="completed")
    session.add(inv)
    session.commit()

    with client.stream("GET", f"/investigations/{inv.id}/stream") as r:
        assert r.status_code == 404
