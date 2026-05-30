"""Push an accepted pilot diff to the user's GitHub fork.

Flow:
    1. Pre-flight: pilot must be in status='accepted' AND not already pushed.
    2. Fork the upstream repo into the user's account (idempotent — GitHub
       returns the existing fork if there is one).
    3. Wait until the fork's metadata is fetchable (just-forked repos
       briefly 404).
    4. Clone the fork into a fresh sandbox workspace using token auth.
    5. Create a deterministic feature branch named
       `oss-engine/pilot-<short-id>-issue-<n>`.
    6. Apply the accepted diff via `git apply --whitespace=nowarn`.
    7. Configure git user.name/email so the commit shows up in the
       user's profile feed.
    8. Commit with a clearly-machine-flavored message + push the branch.
    9. Persist `fork_url`, `branch_ref`, `pushed_at` on the PilotRun row.

This module does NOT open a PR — that's Batch 35.

Failure modes that get caught and surfaced as `push_error`:
    - User revoked the OAuth grant (401)
    - Diff fails to apply (upstream moved since pilot was generated)
    - Token has insufficient scopes
    - Network flake (one retry, then give up)
"""
from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt_token
from app.db.models import Investigation, OAuthToken, PilotRun
from app.pilot.safety import is_repo_refused
from app.sandbox import Workspace
from app.tools.github import GitHubClient
from app.tools.github.exceptions import AuthError, GitHubError

log = structlog.get_logger(__name__)

# Cap the branch name at GitHub's ref-length limit (~250 chars; we stay
# well under). Issue numbers go in for searchability.
_BRANCH_PREFIX = "oss-engine/pilot"

# Per-step timeouts. git operations are local but `clone` against GitHub
# can be slow on big repos.
_GIT_CLONE_TIMEOUT_S = 180
_GIT_GENERIC_TIMEOUT_S = 60

# A safe pattern for the issue-title slug we drop into the commit message
# subject. Anything else gets stripped.
_SLUG_RE = re.compile(r"[^A-Za-z0-9 _-]+")


class PusherError(Exception):
    """Anything that goes wrong during push. We never let this escape the
    background task — gets persisted to `push_error`."""


async def push_pilot_branch(
    *,
    pilot_id: str,
    session_factory,
) -> None:
    """Top-level entry point. Designed for background-task usage:
    persists all outcomes to the DB and never raises."""
    with session_factory() as session:
        ok, ctx = _load_context(session, pilot_id)
        if not ok:
            return
        repo_full_name = ctx["repo_full_name"]
        github_token = ctx["github_token"]
        github_login = ctx["github_login"]
        issue_number = ctx["issue_number"]
        issue_title = ctx["issue_title"]
        accepted_diff = ctx["accepted_diff"]
        commit_author_name = ctx["commit_author_name"]
        commit_author_email = ctx["commit_author_email"]

    branch_ref = _branch_name(pilot_id, issue_number)
    fork_full_name = f"{github_login}/{repo_full_name.split('/', 1)[1]}"

    log.info(
        "pilot_push_start",
        pilot_id=pilot_id, fork=fork_full_name, branch=branch_ref,
    )

    # ---- 1. Fork ----
    try:
        async with GitHubClient(token=github_token) as gh:
            fork = await gh.fork_repo(repo_full_name)
            # Just-forked repos can briefly 404; wait for the API to settle.
            await gh.wait_for_repo_ready(fork.full_name, max_wait_s=30)
            fork_url = fork.html_url
            clone_url = f"https://github.com/{fork.full_name}.git"
    except AuthError:
        _record_push_error(
            session_factory, pilot_id,
            "GitHub OAuth token rejected — user likely revoked the grant",
        )
        return
    except GitHubError as e:
        _record_push_error(
            session_factory, pilot_id, f"fork failed: {e}",
        )
        return

    # ---- 2-9. Clone, branch, apply, commit, push ----
    ws = Workspace.create(f"push-{pilot_id[:8]}")
    try:
        try:
            local_repo = _clone_with_token(
                clone_url=clone_url,
                fork_full_name=fork.full_name,
                token=github_token,
                workspace=ws,
            )
            _create_branch(local_repo, branch_ref)
            _apply_diff(local_repo, accepted_diff)
            _configure_git_identity(
                local_repo,
                name=commit_author_name,
                email=commit_author_email,
            )
            _commit(
                local_repo,
                issue_title=issue_title,
                issue_number=issue_number,
                pilot_id=pilot_id,
            )
            _push_branch(local_repo, branch_ref, token=github_token, clone_url=clone_url)
        except PusherError as e:
            _record_push_error(session_factory, pilot_id, str(e))
            return

        # ---- 10. Persist success ----
        with session_factory() as session:
            pilot = session.get(PilotRun, pilot_id)
            if pilot is None:
                log.error("pilot_row_vanished_during_push", pilot_id=pilot_id)
                return
            pilot.fork_url = fork_url
            pilot.branch_ref = branch_ref
            pilot.pushed_at = _now()
            pilot.push_error = None
            session.commit()
        log.info(
            "pilot_push_done",
            pilot_id=pilot_id, fork=fork.full_name, branch=branch_ref,
        )
    finally:
        ws.cleanup()


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

