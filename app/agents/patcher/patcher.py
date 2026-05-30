"""Patch Writer — given an issue + Code Explorer candidates, produces edits.

Flow:
  1. Read the full content of every candidate file (truncate huge ones).
  2. Build a structured prompt: issue + per-file blocks.
  3. Call the LLM with response_model=PatchAttempt.
  4. Validate + apply the proposed edits via the applier.
  5. Capture the resulting unified diff via `git diff`.
  6. Wrap everything in a PatchResult — both on success and failure.

This batch does NOT validate that the patched code is correct (syntax,
tests, etc.) — that's the Test Runner (Batch 31) + Reviewer (Batch 32).
"""
from __future__ import annotations

from pathlib import Path

import structlog
from sqlalchemy.orm import Session

from app.agents.explorer.schemas import FileCandidate
from app.agents.patcher.applier import apply_edits, capture_diff
from app.agents.patcher.exceptions import EditApplyError, NoEditsError
from app.agents.patcher.schemas import (
    AppliedEdit,
    CodeEdit,
    PatchAttempt,
    PatchResult,
    PriorAttempt,
)
from app.llm import ProvidersExhaustedError, call_llm

log = structlog.get_logger(__name__)

# Hard cap on file content shipped to the LLM. Most issues need <2k lines
# of context; runaway files (auto-generated SQL fixtures, vendored CSS)
# would otherwise blow the context window.
_MAX_FILE_CHARS = 12_000
_MAX_FILE_LINES = 400

# Global cap on TOTAL candidate-file content across the whole prompt. The
# per-file cap alone let 3 large files balloon the request to ~8.8k tokens,
# which Groq's free tier rejects when Gemini is down (8b caps at 6k TPM,
# 70b at 12k). This shared budget is consumed highest-confidence-file-first
# (candidates arrive sorted desc), so the most relevant code keeps its
# context and the tail gets trimmed or omitted. ~16k chars ≈ 4k tokens,
# which — with the issue body + system prompt + output reservation below —
# keeps the whole request comfortably under the 70b cap and often the 8b's.
_MAX_TOTAL_FILE_CHARS = 16_000

# Output token budget. Aider-style search/replace patches average ~500
# tokens for small fixes. 1536 leaves headroom for multi-edit fixes while
# freeing ~1.5k tokens of the provider's per-minute budget vs the old 3000
# — output tokens count against Groq's TPM cap just like input.
_MAX_OUTPUT_TOKENS = 1536

# Anything beyond this many edits in a single attempt smells like the LLM
# trying to refactor instead of fix. We surface (don't reject) for now.
_SOFT_EDIT_CAP = 8


SYSTEM_PROMPT = """You are fixing a GitHub issue by editing source files.

You'll receive:
- An issue (title + body + labels)
- A short list of candidate source files (with full content)

Return JSON matching this shape:
{
  "summary":    "1-2 sentences describing the overall fix",
  "confidence": 0.0-1.0,
  "edits": [
    {
      "path":        "<exact path from the candidate list>",
      "search":      "<EXACT text to find — whitespace-sensitive>",
      "replace":     "<text to substitute in>",
      "explanation": "<≤25 words>"
    }
  ]
}

Search-and-replace rules — these matter:
- `search` must appear EXACTLY ONCE in the file. Include enough surrounding
  context to make the match unambiguous (3-5 lines around the change is
  usually enough).
- Whitespace, indentation, and blank lines in `search` must match the file
  byte-for-byte. Do NOT collapse, normalize, or reformat.
- To create a NEW file: leave `search` empty and put the full file content
  in `replace`. The `path` must be a path that doesn't yet exist.
- Don't reformat code that isn't part of your fix. Don't reorder imports.
  Don't change unrelated lines.

If you can't confidently fix this from the candidates given:
- Return `"confidence": 0.0-0.3`
- Return `"edits": []`
- Use `summary` to explain what you'd need (more files, different context).

Don't include markdown fences. JSON only."""


