"""GET /users/me/matches — auth-gated + scoped to logged-in user."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models import GsocOrg, Issue, Repo, UserSkill
from app.db.session import VEC_DIM
from app.db.vector import insert_vector

NOW = datetime.now(UTC).replace(tzinfo=None)


def _fake_voyage():
    v = SimpleNamespace()
    v.embed = AsyncMock(side_effect=lambda texts, **_: SimpleNamespace(
        embeddings=[[0.1] * VEC_DIM for _ in texts],
        model="voyage-3-large",
        total_tokens=len(texts) * 10,
    ))
    return v


def _seed_user_skill_and_issues(session, user, *, n_issues: int = 3) -> None:
    session.add(UserSkill(
        user_id=user.id,
        languages=["Python"], frameworks=["FastAPI"], domains=["backend"],
        experience_signal="mid", summary="A backend dev.",
    ))
    session.flush()
    for i in range(n_issues):
        repo = Repo(
            id=100 + i, full_name=f"acme/r{i}", name=f"r{i}",
            html_url=f"https://github.com/acme/r{i}",
            language="Python",
            stargazers_count=500 + i * 100,
            forks_count=20, open_issues_count=5,
            pushed_at=NOW - timedelta(days=1),
            health_score=0.8,
        )
        session.add(repo)
        session.flush()
        issue = Issue(
            id=1000 + i, repo_id=repo.id, number=i + 1,
            title=f"Issue {i}", body=f"Body {i}",
            state="open", labels=["bug"],
            html_url=f"https://github.com/acme/r{i}/issues/{i+1}",
            issue_created_at=NOW - timedelta(days=i + 1),
            issue_updated_at=NOW - timedelta(days=i),
            difficulty=("easy", "medium", "hard")[i % 3],
        )
        session.add(issue)
        session.flush()
        emb = [0.1] * VEC_DIM
        emb[0] = 0.1 + i * 0.05
        insert_vector(session, "issues_vec", issue.id, emb)
    session.commit()


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_matches_requires_auth(client):
    response = client.get("/users/me/matches")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Behavior (with auth)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_matches_requires_voyage_configured(client, make_logged_in_user):
    make_logged_in_user()
    response = client.get("/users/me/matches")
    assert response.status_code == 503
    assert "Voyage" in response.json()["detail"] or "embedder" in response.json()["detail"].lower()


@pytest.mark.unit
def test_matches_returns_409_for_unprofiled_user(client, api_app, make_logged_in_user):
    make_logged_in_user()  # no UserSkill yet
    api_app.state.voyage = _fake_voyage()
    response = client.get("/users/me/matches")
    assert response.status_code == 409
    assert "No skill profile" in response.json()["detail"]


@pytest.mark.unit
def test_matches_returns_ranked_list_without_explain(
    client, api_app, session, make_logged_in_user,
):
    user = make_logged_in_user(github_login="ranker", github_id=99)
    _seed_user_skill_and_issues(session, user, n_issues=3)
    api_app.state.voyage = _fake_voyage()

    response = client.get("/users/me/matches?top=2&explain=false")
    assert response.status_code == 200
    body = response.json()
    assert body["github_login"] == "ranker"
    assert body["count"] == 2
    assert len(body["matches"]) == 2
    scores = [m["final_score"] for m in body["matches"]]
    assert scores == sorted(scores, reverse=True)
    assert all(m["why_it_fits"] is None for m in body["matches"])


@pytest.mark.unit
def test_matches_validates_difficulty(client, api_app, make_logged_in_user):
    make_logged_in_user()
    api_app.state.voyage = _fake_voyage()
    response = client.get("/users/me/matches?difficulty=insane")
    assert response.status_code == 422


@pytest.mark.unit
def test_matches_caps_top_param(client, api_app, make_logged_in_user):
    make_logged_in_user()
    api_app.state.voyage = _fake_voyage()
    response = client.get("/users/me/matches?top=999")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Mode (Batch 20) — general vs gsoc
# ---------------------------------------------------------------------------

def _seed_gsoc_orgs(session, logins, *, year: int = 2025) -> None:
    for slug_login in logins:
        session.add(GsocOrg(
            slug=slug_login, name=slug_login.title(),
            github_login=slug_login,
            primary_languages=["Python"], topics=[],
            years_participated=[year], last_seen_year=year,
        ))
    session.commit()


def _seed_issues_for_owners(session, owners: list[str], *, base_id: int = 200) -> None:
    """Seed one repo + one issue + one vector per owner."""
    for i, owner in enumerate(owners):
        full = f"{owner}/proj{i}"
        repo = Repo(
            id=base_id + i, full_name=full, name=f"proj{i}",
            html_url=f"https://github.com/{full}",
            language="Python", stargazers_count=500,
            forks_count=10, open_issues_count=2,
            pushed_at=NOW - timedelta(days=1),
            health_score=0.8,
        )
        session.add(repo)
        session.flush()
        issue = Issue(
            id=base_id + 1000 + i, repo_id=repo.id, number=i + 1,
            title=f"{owner} issue", body="x",
            state="open", labels=["help wanted"],
            html_url=f"https://github.com/{full}/issues/{i+1}",
            issue_created_at=NOW - timedelta(days=2),
            issue_updated_at=NOW - timedelta(days=1),
            difficulty="easy",
        )
        session.add(issue)
        session.flush()
        emb = [0.1] * VEC_DIM
        emb[0] = 0.1 + i * 0.01
        insert_vector(session, "issues_vec", issue.id, emb)
    session.commit()


@pytest.mark.unit
def test_matches_rejects_invalid_mode(client, api_app, make_logged_in_user):
    make_logged_in_user()
    api_app.state.voyage = _fake_voyage()
    response = client.get("/users/me/matches?mode=invalid")
    assert response.status_code == 422


@pytest.mark.unit
def test_matches_gsoc_mode_filters_to_listed_orgs(
    client, api_app, session, make_logged_in_user,
):
    user = make_logged_in_user(github_login="g", github_id=77)
    session.add(UserSkill(
        user_id=user.id, languages=["Python"], frameworks=[], domains=[],
        experience_signal="mid", summary="Python dev.",
    ))
    session.commit()
    # Issues from one GSoC org + one non-GSoC org
    _seed_issues_for_owners(session, ["apache", "randostartup"])
    _seed_gsoc_orgs(session, ["apache"])
    api_app.state.voyage = _fake_voyage()

    response = client.get("/users/me/matches?top=10&explain=false&mode=gsoc")
    assert response.status_code == 200
    body = response.json()
    repos = {m["repo_full_name"] for m in body["matches"]}
    assert repos == {"apache/proj0"}


@pytest.mark.unit
def test_matches_general_mode_includes_all_orgs(
    client, api_app, session, make_logged_in_user,
):
    user = make_logged_in_user(github_login="g", github_id=77)
    session.add(UserSkill(
        user_id=user.id, languages=["Python"], frameworks=[], domains=[],
        experience_signal="mid", summary="Python dev.",
    ))
    session.commit()
    _seed_issues_for_owners(session, ["apache", "randostartup"])
    _seed_gsoc_orgs(session, ["apache"])
    api_app.state.voyage = _fake_voyage()

    response = client.get("/users/me/matches?top=10&explain=false&mode=general")
    assert response.status_code == 200
    repos = {m["repo_full_name"] for m in response.json()["matches"]}
    assert repos == {"apache/proj0", "randostartup/proj1"}


@pytest.mark.unit
def test_matches_gsoc_mode_returns_empty_when_no_orgs_seeded(
    client, api_app, session, make_logged_in_user,
):
    user = make_logged_in_user(github_login="g", github_id=77)
    session.add(UserSkill(
        user_id=user.id, languages=["Python"], frameworks=[], domains=[],
        experience_signal="mid", summary="Python dev.",
    ))
    session.commit()
    _seed_issues_for_owners(session, ["apache"])  # issues exist
    # but gsoc_orgs is empty
    api_app.state.voyage = _fake_voyage()

    response = client.get("/users/me/matches?explain=false&mode=gsoc")
    assert response.status_code == 200
    assert response.json()["count"] == 0


# ---------------------------------------------------------------------------
# Admin endpoints (no auth required for now)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_admin_stats_returns_zero_when_empty(client):
    response = client.get("/admin/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["users"] == 0
    assert body["issues"] == 0
    assert body["agent_runs"] == 0


@pytest.mark.unit
def test_admin_stats_reflects_seeded_rows(client, session, make_logged_in_user):
    user = make_logged_in_user(github_login="seeded", github_id=99)
    _seed_user_skill_and_issues(session, user, n_issues=2)
    response = client.get("/admin/stats")
    body = response.json()
    assert body["users"] == 1
    assert body["user_skills"] == 1
    assert body["repos"] == 2
    assert body["issues"] == 2
    assert body["issues_with_embeddings"] == 2


@pytest.mark.unit
def test_admin_hunt_requires_all_services(client):
    response = client.post("/admin/hunt", json={"max_total_issues": 10})
    assert response.status_code == 503
