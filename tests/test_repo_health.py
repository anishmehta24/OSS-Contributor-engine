"""Tests for repo_health_score and freshness helpers."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.hunter.health import (
    is_recent_enough,
    issue_freshness_score,
    repo_health_score,
)

NOW = datetime(2026, 5, 10, tzinfo=UTC)


@pytest.mark.unit
def test_archived_repo_scores_zero():
    score = repo_health_score(
        stars=10000, pushed_at=NOW, archived=True, now=NOW,
    )
    assert score == 0.0


@pytest.mark.unit
def test_active_popular_repo_scores_high():
    score = repo_health_score(
        stars=50000, pushed_at=NOW - timedelta(days=1),
        forks_count=2000, open_issues_count=20, now=NOW,
    )
    assert 0.85 < score <= 1.0


@pytest.mark.unit
def test_old_unpopular_repo_scores_low():
    score = repo_health_score(
        stars=5, pushed_at=NOW - timedelta(days=400),
        open_issues_count=0, forks_count=0, now=NOW,
    )
    assert score < 0.20


@pytest.mark.unit
def test_recency_dominates_when_stars_low_but_active():
    # Same stars, one pushed yesterday, one a year ago
    fresh = repo_health_score(
        stars=200, pushed_at=NOW - timedelta(days=1), now=NOW,
    )
    stale = repo_health_score(
        stars=200, pushed_at=NOW - timedelta(days=365), now=NOW,
    )
    assert fresh > stale


@pytest.mark.unit
def test_issue_backlog_penalty():
    healthy = repo_health_score(
        stars=1000, pushed_at=NOW, open_issues_count=10, now=NOW,
    )
    backed_up = repo_health_score(
        stars=1000, pushed_at=NOW, open_issues_count=1000, now=NOW,
    )
    assert healthy > backed_up


@pytest.mark.unit
def test_repo_health_in_range():
    """Sanity: across realistic inputs, score stays in [0, 1]."""
    for stars in (0, 100, 5000, 200000):
        for days_back in (0, 30, 180, 720):
            score = repo_health_score(
                stars=stars,
                pushed_at=NOW - timedelta(days=days_back),
                forks_count=stars // 10,
                open_issues_count=days_back,
                now=NOW,
            )
            assert 0.0 <= score <= 1.0


@pytest.mark.unit
def test_repo_health_handles_none_pushed_at():
    score = repo_health_score(stars=100, pushed_at=None, now=NOW)
    assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Issue freshness
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_issue_freshness_just_updated_is_one():
    score = issue_freshness_score(issue_updated_at=NOW, now=NOW)
    assert score == pytest.approx(1.0)


@pytest.mark.unit
def test_issue_freshness_decays_with_time():
    fresh = issue_freshness_score(issue_updated_at=NOW - timedelta(days=1), now=NOW)
    older = issue_freshness_score(issue_updated_at=NOW - timedelta(days=60), now=NOW)
    ancient = issue_freshness_score(issue_updated_at=NOW - timedelta(days=365), now=NOW)
    assert fresh > older > ancient


@pytest.mark.unit
def test_is_recent_enough_within_window():
    assert is_recent_enough(
        issue_created_at=NOW - timedelta(days=30), max_age_days=90, now=NOW,
    )


@pytest.mark.unit
def test_is_recent_enough_outside_window():
    assert not is_recent_enough(
        issue_created_at=NOW - timedelta(days=120), max_age_days=90, now=NOW,
    )


@pytest.mark.unit
def test_health_handles_naive_datetimes():
    """Pushed_at may come from GitHub as naive UTC; shouldn't crash."""
    naive = datetime(2026, 5, 1)  # no tzinfo
    score = repo_health_score(stars=100, pushed_at=naive, now=NOW)
    assert 0.0 <= score <= 1.0
