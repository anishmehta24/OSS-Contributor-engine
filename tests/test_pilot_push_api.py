"""Tests for POST /investigations/{inv}/pilot/{pid}/push."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models import Investigation, Issue, PilotRun, Repo


def _seed_chain(
    session, user, *,
    pilot_status: str = "accepted",
    accepted_diff: str | None = "diff --git a/x b/x\n",
    pushed_at: datetime | None = None,
) -> tuple[Investigation, PilotRun]:
    repo = Repo(
        id=88, full_name="upstream/foo", name="foo",
        html_url="https://github.com/upstream/foo",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=88001, repo_id=repo.id, number=11, title="bug",
        html_url="https://github.com/upstream/foo/issues/11",
        issue_created_at=datetime.now(UTC).replace(tzinfo=None),
        issue_updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(issue)
    session.flush()
    inv = Investigation(
        user_id=user.id, issue_id=issue.id, status="completed",
        report_md="# r",
    )
    session.add(inv)
    session.flush()
    pilot = PilotRun(
        investigation_id=inv.id,
        user_id=user.id,
        status=pilot_status,
        accepted_diff=accepted_diff,
        pushed_at=pushed_at,
        branch_ref="oss-engine/pilot-deadbeef-issue-11" if pushed_at else None,
    )
    session.add(pilot)
    session.commit()
    return inv, pilot


@pytest.fixture
def patched_spawn(monkeypatch):
    """Stub out the push background spawn; close the coroutine to avoid
    'never awaited' warnings."""
    mock = MagicMock()

    def _capture(coro, *args, **kwargs):
        if hasattr(coro, "close"):
            coro.close()
        return mock(coro, *args, **kwargs)

    monkeypatch.setattr("app.api.routes.pilot.spawn", _capture)
    return mock


# ---------------------------------------------------------------------------
# Auth + ownership
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_push_requires_auth(client):
    r = client.post("/investigations/x/pilot/y/push")
    assert r.status_code == 401


@pytest.mark.unit
def test_push_404_for_other_users_pilot(
    client, session, make_logged_in_user, patched_spawn,
):
    make_logged_in_user(github_login="alice", github_id=1)
    from app.db.models import User
    bob = User(github_login="bob", github_id=2, name=None)
    session.add(bob)
    session.flush()
    inv, pilot = _seed_chain(session, bob)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/push")
    # 404 not 403 — no existence leak.
    assert r.status_code == 404
    assert not patched_spawn.called


@pytest.mark.unit
def test_push_404_when_pilot_missing(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, _ = _seed_chain(session, user)
    r = client.post(f"/investigations/{inv.id}/pilot/does-not-exist/push")
    assert r.status_code == 404
    assert not patched_spawn.called


@pytest.mark.unit
def test_push_404_when_pilot_belongs_to_other_investigation(
    client, session, make_logged_in_user, patched_spawn,
):
    """Pilot exists but is attached to a different investigation."""
    user = make_logged_in_user()
    _inv_a, pilot = _seed_chain(session, user)
    # Build a second, unrelated investigation under the same user.
    repo = Repo(
        id=99, full_name="other/bar", name="bar",
        html_url="https://github.com/other/bar",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=99001, repo_id=repo.id, number=1, title="x",
        html_url="https://github.com/other/bar/issues/1",
        issue_created_at=datetime.now(UTC).replace(tzinfo=None),
        issue_updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(issue)
    session.flush()
    other_inv = Investigation(
        user_id=user.id, issue_id=issue.id, status="completed",
    )
    session.add(other_inv)
    session.commit()

    r = client.post(f"/investigations/{other_inv.id}/pilot/{pilot.id}/push")
    assert r.status_code == 404
    assert not patched_spawn.called


# ---------------------------------------------------------------------------
# Precondition checks
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_push_refuses_non_accepted_pilot(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed_chain(session, user, pilot_status="rejected")
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/push")
    assert r.status_code == 409
    assert "accepted" in r.json()["detail"]
    assert not patched_spawn.called


@pytest.mark.unit
def test_push_refuses_already_pushed(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    now = datetime.now(UTC).replace(tzinfo=None)
    inv, pilot = _seed_chain(session, user, pushed_at=now)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/push")
    assert r.status_code == 409
    assert "already pushed" in r.json()["detail"]
    assert "oss-engine/pilot" in r.json()["detail"]
    assert not patched_spawn.called


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_push_returns_202_and_spawns_background(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed_chain(session, user)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/push")
    assert r.status_code == 202
    body = r.json()
    assert body == {"pilot_id": pilot.id, "status": "push_queued"}
    assert patched_spawn.call_count == 1


# ---------------------------------------------------------------------------
# Serialization includes push fields
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pilot_run_row_includes_push_fields(
    client, session, make_logged_in_user,
):
    user = make_logged_in_user()
    now = datetime.now(UTC).replace(tzinfo=None)
    inv, pilot = _seed_chain(session, user, pushed_at=now)
    pilot.fork_url = "https://github.com/dev/foo"
    session.commit()

    r = client.get(f"/investigations/{inv.id}/pilot")
    assert r.status_code == 200
    body = r.json()
    assert body["fork_url"] == "https://github.com/dev/foo"
    assert body["branch_ref"] == "oss-engine/pilot-deadbeef-issue-11"
    assert body["pushed_at"] is not None
    assert body["push_error"] is None
