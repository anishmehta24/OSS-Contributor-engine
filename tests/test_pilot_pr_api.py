"""Tests for POST /investigations/{inv}/pilot/{pid}/pr."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.db.models import Investigation, Issue, PilotRun, Repo


def _seed(
    session, user, *,
    pilot_status: str = "accepted",
    pushed: bool = True,
    pr_opened: bool = False,
) -> tuple[Investigation, PilotRun]:
    repo = Repo(
        id=7777, full_name="upstream/foo", name="foo",
        html_url="https://github.com/upstream/foo",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=7700, repo_id=repo.id, number=1, title="t",
        html_url="https://github.com/upstream/foo/issues/1",
        issue_created_at=datetime.now(UTC).replace(tzinfo=None),
        issue_updated_at=datetime.now(UTC).replace(tzinfo=None),
    )
    session.add(issue)
    session.flush()
    inv = Investigation(
        user_id=user.id, issue_id=issue.id, status="completed",
    )
    session.add(inv)
    session.flush()
    now = datetime.now(UTC).replace(tzinfo=None)
    pilot = PilotRun(
        investigation_id=inv.id,
        user_id=user.id,
        status=pilot_status,
        accepted_diff="diff --git a/x b/x\n",
        branch_ref="oss-engine/pilot-deadbeef-issue-1" if pushed else None,
        pushed_at=now if pushed else None,
        pr_url="https://github.com/upstream/foo/pull/9" if pr_opened else None,
        pr_number=9 if pr_opened else None,
        pr_opened_at=now if pr_opened else None,
    )
    session.add(pilot)
    session.commit()
    return inv, pilot


@pytest.fixture
def patched_spawn(monkeypatch):
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
def test_open_pr_requires_auth(client):
    r = client.post("/investigations/x/pilot/y/pr")
    assert r.status_code == 401


@pytest.mark.unit
def test_open_pr_404_for_other_users_pilot(
    client, session, make_logged_in_user, patched_spawn,
):
    make_logged_in_user(github_login="alice", github_id=1)
    from app.db.models import User
    bob = User(github_login="bob", github_id=2, name=None)
    session.add(bob)
    session.flush()
    inv, pilot = _seed(session, bob)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/pr")
    assert r.status_code == 404
    assert not patched_spawn.called


@pytest.mark.unit
def test_open_pr_404_when_missing(client, session, make_logged_in_user, patched_spawn):
    user = make_logged_in_user()
    inv, _ = _seed(session, user)
    r = client.post(f"/investigations/{inv.id}/pilot/does-not-exist/pr")
    assert r.status_code == 404
    assert not patched_spawn.called


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_open_pr_refuses_non_accepted_pilot(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed(session, user, pilot_status="rejected")
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/pr")
    assert r.status_code == 409
    assert "accepted" in r.json()["detail"]
    assert not patched_spawn.called


@pytest.mark.unit
def test_open_pr_refuses_unpushed_pilot(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed(session, user, pushed=False)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/pr")
    assert r.status_code == 409
    assert "push" in r.json()["detail"].lower()
    assert not patched_spawn.called


@pytest.mark.unit
def test_open_pr_refuses_when_pr_already_exists(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed(session, user, pr_opened=True)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/pr")
    assert r.status_code == 409
    assert "already opened" in r.json()["detail"]
    assert "/pull/9" in r.json()["detail"]
    assert not patched_spawn.called


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_open_pr_returns_202_and_spawns_background(
    client, session, make_logged_in_user, patched_spawn,
):
    user = make_logged_in_user()
    inv, pilot = _seed(session, user)
    r = client.post(f"/investigations/{inv.id}/pilot/{pilot.id}/pr")
    assert r.status_code == 202
    body = r.json()
    assert body == {"pilot_id": pilot.id, "status": "pr_queued"}
    assert patched_spawn.call_count == 1


@pytest.mark.unit
def test_pilot_run_row_includes_pr_fields(
    client, session, make_logged_in_user,
):
    user = make_logged_in_user()
    inv, _ = _seed(session, user, pr_opened=True)
    r = client.get(f"/investigations/{inv.id}/pilot")
    assert r.status_code == 200
    body = r.json()
    assert body["pr_url"].endswith("/pull/9")
    assert body["pr_number"] == 9
    assert body["pr_opened_at"] is not None
    assert body["pr_error"] is None
