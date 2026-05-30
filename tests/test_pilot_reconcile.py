"""Tests for startup reconciliation of orphaned pilots."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import Investigation, Issue, PilotRun, Repo
from app.pilot import reconcile_orphaned_pilots


def _seed_inv(session, user) -> Investigation:
    repo = Repo(
        id=8800, full_name="acme/recon", name="recon",
        html_url="https://github.com/acme/recon",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=8801, repo_id=repo.id, number=1, title="t",
        html_url="https://github.com/acme/recon/issues/1",
        issue_created_at=datetime.now(UTC).replace(tzinfo=None),
        issue_updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(issue)
    session.flush()
    inv = Investigation(user_id=user.id, issue_id=issue.id, status="completed")
    session.add(inv)
    session.commit()
    return inv


@pytest.mark.unit
def test_reconciles_queued_and_running(session, engine, make_logged_in_user):
    user = make_logged_in_user()
    inv = _seed_inv(session, user)
    for st in ("queued", "running"):
        session.add(PilotRun(
            investigation_id=inv.id, user_id=user.id, status=st,
        ))
    session.commit()

    sm = sessionmaker(engine, expire_on_commit=False)
    n = reconcile_orphaned_pilots(sm)
    assert n == 2

    # Both now failed, with an explanatory error + completed_at set.
    with sm() as s:
        rows = s.query(PilotRun).all()
        assert all(r.status == "failed" for r in rows)
        assert all("orphaned" in (r.error or "") for r in rows)
        assert all(r.completed_at is not None for r in rows)


@pytest.mark.unit
def test_does_not_touch_terminal_pilots(session, engine, make_logged_in_user):
    user = make_logged_in_user()
    inv = _seed_inv(session, user)
    accepted = PilotRun(
        investigation_id=inv.id, user_id=user.id, status="accepted",
        summary="good", accepted_diff="diff",
    )
    rejected = PilotRun(
        investigation_id=inv.id, user_id=user.id, status="rejected",
        summary="nope",
    )
    failed = PilotRun(
        investigation_id=inv.id, user_id=user.id, status="failed",
        error="boom",
    )
    session.add_all([accepted, rejected, failed])
    session.commit()

    sm = sessionmaker(engine, expire_on_commit=False)
    n = reconcile_orphaned_pilots(sm)
    assert n == 0

    with sm() as s:
        statuses = {r.id: r.status for r in s.query(PilotRun).all()}
        assert statuses[accepted.id] == "accepted"
        assert statuses[rejected.id] == "rejected"
        assert statuses[failed.id] == "failed"
        # The pre-existing failed pilot's error wasn't appended to.
        f = s.get(PilotRun, failed.id)
        assert f.error == "boom"


@pytest.mark.unit
def test_noop_on_empty_db(engine):
    sm = sessionmaker(engine, expire_on_commit=False)
    assert reconcile_orphaned_pilots(sm) == 0


@pytest.mark.unit
def test_preserves_existing_error_text(session, engine, make_logged_in_user):
    user = make_logged_in_user()
    inv = _seed_inv(session, user)
    session.add(PilotRun(
        investigation_id=inv.id, user_id=user.id, status="running",
        error="explorer was mid-flight",
    ))
    session.commit()

    sm = sessionmaker(engine, expire_on_commit=False)
    reconcile_orphaned_pilots(sm)
    with sm() as s:
        r = s.query(PilotRun).one()
        # Original context kept, orphan note appended.
        assert "explorer was mid-flight" in r.error
        assert "orphaned" in r.error