async def write_patch(
    *,
    repo: str,
    repo_path: Path,
    issue_title: str,
    issue_body: str | None,
    issue_labels: list[str] | None,
    candidates: list[FileCandidate],
    router,
    prior_attempts: list[PriorAttempt] | None = None,
    investigation_id: str | None = None,
    user_id: int | None = None,
    session: Session | None = None,
) -> PatchResult:
    """Top-level entry point.

    Returns a `PatchResult` whether or not anything actually got patched —
    on failure, `success=False` and `error` is set. Never raises for
    LLM-side problems; only raises if the workspace is bogus (not a dir,
    not a git repo).

    `prior_attempts` is passed by the Reviewer during retries so the LLM
    can see what didn't work last time.
    """
    if not candidates:
        return PatchResult(
            success=False,
            error="no candidate files supplied — run the Code Explorer first",
        )
    if router is None:
        return PatchResult(
            success=False,
            error="patch generation requires an LLM router",
        )

    user_msg = _build_user_message(
        repo=repo,
        repo_path=repo_path,
        issue_title=issue_title,
        issue_body=issue_body,
        issue_labels=issue_labels or [],
        candidates=candidates,
        prior_attempts=prior_attempts or [],
    )

    log.info(
        "patcher_llm_call_start",
        repo=repo,
        candidate_count=len(candidates),
        prior_attempt_count=len(prior_attempts or []),
    )
    try:
        _result, parsed = call_llm(
            router,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            agent_name="patch_writer",
            response_model=PatchAttempt,
            investigation_id=investigation_id,
            user_id=user_id,
            session=session,
            max_tokens=_MAX_OUTPUT_TOKENS,
        )
    except ProvidersExhaustedError as e:
        # Every provider was rate-limited / unavailable — a transient capacity
        # wall, not a real failure. Flag it so the Reviewer/Pilot surface
        # "retry shortly" instead of implying the agent couldn't fix the issue.
        log.warning("patcher_providers_exhausted", repo=repo, error=str(e))
        return PatchResult(
            success=False,
            rate_limited=True,
            error=f"all LLM providers were rate-limited or unavailable: {e}",
        )

    if parsed is None:
        # A strict json_object request that fails to validate is virtually
        # always a degraded / throttled / truncated response — a healthy
        # provider returns parseable JSON, and a genuine "can't fix" comes
        # back as VALID JSON with edits=[] (handled in _materialize, not
        # here). So we treat ANY parse failure as a transient capacity issue
        # and tell the user to retry, rather than implying the agent
        # considered the problem and couldn't solve it.
        empty = not _result.text.strip()
        log.warning("patcher_parse_failed", repo=repo, empty_response=empty)
        return PatchResult(
            success=False,
            rate_limited=True,
            error=(
                "LLM returned an empty response — provider likely throttled; "
                "retry shortly"
                if empty
                else "LLM returned an unparseable response (provider likely "
                "throttled or truncated the output) — retry shortly"
            ),
        )

    return await _materialize(
        repo=repo,
        repo_path=repo_path,
        attempt=parsed,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

async def _materialize(
    *,
    repo: str,
    repo_path: Path,
    attempt: PatchAttempt,
) -> PatchResult:
    """Take a validated PatchAttempt and try to apply it."""
    if not attempt.edits:
        log.info(
            "patcher_no_edits_returned",
            repo=repo,
            confidence=attempt.confidence,
        )
        return PatchResult(
            success=False,
            summary=attempt.summary,
            confidence=attempt.confidence,
            edits_attempted=0,
            error="LLM returned zero edits — issue may need more context or human review",
        )

    if len(attempt.edits) > _SOFT_EDIT_CAP:
        log.warning(
            "patcher_many_edits",
            repo=repo,
            count=len(attempt.edits),
            cap=_SOFT_EDIT_CAP,
        )

    applied: list[AppliedEdit]
    try:
        applied = apply_edits(repo_path, attempt.edits)
    except EditApplyError as e:
        log.warning(
            "patcher_apply_failed",
            repo=repo,
            path=e.path,
            error=str(e),
        )
        return PatchResult(
            success=False,
            summary=attempt.summary,
            confidence=attempt.confidence,
            edits_attempted=len(attempt.edits),
            edits_applied=[],
            error=f"edit failed on {e.path}: {e}" if e.path else str(e),
        )

    try:
        diff = capture_diff(repo_path)
    except EditApplyError as e:
        log.warning("patcher_diff_capture_failed", repo=repo, error=str(e))
        # Edits did apply — just couldn't get the diff. Still a partial success
        # from the agent's perspective; the workspace is patched.
        return PatchResult(
            success=False,
            summary=attempt.summary,
            confidence=attempt.confidence,
            edits_attempted=len(attempt.edits),
            edits_applied=applied,
            error=f"edits applied but couldn't capture diff: {e}",
        )

    if not diff.strip():
        # All edits "applied" but produced no actual change (search==replace).
        return PatchResult(
            success=False,
            summary=attempt.summary,
            confidence=attempt.confidence,
            edits_attempted=len(attempt.edits),
            edits_applied=applied,
            error="patch produced no visible change — search and replace text were identical",
        )

    log.info(
        "patcher_success",
        repo=repo,
        edits_applied=len(applied),
        diff_bytes=len(diff),
        confidence=attempt.confidence,
    )
    return PatchResult(
        success=True,
        summary=attempt.summary,
        confidence=attempt.confidence,
        edits_attempted=len(attempt.edits),
        edits_applied=applied,
        unified_diff=diff,
        error=None,
    )


# Used by `__main__` to surface "no edits" the same way the result API does.
# Re-exported for convenience.
__all__ = ["write_patch", "NoEditsError"]


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

_MAX_BODY_CHARS = 4_000


_MAX_PRIOR_EXCERPT_CHARS = 1_500


def _build_user_message(
    *,
    repo: str,
    repo_path: Path,
    issue_title: str,
    issue_body: str | None,
    issue_labels: list[str],
    candidates: list[FileCandidate],
    prior_attempts: list[PriorAttempt],
) -> str:
    body = (issue_body or "").strip()
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS] + "\n…(body truncated)"

    labels_line = ", ".join(issue_labels) if issue_labels else "(none)"

    file_blocks: list[str] = []
    remaining = _MAX_TOTAL_FILE_CHARS
    for c in candidates:
        if remaining <= 0:
            # Global budget spent — name the file so the LLM knows it exists
            # but don't ship its body (keeps us under free-tier TPM caps).
            file_blocks.append(
                f"--- {c.path}"
                f"  (confidence={c.confidence:.2f}, {c.size_bytes}B)"
                f"  (omitted — prompt size budget reached)\n",
            )
            continue
        budget = min(_MAX_FILE_CHARS, remaining)
        content, truncated = _read_file_for_prompt(
            repo_path, c.path, max_chars=budget,
        )
        remaining -= len(content)
        marker = "  (file truncated — only first portion shown)" if truncated else ""
        file_blocks.append(
            f"--- {c.path}"
            f"  (confidence={c.confidence:.2f}, {c.size_bytes}B){marker}\n"
            f"{content}\n",
        )

    prior_block = _format_prior_attempts(prior_attempts) if prior_attempts else ""

    return (
        f"REPO: {repo}\n"
        f"ISSUE TITLE: {issue_title}\n"
        f"LABELS: {labels_line}\n"
        f"ISSUE BODY:\n{body}\n\n"
        f"{prior_block}"
        f"CANDIDATE FILES ({len(candidates)}):\n\n"
        + "\n".join(file_blocks)
    )


