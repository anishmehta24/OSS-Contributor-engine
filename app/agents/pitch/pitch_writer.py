"""Pitch Writer: turns an investigation report into a comment a developer
would actually feel comfortable posting on a GitHub issue.

The hard part is tone, not content — most LLM-generated PR comments come
across either sycophantic ("Hello maintainers! Hope you're having a great
day!") or overconfident ("I'll knock this out in an hour"). The system
prompt below explicitly trains against both failure modes.
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.agents.pitch.schemas import PitchDraft
from app.llm import call_llm

log = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are drafting a comment a developer will post on a GitHub
issue to claim it. You write FOR the developer, IN their voice — never reveal
this comment was AI-assisted.

You will receive:
- The repo and issue (for context)
- An investigation report describing the issue, candidate files, suggested
  approach, open questions, and estimated effort

Return ONE JSON object:
  "comment_md":         The drafted comment, 80-300 words, in GitHub markdown.
                        Plain prose preferred; bullets only if listing
                        questions or trade-offs.
  "asks_questions":     true if comment includes a clarifying question,
                        false otherwise.
  "estimated_timeline": A short phrase like "this weekend" or "over the next
                        couple of days". null if you can't say.
  "tone":               "respectful" or "casual" — match the project's vibe
                        if you can infer it; "respectful" is the safe default.

Rules for the comment:
- Open by claiming the issue plainly: "I'd like to take this on" or similar.
  No greeting, no flattery, no "Hope you're having a great day".
- Mention 1-2 SPECIFIC observations from the investigation that show you
  actually read the issue + code (file paths, approach, etc.).
- If there are open_questions, pick the 1-2 most important and ask them
  inline. Don't ask more than 2 — looks like you haven't done your homework.
- Be honest about uncertainty. "I think X but want to confirm Y" beats
  "I will do X".
- Mention a rough timeline based on the effort estimate. Don't promise
  faster than the report suggests.
- Close with a single sentence offering to start once the maintainer confirms.
- No emojis. No "thanks in advance!". No "let me know if you have any
  questions, I'm happy to discuss" filler.
- No code blocks in the comment (you don't have to design the solution
  inline — the comment is for getting buy-in, not shipping the patch).

If the investigation report seems thin or incomplete, write a shorter,
more cautious comment — don't pad with vagueness."""


def build_user_message(
    *,
    repo_full_name: str,
    issue_number: int,
    issue_url: str,
    markdown_report: str,
) -> str:
    return (
        f"REPO: {repo_full_name}\n"
        f"ISSUE: #{issue_number}\n"
        f"URL: {issue_url}\n\n"
        f"=== Investigation report ===\n"
        f"{markdown_report[:6000]}"
    )


def run_pitch_writer(
    router,
    *,
    repo_full_name: str,
    issue_number: int,
    issue_url: str,
    markdown_report: str,
    investigation_id: str | None = None,
    user_id: int | None = None,
    session: Session | None = None,
) -> PitchDraft:
    user_msg = build_user_message(
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        issue_url=issue_url,
        markdown_report=markdown_report,
    )
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="pitch_writer",
        response_model=PitchDraft,
        investigation_id=investigation_id,
        user_id=user_id,
        session=session,
        # Headroom so Gemini's thinking tokens don't truncate the JSON.
        max_tokens=1800,
    )
    if parsed is None:
        log.warning(
            "pitch_writer_parse_failed",
            repo=repo_full_name, issue=issue_number,
        )
        return PitchDraft(
            comment_md=(
                "I'd like to take a look at this issue. "
                "(Auto-drafted pitch failed to render — please review the "
                "investigation report and edit before posting.)"
            ),
            asks_questions=False,
            estimated_timeline=None,
            tone="respectful",
        )
    return parsed