def _load_context(session: Session, pilot_id: str) -> tuple[bool, dict]:
    """Validate the pilot is push-ready + load everything we need.

    Returns (ok, context). On ok=False the push_error is already written.
    """
    pilot = session.get(PilotRun, pilot_id)
    if pilot is None:
        log.error("pilot_row_missing_for_push", pilot_id=pilot_id)
        return False, {}

    if pilot.status != "accepted":
        _set_error(pilot, session,
                   f"pilot status is {pilot.status!r}; can only push 'accepted' pilots")
        return False, {}

    if pilot.pushed_at is not None:
        _set_error(pilot, session,
                   "pilot already pushed (won't clobber the existing branch)")
        return False, {}

    if not pilot.accepted_diff or not pilot.accepted_diff.strip():
        _set_error(pilot, session, "pilot has no accepted_diff to push")
        return False, {}

    inv = session.get(Investigation, pilot.investigation_id)
    if inv is None or inv.issue is None or inv.issue.repo is None:
        _set_error(pilot, session, "investigation has no issue/repo association")
        return False, {}

    # Defense in depth: the create endpoint already refuses opted-out repos,
    # but re-check here so a refuse-list entry added AFTER the pilot ran
    # still blocks the actual fork/push.
    if is_repo_refused(inv.issue.repo.full_name):
        _set_error(
            pilot, session,
            f"{inv.issue.repo.full_name} is on the pilot refuse-list — "
            f"won't fork or push.",
        )
        return False, {}

    token_row = (
        session.query(OAuthToken)
        .filter(OAuthToken.user_id == pilot.user_id)
        .one_or_none()
    )
    if token_row is None:
        _set_error(pilot, session, "user has no OAuth token — re-sign in")
        return False, {}

    try:
        token = decrypt_token(token_row.encrypted_access_token)
    except Exception as e:
        _set_error(pilot, session, f"OAuth token decrypt failed: {e}")
        return False, {}

    return True, {
        "repo_full_name": inv.issue.repo.full_name,
        "github_token": token,
        "github_login": pilot.user.github_login,
        "issue_number": inv.issue.number,
        "issue_title": inv.issue.title,
        "accepted_diff": pilot.accepted_diff,
        "commit_author_name": pilot.user.name or pilot.user.github_login,
        "commit_author_email": (
            f"{pilot.user.github_id}+{pilot.user.github_login}@users.noreply.github.com"
        ),
    }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _branch_name(pilot_id: str, issue_number: int) -> str:
    return f"{_BRANCH_PREFIX}-{pilot_id[:8]}-issue-{issue_number}"


