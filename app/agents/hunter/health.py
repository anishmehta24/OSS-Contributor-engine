"""Pure functions for scoring repo + issue freshness.

We compute these once at hunt time and store on the rows so the Triager
(Batch 6) doesn't have to recompute on every ranking request.

Score range: 0.0 - 1.0 (higher = healthier / fresher).
"""
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta


def repo_health_score(
    *,
    stars: int,
    pushed_at: datetime | None,
    open_issues_count: int = 0,
    forks_count: int = 0,
    archived: bool = False,
    now: datetime | None = None,
) -> float:
    """Combine star popularity + recency + activity into a [0, 1] score.

    Weights (sum to 1.0):
        50% — log-scaled stars (caps the runaway-popularity effect)
        30% — recent commit activity (90-day decay)
        15% — has a healthy backlog of forks (community engagement)
         5% — open issues *aren't* runaway (capped at 500)

    Archived repos get a hard 0.
    """
    if archived:
        return 0.0
    now = _aware(now) if now is not None else datetime.now(UTC)

    # 1) Stars: log10 cap. log10(100k) = 5, so we divide by 5 for [0, 1].
    star_score = min(1.0, math.log10(max(stars, 1)) / 5.0)

    # 2) Recency: 90-day half-life decay.
    if pushed_at is None:
        recency = 0.0
    else:
        days_since = max(0.0, (now - _aware(pushed_at)).total_seconds() / 86400)
        recency = math.exp(-days_since / 90.0)

    # 3) Forks: log-scaled, caps at 1000 forks for max score.
    fork_score = min(1.0, math.log10(max(forks_count, 1)) / 3.0)

    # 4) Issue backlog penalty: many open issues = unresponsive maintainer.
    if open_issues_count <= 50:
        issue_score = 1.0
    elif open_issues_count >= 500:
        issue_score = 0.0
    else:
        issue_score = 1.0 - (open_issues_count - 50) / 450.0

    score = (
        0.50 * star_score
        + 0.30 * recency
        + 0.15 * fork_score
        + 0.05 * issue_score
    )
    return round(min(1.0, max(0.0, score)), 4)


def issue_freshness_score(
    *,
    issue_updated_at: datetime,
    now: datetime | None = None,
) -> float:
    """30-day half-life decay on issue last-update."""
    now = _aware(now) if now is not None else datetime.now(UTC)
    days = max(0.0, (now - _aware(issue_updated_at)).total_seconds() / 86400)
    return round(math.exp(-days / 30.0), 4)


def is_recent_enough(
    *,
    issue_created_at: datetime,
    max_age_days: int = 90,
    now: datetime | None = None,
) -> bool:
    """Hard filter for issues that are too old to bother surfacing."""
    now = _aware(now) if now is not None else datetime.now(UTC)
    return (now - _aware(issue_created_at)) <= timedelta(days=max_age_days)


def _aware(dt: datetime) -> datetime:
    """Make sure we compare apples to apples. Treat naive as UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
