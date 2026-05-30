"""Open a draft PR on the upstream repo from a pushed pilot branch.

Runs after Batch 34's pusher has populated `PilotRun.branch_ref` and
`pushed_at`. The PR is ALWAYS opened as a draft — the v3 design treats
maintainer review as non-negotiable.

Flow:
    1. Pre-flight: pilot must be 'accepted', already pushed, and not
       already have a PR open.
    2. Read the upstream repo's default branch to use as the PR base.
    3. Build a clearly-AI-labeled PR title + markdown body from the
       PilotRun transcript.
    4. POST /repos/{upstream}/pulls with draft=True.
    5. Persist pr_url, pr_number, pr_opened_at on the PilotRun row.

Like the pusher, this module never raises — failures are persisted to
`pr_error` so the UI / next iteration can surface them.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.auth.crypto import decrypt_token
from app.db.models import Investigation, OAuthToken, PilotRun
from app.tools.github import GitHubClient
from app.tools.github.exceptions import AuthError, GitHubError

log = structlog.get_logger(__name__)

# Truncate the slug used inside the PR title so it stays scannable.
_TITLE_SLUG_MAX = 70
# Anything that isn't safe filename / shell char gets stripped from the slug.
_SLUG_RE = re.compile(r"[^A-Za-z0-9 _-]+")
# Body excerpt cap — long transcripts make the PR description scroll forever.
_MAX_BODY_BYTES = 12_000


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class PROpenerError(Exception):
    """Anything that breaks the open-PR flow."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def open_pilot_pr(
    *,
    pilot_id: str,
    session_factory,
) -> None:
    """Open a draft PR for `pilot_id`. Background-task safe — never raises."""
    with session_factory() as session:
        ok, ctx = _load_context(session, pilot_id)
        if not ok:
            return
        upstream_full_name = ctx["upstream_full_name"]
        github_token = ctx["github_token"]
        head_ref = ctx["head_ref"]
        title = ctx["title"]
        body = ctx["body"]

    log.info(
        "pilot_pr_open_start",
        pilot_id=pilot_id, upstream=upstream_full_name, head=head_ref,
    )

    try:
        async with GitHubClient(token=github_token) as gh:
            # Discover the upstream default branch — don't hardcode 'main'.
            upstream = await gh.get_repo(upstream_full_name)
            base_branch = upstream.default_branch or "main"

            pr = await gh.create_pull_request(
                upstream_full_name,
                title=title,
                body=body,
                head=head_ref,
                base=base_branch,
                draft=True,
            )
    except AuthError:
        _record_error(
            session_factory, pilot_id,
            "GitHub OAuth token rejected — user likely revoked the grant",
        )
        return
    except GitHubError as e:
        # Common case: GitHub returns 422 when a PR already exists for this
        # head -> base pair. Surface that explicitly so the user can find
        # and reopen it manually.
        msg = str(e).lower()
        if "already exists" in msg or "no commits between" in msg:
            _record_error(
                session_factory, pilot_id,
                f"GitHub refused PR creation: {e}",
            )
            return
        _record_error(
            session_factory, pilot_id,
            f"create_pull_request failed: {e}",
        )
        return

    # ---- Persist ----
    with session_factory() as session:
        pilot = session.get(PilotRun, pilot_id)
        if pilot is None:
            log.error("pilot_row_vanished_during_pr", pilot_id=pilot_id)
            return
        pilot.pr_url = pr.html_url
        pilot.pr_number = pr.number
        pilot.pr_opened_at = _now()
        pilot.pr_error = None
        session.commit()

    log.info(
        "pilot_pr_open_done",
        pilot_id=pilot_id, pr_url=pr.html_url, pr_number=pr.number,
    )


# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

