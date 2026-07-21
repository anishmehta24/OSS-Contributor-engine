"""Issue Analyst: reads issue body + comments, extracts what's actually being asked."""
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.agents.investigator.schemas import IssueRequirements
from app.llm import call_llm

log = structlog.get_logger(__name__)

SYSTEM_PROMPT = """You are reading a GitHub issue and extracting what a developer
who picks up this issue would actually need to know.

Input includes:
- Issue title, body, and labels
- All comments posted on the issue

Return ONE JSON object with these fields:
  "summary":             2-3 sentence restatement of the issue in your own words
  "requirements":        Up to 12 explicit things the implementation must do
  "acceptance_criteria": Up to 8 testable conditions for "done" (often implied)
  "open_questions":      Up to 6 ambiguities the contributor should clarify
  "technical_keywords":  Up to 12 lowercase terms (function names, file paths,
                         framework names) useful for code search

Rules:
- Do NOT invent requirements that aren't in the issue or comments.
- If a section has nothing real to say, return an empty list.
- No markdown fences in the JSON."""


def build_user_message(
    *,
    title: str,
    body: str | None,
    labels: list[str],
    comments: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"TITLE: {title}")
    lines.append(f"LABELS: {', '.join(labels) if labels else '(none)'}")
    lines.append("")
    lines.append("BODY:")
    lines.append((body or "(empty)")[:6000])
    lines.append("")
    lines.append(f"COMMENTS ({len(comments)}):")
    if not comments:
        lines.append("(none)")
    else:
        for c in comments[:15]:
            author = (c.get("user") or {}).get("login", "?")
            content = (c.get("body") or "").strip()[:1500]
            lines.append(f"--- {author} ---")
            lines.append(content)
    return "\n".join(lines)


def run_issue_analyst(
    router,
    *,
    title: str,
    body: str | None,
    labels: list[str],
    comments: list[dict[str, Any]],
    investigation_id: str | None = None,
    session: Session | None = None,
) -> IssueRequirements:
    user_msg = build_user_message(
        title=title, body=body, labels=labels, comments=comments,
    )
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="issue_analyst",
        response_model=IssueRequirements,
        investigation_id=investigation_id,
        session=session,
        # Headroom so Gemini's thinking tokens don't truncate the JSON.
        max_tokens=2500,
    )
    if parsed is None:
        log.warning("issue_analyst_parse_failed", title=title[:80])
        return IssueRequirements(summary=title)
    return parsed
