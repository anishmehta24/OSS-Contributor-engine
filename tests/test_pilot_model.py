"""Schema + ORM tests for PilotRun."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import Investigation, Issue, PilotRun, Repo, User


def _seed_inv(session, user: User) -> Investigation:
    """Create a minimal investigation chain so PilotRun has a FK target."""
    repo = Repo(
        id=999, full_name="acme/widget", name="widget",
        html_url="https://github.com/acme/widget",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=1234, repo_id=repo.id, number=42, title="x",
        html_url="https://github.com/acme/widget/issues/42",
        issue_created_at=__import__("datetime").datetime.utcnow(),
        issue_updated_at=__import__("datetime").datetime.utcnow(),
    )
    session.add(issue)
    session.flush()
    inv = Investigation(
        user_id=user.id, issue_id=issue.id, status="completed",
        report_md="# report",
    )
    session.add(inv)
    session.commit()
    return inv


@pytest.mark.unit
def test_pilot_run_round_trip(session, make_logged_in_user):
    user = make_logged_in_user(github_login="pilot-user", github_id=77)
    inv = _seed_inv(session, user)

    p = PilotRun(
        investigation_id=inv.id,
        user_id=user.id,
        status="queued",
    )
    session.add(p)
    session.commit()

    row = session.execute(
        select(PilotRun).where(PilotRun.id == p.id),
    ).scalar_one()
    assert row.investigation_id == inv.id
    assert row.status == "queued"
    assert row.attempts_made == 0
    assert row.id is not None  # UUID assigned by default


@pytest.mark.unit
def test_pilot_cascade_on_investigation_delete(session, make_logged_in_user):
    user = make_logged_in_user(github_login="pilot-cascade", github_id=78)
    inv = _seed_inv(session, user)
    p = PilotRun(investigation_id=inv.id, user_id=user.id, status="queued")
    session.add(p)
    session.commit()
    pilot_id = p.id

    session.delete(inv)
    session.commit()

    gone = session.execute(
        select(PilotRun).where(PilotRun.id == pilot_id),
    ).scalar_one_or_none()
    assert gone is None  # cascade fired