def _format_prior_attempts(prior: list[PriorAttempt]) -> str:
    """Render the retry context. The Reviewer feeds us prior failures so
    the model can avoid repeating the same dead-end pattern."""
    parts = [
        f"PREVIOUS ATTEMPTS ({len(prior)} failed) — DO NOT REPEAT:\n",
    ]
    for a in prior:
        excerpt = a.failure_excerpt or "(no failure output captured)"
        if len(excerpt) > _MAX_PRIOR_EXCERPT_CHARS:
            excerpt = (
                "...(truncated front)...\n"
                + excerpt[-_MAX_PRIOR_EXCERPT_CHARS:]
            )
        files = ", ".join(a.edits_applied_paths) or "(no files)"
        parts.append(
            f"--- Attempt {a.attempt_number} ---\n"
            f"What was tried: {a.summary or '(no summary)'}\n"
            f"Files touched: {files}\n"
            f"Why it failed:\n{excerpt}\n",
        )
    parts.append(
        "Plan a DIFFERENT fix this time — same approach will fail the "
        "same way.\n\n",
    )
    return "\n".join(parts)


def _read_file_for_prompt(
    repo_path: Path, rel_path: str, *, max_chars: int = _MAX_FILE_CHARS,
) -> tuple[str, bool]:
    """Return (text, truncated_flag). Truncated at line OR char limit.

    `max_chars` lets the caller shrink a single file's slice to fit the
    global per-prompt budget (see `_MAX_TOTAL_FILE_CHARS`)."""
    full = repo_path / rel_path
    try:
        with full.open("r", encoding="utf-8", errors="replace") as f:
            lines: list[str] = []
            total_chars = 0
            truncated = False
            for i, line in enumerate(f):
                if i >= _MAX_FILE_LINES or total_chars >= max_chars:
                    truncated = True
                    break
                lines.append(line.rstrip("\n"))
                total_chars += len(line)
        return "\n".join(lines), truncated
    except OSError as e:
        return f"(could not read file: {e})", False


# Imported but only re-exported for the CLI module — keep this stub for the
# benefit of explicit type-import sites without making CodeEdit a public name
# in `app.agents.patcher`.
_ = CodeEdit
