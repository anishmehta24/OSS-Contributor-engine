"""LLM-based difficulty estimator for issues.

We try a fast label-based heuristic first; only fall back to the LLM when
labels are ambiguous. This keeps cost down (most "good first issue" labeled
items are obvious).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents.hunter.schemas import Difficulty
from app.llm import call_llm


class DifficultyOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    difficulty: Difficulty = Field(description="One of 'easy', 'medium', 'hard'")
    reason: str = Field(default="", max_length=200)


EASY_LABEL_HINTS = {"good first issue", "beginner", "first-timers-only", "easy", "starter"}
HARD_LABEL_HINTS = {"hard", "expert", "complex", "architecture", "epic", "refactor"}


SYSTEM_PROMPT = """You triage GitHub issues by implementation difficulty.

Given an issue's title, body, and labels, return ONE JSON object:
  {"difficulty": "easy" | "medium" | "hard", "reason": "<one short phrase>"}

Guidance:
- "easy"   — small isolated change, clear scope, no architecture decisions.
            Typo, docs, single-function bug, adding a test.
- "medium" — touches multiple files or requires understanding context,
            but the requirements are clear.
- "hard"   — architecture changes, performance work, requires designing
            an API, or the scope is ambiguous.

Be conservative: when uncertain, prefer "medium". No markdown fences."""


def heuristic_difficulty(labels: list[str]) -> Difficulty | None:
    """Fast path: label-based. Returns None when labels are ambiguous."""
    lowered = {label.lower() for label in labels}
    if lowered & EASY_LABEL_HINTS:
        return "easy"
    if lowered & HARD_LABEL_HINTS:
        return "hard"
    return None


def estimate_difficulty(
    router,
    *,
    title: str,
    body: str | None,
    labels: list[str],
    session: Session | None = None,
) -> Difficulty:
    """Hybrid: label heuristic first, LLM fallback for ambiguous cases."""
    heur = heuristic_difficulty(labels)
    if heur is not None:
        return heur

    user_msg = (
        f"Title: {title}\n"
        f"Labels: {', '.join(labels) if labels else '(none)'}\n"
        f"Body:\n{(body or '(empty)')[:2000]}"
    )
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="difficulty_estimator",
        response_model=DifficultyOutput,
        session=session,
        max_tokens=120,
    )
    if parsed is None:
        return "medium"  # safe fallback when LLM fails to produce valid JSON
    return parsed.difficulty
