"""Tests for the pilot pusher.

We focus on the pre-flight + DB-write contract — the actual git
operations are subprocess shellouts we don't want to exercise in unit
tests (they'd need a real GitHub fork). The integration test class
proves the inner-loop helpers do what they say against a local fixture
repo.
"""
from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.patcher.applier import capture_diff
from app.db.models import Investigation, Issue, OAuthToken, PilotRun, Repo
from app.pilot.pusher import (
    PusherError,
    _apply_diff,
    _branch_name,
    _load_context,
    push_pilot_branch,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_chain(
    session, user, *,
    pilot_status: str = "accepted",
    accepted_diff: str | None = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@\n-old\n+new\n",
    pushed_at: datetime | None = None,
) -> tuple[Investigation, PilotRun]:
    """Build a full Investigation -> PilotRun chain for tests that need
    a realistic state to push from."""
    from app.auth.crypto import encrypt_token

    repo = Repo(
        id=42424242, full_name="upstream/widget", name="widget",
        html_url="https://github.com/upstream/widget",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=998877, repo_id=repo.id, number=7, title="Fix the foo bug",
        html_url="https://github.com/upstream/widget/issues/7",
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
    )
    session.add(pilot)
    # User needs an OAuth token row for the decrypt step.
    if session.query(OAuthToken).filter_by(user_id=user.id).first() is None:
        session.add(OAuthToken(
            user_id=user.id,
            encrypted_access_token=encrypt_token("gho_test_token"),
            scopes=["repo"],
        ))
    session.commit()
    return inv, pilot


def _git_init(root: Path, *, with_file: str = "x") -> None:
    """Minimal local repo we can test apply against."""
    (root / "x").write_text("old\n", encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
    ):
        subprocess.run(argv, cwd=root, check=True, capture_output=True)


# ---------------------------------------------------------------------------
# _branch_name + _load_context (pure)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_branch_name_format():
    name = _branch_name("abcdef0123456789", issue_number=42)
    assert name == "oss-engine/pilot-abcdef01-issue-42"
    # Stays deterministic across calls.
    assert _branch_name("abcdef0123456789", issue_number=42) == name


@pytest.mark.unit
def test_load_context_happy_path(session, make_logged_in_user):
    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user)
    ok, ctx = _load_context(session, pilot.id)
    assert ok is True
    assert ctx["repo_full_name"] == "upstream/widget"
    assert ctx["issue_number"] == 7
    assert ctx["issue_title"] == "Fix the foo bug"
    assert ctx["github_login"] == user.github_login
    assert "github_token" in ctx
    # No-reply email format prevents leaking real addresses.
    assert ctx["commit_author_email"].endswith("@users.noreply.github.com")


@pytest.mark.unit
def test_load_context_refuses_non_accepted_pilot(session, make_logged_in_user):
    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user, pilot_status="rejected")
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "accepted" in (pilot.push_error or "")


@pytest.mark.unit
def test_load_context_refuses_already_pushed(session, make_logged_in_user):
    user = make_logged_in_user()
    now = datetime.now(UTC).replace(tzinfo=None)
    _inv, pilot = _seed_chain(session, user, pushed_at=now)
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "already pushed" in (pilot.push_error or "")


@pytest.mark.unit
def test_load_context_refuses_empty_diff(session, make_logged_in_user):
    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user, accepted_diff="")
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "no accepted_diff" in (pilot.push_error or "")


@pytest.mark.unit
def test_load_context_refuses_when_oauth_missing(
    session, make_logged_in_user,
):
    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user)
    # Wipe the token row.
    session.query(OAuthToken).filter_by(user_id=user.id).delete()
    session.commit()
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "OAuth token" in (pilot.push_error or "")


# ---------------------------------------------------------------------------
# _apply_diff (real git, fixture repo)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_apply_diff_against_real_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    # Modify a file so we have something to capture as a diff, then
    # use that diff to round-trip via _apply_diff on a clean copy.
    (repo / "x").write_text("modified\n", encoding="utf-8")
    diff = capture_diff(repo)
    # Revert.
    subprocess.run(
        ["git", "checkout", "x"], cwd=repo, check=True, capture_output=True,
    )
    # Apply our captured diff via the pusher helper.
    _apply_diff(repo, diff)
    assert (repo / "x").read_text(encoding="utf-8") == "modified\n"


@pytest.mark.integration
def test_apply_diff_raises_pusher_error_on_bad_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_init(repo)
    bad_diff = "this is definitely not a unified diff\n"
    with pytest.raises(PusherError, match="git apply"):
        _apply_diff(repo, bad_diff)


# ---------------------------------------------------------------------------
# Top-level push: pre-flight failure short-circuits before forking
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_push_pilot_branch_short_circuits_on_preflight_fail(
    session, make_logged_in_user, engine,
):
    """A pilot in 'rejected' state should never even call the GitHub API."""
    from sqlalchemy.orm import sessionmaker

    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user, pilot_status="rejected")
    sm = sessionmaker(engine, expire_on_commit=False)

    mock_gh = MagicMock(name="GitHubClient")
    with patch("app.pilot.pusher.GitHubClient", return_value=mock_gh):
        await push_pilot_branch(pilot_id=pilot.id, session_factory=sm)

    # GitHub client must NOT have been touched.
    mock_gh.fork_repo.assert_not_called()
    mock_gh.__aenter__.assert_not_called() if hasattr(mock_gh, "__aenter__") else None

    # Error recorded on the row.
    with sm() as s2:
        p = s2.get(PilotRun, pilot.id)
        assert p.push_error is not None
        assert "accepted" in p.push_error