def _load_context(session: Session, pilot_id: str) -> tuple[bool, dict]:
    """Validate the pilot is PR-ready + assemble title + body + head ref.

    On failure writes `pr_error` and returns (False, {}).
    """
    pilot = session.get(PilotRun, pilot_id)
    if pilot is None:
        log.error("pilot_row_missing_for_pr", pilot_id=pilot_id)
        return False, {}

    if pilot.status != "accepted":
        _set_error(pilot, session,
                   f"pilot status is {pilot.status!r}; can only open PRs for 'accepted' pilots")
        return False, {}

    if not pilot.branch_ref or pilot.pushed_at is None:
        _set_error(pilot, session,
                   "pilot hasn't been pushed yet — push first, then open the PR")
        return False, {}

    if pilot.pr_url:
        _set_error(pilot, session,
                   f"PR already opened at {pilot.pr_url} (#{pilot.pr_number}); won't reopen")
        return False, {}

    inv = session.get(Investigation, pilot.investigation_id)
    if inv is None or inv.issue is None or inv.issue.repo is None:
        _set_error(pilot, session, "investigation has no issue/repo association")
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

    upstream_full = inv.issue.repo.full_name
    # Cross-fork PRs: head must be `<fork_owner>:<branch>`.
    head_ref = f"{pilot.user.github_login}:{pilot.branch_ref}"

    transcript = _decode_transcript(pilot.transcript_json)
    title = _build_title(
        issue_number=inv.issue.number,
        issue_title=inv.issue.title,
    )
    body = _build_body(
        pilot=pilot,
        upstream_full=upstream_full,
        issue_number=inv.issue.number,
        issue_title=inv.issue.title,
        transcript=transcript,
    )

    return True, {
        "upstream_full_name": upstream_full,
        "github_token": token,
        "head_ref": head_ref,
        "title": title,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Title + body builders
# ---------------------------------------------------------------------------

def _build_title(*, issue_number: int, issue_title: str) -> str:
    """Build a PR title that's clearly machine-flavored and references the
    issue, so a maintainer skimming notifications knows what they're
    looking at."""
    slug = _SLUG_RE.sub("", issue_title).strip()
    if len(slug) > _TITLE_SLUG_MAX:
        slug = slug[: _TITLE_SLUG_MAX - 1].rstrip() + "…"
    return f"[oss-engine] Attempted fix for #{issue_number}: {slug}"


def _build_body(
    *,
    pilot: PilotRun,
    upstream_full: str,
    issue_number: int,
    issue_title: str,
    transcript: dict[str, Any] | None,
) -> str:
    """Render the PR body markdown. Defensive against missing transcript
    fields — partial info is better than nothing."""
    accepted_attempt = _accepted_attempt(transcript, pilot.accepted_attempt_number)
    test_classification = _safe_get(
        accepted_attempt, "test_result", "classification",
    ) or "unknown"
    test_summary = _safe_get(accepted_attempt, "test_result", "summary") or ""
    edits = _safe_get(accepted_attempt, "patch_result", "edits_applied") or []

    lines: list[str] = []

    # ---- AI-generated banner (unmissable) ----
    lines.append(
        "> 🤖 **Generated by the [OSS Contributor Engine]"
        "(https://github.com/anishmehta-oss-engine)**"
        " — an autonomous multi-agent system that reads issues,"
        " explores the codebase, writes patches, and runs tests in a"
        " sandboxed environment. **Please review carefully before merging.**",
    )
    lines.append("")
    lines.append(f"Closes #{issue_number}")
    lines.append("")

    # ---- Summary ----
    lines.append("## What this attempts to fix")
    lines.append("")
    lines.append(
        pilot.summary
        or f"Attempted fix for issue **{issue_title}** in `{upstream_full}`.",
    )
    lines.append("")

    # ---- Files changed ----
    if edits:
        lines.append("## Files changed")
        lines.append("")
        for e in edits:
            path = (e or {}).get("path", "?")
            is_new = (e or {}).get("new_file") is True
            why = ((e or {}).get("explanation") or "").strip()
            kind = "**NEW** " if is_new else ""
            line = f"- {kind}`{path}`"
            if why:
                line += f" — {why}"
            lines.append(line)
        lines.append("")

    # ---- Test result ----
    lines.append("## Sandbox test results")
    lines.append("")
    icon = {"pass": "✅", "needs_env": "⚠️", "fail": "❌", "error": "❌"}.get(
        test_classification, "•",
    )
    lines.append(f"- {icon} **{test_classification}** — {test_summary or '(no detail)'}")
    if test_classification == "needs_env":
        lines.append(
            "  - *The sandbox couldn't install this project's runtime deps,"
            " so pytest couldn't collect. The patch passed syntax checks"
            " but hasn't been exercised against the real test suite — please"
            " run the suite locally before merging.*",
        )
    lines.append("")

    # ---- Provenance ----
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Attempts: {pilot.attempts_made}")
    if pilot.accepted_attempt_number is not None:
        lines.append(f"- Accepted on attempt: {pilot.accepted_attempt_number}")
    lines.append(f"- Pilot id: `{pilot.id}`")
    lines.append("")

    # ---- Review guidance ----
    lines.append("## How to review")
    lines.append("")
    lines.append(
        "This is a **draft** PR. If the approach looks right but the diff"
        " isn't quite there, feel free to push commits to this branch. If"
        " it isn't useful, please close — no hard feelings. Feedback on"
        " the agent's reasoning helps improve future attempts.",
    )

    body = "\n".join(lines)
    if len(body.encode("utf-8")) > _MAX_BODY_BYTES:
        body = body.encode("utf-8")[: _MAX_BODY_BYTES - 64].decode(
            "utf-8", errors="ignore",
        ) + "\n\n*(PR body truncated for length)*"
    return body


def _accepted_attempt(
    transcript: dict[str, Any] | None,
    accepted_n: int | None,
) -> dict | None:
    """Pick the accepted Attempt out of a stored ReviewerResult."""
    if not transcript or accepted_n is None:
        return None
    for a in transcript.get("attempts") or []:
        if (a or {}).get("attempt_number") == accepted_n:
            return a
    return None


def _safe_get(d: dict | None, *keys: str) -> Any:
    """Dict-walk that returns None for any missing/None key."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _decode_transcript(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# DB writers
# ---------------------------------------------------------------------------

def _record_error(session_factory, pilot_id: str, reason: str) -> None:
    with session_factory() as session:
        pilot = session.get(PilotRun, pilot_id)
        if pilot is None:
            return
        _set_error(pilot, session, reason)


def _set_error(pilot: PilotRun, session: Session, reason: str) -> None:
    pilot.pr_error = reason
    session.commit()
    log.warning("pilot_pr_open_failed", pilot_id=pilot.id, reason=reason)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


__all__ = ["open_pilot_pr", "PROpenerError"]
