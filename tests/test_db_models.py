"""CRUD + relationship + constraint tests for the ORM models."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AgentRun,
    Investigation,
    Issue,
    Repo,
    User,
    UserSkill,
)

# ---------------------------------------------------------------------------
# User + UserSkill
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_user_create_and_fetch(session):
    user = User(github_login="octocat", github_id=583231, name="The Octocat")
    session.add(user)
    session.commit()

    fetched = session.execute(select(User).where(User.github_login == "octocat")).scalar_one()
    assert fetched.id is not None
    assert fetched.github_id == 583231
    assert fetched.created_at is not None


@pytest.mark.unit
def test_user_login_is_unique(session):
    session.add(User(github_login="dup", github_id=1))
    session.commit()
    session.add(User(github_login="dup", github_id=2))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.unit
def test_user_skill_one_to_one(session):
    user = User(github_login="alice", github_id=100)
    session.add(user)
    session.flush()

    skill = UserSkill(
        user_id=user.id,
        languages=["Python", "Go"],
        frameworks=["FastAPI"],
        domains=["backend"],
        experience_signal="mid",
        summary="Backend engineer with Go + Python.",
    )
    session.add(skill)
    session.commit()

    fetched = session.execute(select(User).where(User.id == user.id)).scalar_one()
    session.refresh(fetched, ["skill"])
    assert fetched.skill is not None
    assert fetched.skill.languages == ["Python", "Go"]
    assert fetched.skill.frameworks == ["FastAPI"]


@pytest.mark.unit
def test_user_skill_user_id_is_unique(session):
    user = User(github_login="bob", github_id=200)
    session.add(user)
    session.flush()
    session.add(UserSkill(user_id=user.id, languages=[], frameworks=[], domains=[]))
    session.commit()
    session.add(UserSkill(user_id=user.id, languages=[], frameworks=[], domains=[]))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------------------------------------------------------------------------
# Repo + Issue
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_repo_and_issue_with_relationship(session):
    repo = Repo(
        id=12345,
        full_name="fastapi/fastapi",
        name="fastapi",
        language="Python",
        stargazers_count=75000,
        html_url="https://github.com/fastapi/fastapi",
        topics=["python", "api"],
    )
    session.add(repo)
    session.flush()

    now = datetime.utcnow()
    session.add_all([
        Issue(
            id=1, repo_id=repo.id, number=1, title="bug",
            html_url="https://...", labels=["bug"],
            issue_created_at=now, issue_updated_at=now,
        ),
        Issue(
            id=2, repo_id=repo.id, number=2, title="feature",
            html_url="https://...", labels=["enhancement"],
            issue_created_at=now, issue_updated_at=now,
        ),
    ])
    session.commit()

    repo_fetched = session.execute(select(Repo).where(Repo.id == 12345)).scalar_one()
    session.refresh(repo_fetched, ["issues"])
    assert len(repo_fetched.issues) == 2
    assert {i.title for i in repo_fetched.issues} == {"bug", "feature"}


@pytest.mark.unit
def test_issue_repo_number_is_unique(session):
    repo = Repo(
        id=1, full_name="x/y", name="y", html_url="https://...", language="Python",
    )
    session.add(repo)
    session.flush()
    now = datetime.utcnow()
    session.add(Issue(
        id=1, repo_id=repo.id, number=10, title="a",
        html_url="https://...", issue_created_at=now, issue_updated_at=now,
    ))
    session.commit()
    session.add(Issue(
        id=2, repo_id=repo.id, number=10, title="b",
        html_url="https://...", issue_created_at=now, issue_updated_at=now,
    ))
    with pytest.raises(IntegrityError):
        session.commit()


# ---------------------------------------------------------------------------
# Investigation + AgentRun
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_investigation_with_agent_runs_cascade(session):
    user = User(github_login="charlie", github_id=300)
    repo = Repo(id=99, full_name="x/z", name="z", html_url="https://...")
    session.add_all([user, repo])
    session.flush()
    now = datetime.utcnow()
    issue = Issue(
        id=42, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=now, issue_updated_at=now,
    )
    session.add(issue)
    session.flush()

    inv = Investigation(user_id=user.id, issue_id=issue.id, status="running")
    session.add(inv)
    session.flush()

    session.add_all([
        AgentRun(
            investigation_id=inv.id, agent_name="repo_mapper",
            provider="gemini", model="gemini-2.5-flash",
            tokens_in=100, tokens_out=200, cost_usd=0.001, latency_ms=1500,
        ),
        AgentRun(
            investigation_id=inv.id, agent_name="synthesizer",
            provider="groq", model="llama-3.3-70b",
            fallback_depth=1,
            tokens_in=300, tokens_out=400, cost_usd=0.0, latency_ms=900,
        ),
    ])
    session.commit()

    fetched = session.execute(
        select(Investigation).where(Investigation.id == inv.id)
    ).scalar_one()
    session.refresh(fetched, ["agent_runs"])
    assert len(fetched.agent_runs) == 2

    # cascade delete: deleting the investigation removes its agent_runs
    session.delete(fetched)
    session.commit()
    remaining = session.execute(select(AgentRun)).all()
    assert remaining == []


@pytest.mark.unit
def test_investigation_status_default_queued(session):
    user = User(github_login="d", github_id=400)
    repo = Repo(id=2, full_name="d/d", name="d", html_url="https://...")
    session.add_all([user, repo])
    session.flush()
    now = datetime.utcnow()
    issue = Issue(
        id=2, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=now, issue_updated_at=now,
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=user.id, issue_id=issue.id)
    session.add(inv)
    session.commit()
    assert inv.status == "queued"
    assert inv.id  # uuid populated


@pytest.mark.unit
def test_user_deletion_cascades_to_skill_and_investigations(session):
    user = User(github_login="e", github_id=500)
    repo = Repo(id=3, full_name="e/e", name="e", html_url="https://...")
    session.add_all([user, repo])
    session.flush()
    now = datetime.utcnow()
    issue = Issue(
        id=3, repo_id=repo.id, number=1, title="t",
        html_url="https://...", issue_created_at=now, issue_updated_at=now,
    )
    session.add_all([
        issue,
        UserSkill(user_id=user.id, languages=[], frameworks=[], domains=[]),
    ])
    session.flush()
    inv = Investigation(user_id=user.id, issue_id=issue.id)
    session.add(inv)
    session.commit()

    session.delete(user)
    session.commit()
    assert session.execute(select(UserSkill)).all() == []
    assert session.execute(select(Investigation)).all() == []
    # Repo and Issue should remain (independent of user lifecycle).
    assert session.execute(select(Repo)).first() is not None
    assert session.execute(select(Issue)).first() is not None


# ---------------------------------------------------------------------------
# JSON column round-trip
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_json_columns_round_trip(session):
    user = User(github_login="f", github_id=600)
    session.add(user)
    session.flush()
    skill = UserSkill(
        user_id=user.id,
        languages=["Python", "Rust"],
        frameworks=["FastAPI", "Tokio"],
        domains=["systems"],
    )
    session.add(skill)
    session.commit()

    session.expire_all()
    fetched = session.execute(select(UserSkill).where(UserSkill.user_id == user.id)).scalar_one()
    assert fetched.languages == ["Python", "Rust"]
    assert fetched.frameworks == ["FastAPI", "Tokio"]
    assert fetched.domains == ["systems"]


@pytest.mark.unit
def test_timestamps_auto_populated(session):
    user = User(github_login="g", github_id=700)
    session.add(user)
    session.commit()
    assert user.created_at is not None
    assert user.updated_at is not None
    delta = abs((user.updated_at - user.created_at).total_seconds())
    assert delta < 1.0


@pytest.mark.unit
def test_updated_at_changes_on_update(session):
    user = User(github_login="h", github_id=800)
    session.add(user)
    session.commit()
    original_updated = user.updated_at
    # SQLite's CURRENT_TIMESTAMP has 1-second resolution; sleep to guarantee a tick.
    time.sleep(1.1)
    user.name = "New Name"
    session.commit()
    assert user.updated_at >= original_updated + timedelta(seconds=1)
