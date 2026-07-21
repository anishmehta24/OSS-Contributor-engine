"""History Detective: summarizes what's been happening in this repo recently.

We feed it the last N commit messages and ask:
    - What themes are active right now?
    - Any commits the contributor should be aware of?
    - Is the project actively maintained or stagnant?
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.agents.investigator.schemas import HistoricalContext
from app.llm import call_llm
from app.tools.github.models import Commit

log = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are summarizing recent activity in a GitHub repo to help
a contributor understand the context they're walking into.

Input: the last N commit messages (subject lines).

Return ONE JSON object:
  "recent_themes":    Up to 8 short phrases describing what kind of work
                      has been happening (e.g. "perf optimization", "auth refactor",
                      "test coverage push")
  "notable_commits":  Up to 8 commit messages worth flagging (security fixes,
                      breaking changes, refactors of the area the issue touches)
  "summary":          2-3 sentence narrative for the contributor

Rules:
- If commits look stale (e.g. all from > 6 months ago), say so in summary.
- If commits look like routine dependency bumps, say so.
- Do not invent commits."""


def build_user_message(commits: list[Commit], *, area_hint: str | None = None) -> str:
    lines = []
    if area_hint:
        lines.append(f"Issue area hint: {area_hint}")
        lines.append("")
    lines.append(f"Recent commits ({len(commits)}):")
    for c in commits[:50]:
        subject = c.message.split("\n", 1)[0]
        date = c.author_date.date().isoformat() if c.author_date else "?"
        author = c.author_login or "?"
        lines.append(f"  [{date}] {author}: {subject[:140]}")
    return "\n".join(lines)


def run_history_detective(
    router,
    *,
    commits: list[Commit],
    area_hint: str | None = None,
    investigation_id: str | None = None,
    session: Session | None = None,
) -> HistoricalContext:
    if not commits:
        return HistoricalContext(
            summary="No recent commit history available.",
        )

    user_msg = build_user_message(commits, area_hint=area_hint)
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="history_detective",
        response_model=HistoricalContext,
        investigation_id=investigation_id,
        session=session,
        # Headroom so Gemini's thinking tokens don't truncate the JSON.
        max_tokens=2000,
    )
    if parsed is None:
        log.warning("history_detective_parse_failed")
        return HistoricalContext(summary="(LLM parse failed)")
    return parsed
