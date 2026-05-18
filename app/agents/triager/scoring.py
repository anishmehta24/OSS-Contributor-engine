"""Pure scoring functions for the Triager.

We split scoring out of the orchestration so it's deterministic, easy to
test, and explainable (each component is logged).

All inputs are normalized to [0, 1] before weighting. sqlite-vec returns
cosine *distance* in [0, 2]; we convert it to similarity via 1 - d/2.
"""
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

DifficultyPref = Literal["any", "easy", "medium", "hard"]


def distance_to_similarity(distance: float) -> float:
    """Convert sqlite-vec cosine distance to similarity in [0, 1].

    sqlite-vec returns distance in [0, 2] (0 = identical, 2 = opposite).
    Clamp defensively.
    """
    sim = 1.0 - (distance / 2.0)
    return max(0.0, min(1.0, sim))


def freshness_score(updated_at: datetime, *, now: datetime | None = None) -> float:
    """30-day half-life exponential decay."""
    now = now or datetime.now(UTC)
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    days = max(0.0, (now - updated_at).total_seconds() / 86400)
    return round(math.exp(-days / 30.0), 4)


def impact_score(stars: int) -> float:
    """log10-scaled stars, capped at 100k = 1.0."""
    return round(min(1.0, math.log10(max(stars, 1)) / 5.0), 4)


def difficulty_match_score(
    issue_difficulty: str | None,
    preference: DifficultyPref,
) -> float:
    """How well the issue's difficulty matches the user's preference."""
    if preference == "any" or issue_difficulty is None:
        return 0.7  # neutral score when ambiguous
    if issue_difficulty == preference:
        return 1.0
    # Adjacent difficulties get half credit; opposite gets a quarter
    ladder = {"easy": 0, "medium": 1, "hard": 2}
    if issue_difficulty not in ladder or preference not in ladder:
        return 0.5
    diff = abs(ladder[issue_difficulty] - ladder[preference])
    return {1: 0.5, 2: 0.25}.get(diff, 0.0)


def combine(
    *,
    skill: float,
    repo_health: float,
    freshness: float,
    difficulty: float,
    impact: float,
    weights,
) -> float:
    """Apply weights and clamp to [0, 1]."""
    w = weights.normalized()
    score = (
        w.skill_match * skill
        + w.repo_health * repo_health
        + w.freshness * freshness
        + w.difficulty_match * difficulty
        + w.impact * impact
    )
    return round(min(1.0, max(0.0, score)), 4)
