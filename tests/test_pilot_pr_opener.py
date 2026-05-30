"""Tests for app.pilot.pr_opener.

Covers:
  - Pre-flight: refuses non-accepted / non-pushed / already-PRed pilots
  - Title + body builders (pure)
  - Defensive transcript parsing (missing fields, corrupt JSON)
  - Top-level short-circuits before touching the GitHub API on bad input
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import Investigation, Issue, OAuthToken, PilotRun, Repo
from app.pilot.pr_opener import (
    _build_body,
    _build_title,
    _load_context,
    open_pilot_pr,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _seed_chain(
    session, user, *,
    pilot_status: str = "accepted",
    pushed: bool = True,
    pr_opened: bool = False,
    transcript_json: str | None = None,
) -> tuple[Investigation, PilotRun]:
    from app.auth.crypto import encrypt_token

    repo = Repo(
        id=909090, full_name="upstream/widget", name="widget",
        html_url="https://github.com/upstream/widget",
        default_branch="main",
    )
    session.add(repo)
    session.flush()
    issue = Issue(
        id=70707, repo_id=repo.id, number=42, title="Fix the foo bug!!!",
        html_url="https://github.com/upstream/widget/issues/42",
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
        accepted_attempt_number=1,
        attempts_made=1,
        summary="bumped the value",
        branch_ref="oss-engine/pilot-deadbeef-issue-42" if pushed else None,
        pushed_at=now if pushed else None,
        fork_url=f"https://github.com/{user.github_login}/widget" if pushed else None,
        pr_url=(
            "https://github.com/upstream/widget/pull/100"
            if pr_opened else None
        ),
        pr_number=100 if pr_opened else None,
        pr_opened_at=now if pr_opened else None,
        transcript_json=transcript_json,
    )
    session.add(pilot)
    if session.query(OAuthToken).filter_by(user_id=user.id).first() is None:
        session.add(OAuthToken(
            user_id=user.id,
            encrypted_access_token=encrypt_token("gho_test_token"),
            scopes=["repo"],
        ))
    session.commit()
    return inv, pilot


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_load_context_happy_path(session, make_logged_in_user):
    user = make_logged_in_user(github_login="dev-login", github_id=100)
    _inv, pilot = _seed_chain(session, user)
    ok, ctx = _load_context(session, pilot.id)
    assert ok is True
    assert ctx["upstream_full_name"] == "upstream/widget"
    # Cross-fork head ref format: <fork_owner>:<branch>
    assert ctx["head_ref"] == "dev-login:oss-engine/pilot-deadbeef-issue-42"
    assert ctx["title"].startswith("[oss-engine]")
    assert "#42" in ctx["title"]
    assert "Closes #42" in ctx["body"]


@pytest.mark.unit
def test_load_context_refuses_non_accepted_pilot(session, make_logged_in_user):
    user = make_logged_in_user()
    _, pilot = _seed_chain(session, user, pilot_status="rejected")
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "accepted" in (pilot.pr_error or "")


@pytest.mark.unit
def test_load_context_refuses_unpushed_pilot(session, make_logged_in_user):
    user = make_logged_in_user()
    _, pilot = _seed_chain(session, user, pushed=False)
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "push" in (pilot.pr_error or "").lower()


@pytest.mark.unit
def test_load_context_refuses_when_pr_already_open(session, make_logged_in_user):
    user = make_logged_in_user()
    _, pilot = _seed_chain(session, user, pr_opened=True)
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "already opened" in (pilot.pr_error or "")


@pytest.mark.unit
def test_load_context_refuses_when_oauth_missing(session, make_logged_in_user):
    user = make_logged_in_user()
    _, pilot = _seed_chain(session, user)
    session.query(OAuthToken).filter_by(user_id=user.id).delete()
    session.commit()
    ok, _ = _load_context(session, pilot.id)
    assert ok is False
    session.refresh(pilot)
    assert "OAuth token" in (pilot.pr_error or "")


# ---------------------------------------------------------------------------
# Title + body builders (pure functions)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_title_includes_issue_number_and_slug():
    title = _build_title(issue_number=42, issue_title="Fix the foo bug!!!")
    assert title.startswith("[oss-engine] Attempted fix for #42:")
    # Special chars stripped.
    assert "!!!" not in title
    assert "Fix the foo bug" in title


@pytest.mark.unit
def test_build_title_truncates_long_titles():
    long = "a" * 200
    title = _build_title(issue_number=1, issue_title=long)
    # Title stays bounded — should be well under 200 chars total.
    assert len(title) < 130


@pytest.mark.unit
def test_build_body_includes_critical_sections(session, make_logged_in_user):
    user = make_logged_in_user(github_login="dev", github_id=1)
    transcript = {
        "success": True,
        "accepted_attempt_number": 1,
        "attempts": [{
            "attempt_number": 1,
            "patch_result": {
                "edits_applied": [
                    {"path": "src/auth.py", "explanation": "fix the bug",
                     "new_file": False},
                    {"path": "tests/new_test.py", "explanation": "add coverage",
                     "new_file": True},
                ],
            },
            "test_result": {
                "classification": "pass",
                "summary": "all good",
            },
        }],
    }
    _inv, pilot = _seed_chain(
        session, user, transcript_json=json.dumps(transcript),
    )
    body = _build_body(
        pilot=pilot,
        upstream_full="upstream/widget",
        issue_number=42,
        issue_title="Fix the foo bug",
        transcript=transcript,
    )
    # AI banner is unmissable.
    assert "🤖" in body
    assert "review carefully" in body.lower()
    # Closes the issue.
    assert "Closes #42" in body
    # Files section enumerates edits with the NEW marker.
    assert "src/auth.py" in body
    assert "tests/new_test.py" in body
    assert "**NEW**" in body
    # Test classification surfaced.
    assert "pass" in body
    # Provenance carries pilot id.
    assert pilot.id in body


@pytest.mark.unit
def test_build_body_surfaces_needs_env_caveat(session, make_logged_in_user):
    """When tests classified as needs_env we add the caveat block."""
    user = make_logged_in_user()
    transcript = {
        "success": True,
        "accepted_attempt_number": 1,
        "attempts": [{
            "attempt_number": 1,
            "patch_result": {"edits_applied": []},
            "test_result": {
                "classification": "needs_env",
                "summary": "deps missing",
            },
        }],
    }
    _inv, pilot = _seed_chain(
        session, user, transcript_json=json.dumps(transcript),
    )
    body = _build_body(
        pilot=pilot,
        upstream_full="upstream/widget",
        issue_number=42,
        issue_title="x",
        transcript=transcript,
    )
    assert "needs_env" in body
    assert "couldn't install" in body or "couldn’t install" in body


@pytest.mark.unit
def test_build_body_robust_to_missing_transcript(session, make_logged_in_user):
    """A None/empty transcript shouldn't crash — partial body is fine."""
    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user)
    body = _build_body(
        pilot=pilot,
        upstream_full="upstream/widget",
        issue_number=42,
        issue_title="x",
        transcript=None,
    )
    # Falls back to "unknown" test classification but still produces a body.
    assert "unknown" in body
    assert "Closes #42" in body
    assert pilot.id in body


# ---------------------------------------------------------------------------
# Top-level open_pilot_pr: short-circuits when pre-flight fails
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_open_pilot_pr_short_circuits_before_calling_github(
    session, make_logged_in_user, engine,
):
    """A pilot that isn't pushed yet should never touch the GitHub API."""
    from sqlalchemy.orm import sessionmaker

    user = make_logged_in_user()
    _inv, pilot = _seed_chain(session, user, pushed=False)
    sm = sessionmaker(engine, expire_on_commit=False)

    mock_gh = MagicMock(name="GitHubClient")
    with patch("app.pilot.pr_opener.GitHubClient", return_value=mock_gh):
        await open_pilot_pr(pilot_id=pilot.id, session_factory=sm)

    mock_gh.create_pull_request.assert_not_called()
    mock_gh.get_repo.assert_not_called()

    with sm() as s2:
        p = s2.get(PilotRun, pilot.id)
        assert p.pr_error is not None
        assert "push" in p.pr_error.lower()