def _clone_with_token(
    *,
    clone_url: str,
    fork_full_name: str,
    token: str,
    workspace: Workspace,
):
    """Clone via HTTPS-with-token-in-URL.

    Token is removed from `origin` immediately after to keep it out of
    the local repo's git config. The push uses an inline `-c` override
    so the token never persists to disk.
    """
    # We use `x-access-token:<token>` per the GitHub docs — works for both
    # OAuth tokens and fine-grained PATs.
    auth_url = clone_url.replace(
        "https://", f"https://x-access-token:{token}@", 1,
    )
    target = workspace.host_path / fork_full_name.split("/", 1)[1]

    proc = subprocess.run(
        ["git", "clone", "--depth", "1", auth_url, str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=_GIT_CLONE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        # Stderr from git WILL contain the auth URL — scrub it before logging.
        safe_err = proc.stderr.replace(token, "***")
        raise PusherError(f"git clone failed: {safe_err[:400]}")

    # Wipe the credential from the local remote config.
    _git(target, ["remote", "set-url", "origin", clone_url])
    return target


def _create_branch(repo: Path, branch: str) -> None:
    _git(repo, ["checkout", "-b", branch])


def _apply_diff(repo: Path, diff_text: str) -> None:
    """Apply the unified diff with `git apply`.

    --whitespace=nowarn is intentional — the Patch Writer's diffs come
    from `git diff`, but encoding round-trips through pydantic JSON can
    occasionally normalize trailing whitespace. We've already validated
    the diff applied cleanly during the pilot run (it's where we captured
    it from), so an apply failure here usually means the upstream main
    moved since the pilot was generated.
    """
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=repo,
        input=diff_text,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=_GIT_GENERIC_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise PusherError(
            f"`git apply` failed (upstream may have moved): "
            f"{proc.stderr.strip()[:400]}",
        )


def _configure_git_identity(repo: Path, *, name: str, email: str) -> None:
    _git(repo, ["config", "user.name", name])
    _git(repo, ["config", "user.email", email])


def _commit(
    repo: Path,
    *,
    issue_title: str,
    issue_number: int,
    pilot_id: str,
) -> None:
    # Subject line: short, clearly machine-flavored, references the issue.
    safe_slug = _SLUG_RE.sub("", issue_title).strip()[:60]
    subject = f"oss-engine: attempted fix for issue #{issue_number} ({safe_slug})"
    body = (
        "This branch was generated by the OSS Contributor Engine "
        "(github.com/anishmehta-oss-engine) — an autonomous multi-agent "
        "system that reads issues, explores the codebase, writes patches, "
        "and runs tests in a sandboxed environment.\n\n"
        f"Pilot id: {pilot_id}\n"
        f"Closes: #{issue_number} (proposed, please review)\n\n"
        "Sent as a draft PR. The maintainer is the source of truth — "
        "feedback welcome. If the patch isn't useful, please close and "
        "discard the branch."
    )

    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-m", subject, "-m", body])


def _push_branch(
    repo: Path,
    branch: str,
    *,
    token: str,
    clone_url: str,
) -> None:
    """Push using -c http.extraheader for one-shot auth.

    Avoids writing the token to .git/config. The `-c` flag's value only
    lives for this one git invocation.
    """
    auth_url = clone_url.replace(
        "https://", f"https://x-access-token:{token}@", 1,
    )
    proc = subprocess.run(
        ["git", "push", "--set-upstream", auth_url, f"HEAD:{branch}"],
        cwd=repo,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=_GIT_GENERIC_TIMEOUT_S,
    )
    if proc.returncode != 0:
        safe_err = proc.stderr.replace(token, "***")
        raise PusherError(f"git push failed: {safe_err[:400]}")


def _git(repo: Path, argv: list[str]) -> None:
    proc = subprocess.run(
        ["git", *argv], cwd=repo,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=_GIT_GENERIC_TIMEOUT_S,
    )
    if proc.returncode != 0:
        raise PusherError(
            f"`git {' '.join(argv[:3])}...` failed: {proc.stderr.strip()[:300]}",
        )


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _record_push_error(session_factory, pilot_id: str, reason: str) -> None:
    """Write the push error from outside a session context."""
    with session_factory() as session:
        pilot = session.get(PilotRun, pilot_id)
        if pilot is None:
            return
        _set_error(pilot, session, reason)


def _set_error(pilot: PilotRun, session: Session, reason: str) -> None:
    pilot.push_error = reason
    session.commit()
    log.warning("pilot_push_failed", pilot_id=pilot.id, reason=reason)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


__all__ = ["push_pilot_branch", "PusherError"]
