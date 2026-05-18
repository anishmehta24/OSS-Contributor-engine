"""Pure-function tests for the Triager scoring components."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.triager.schemas import RankingWeights
from app.agents.triager.scoring import (
    combine,
    difficulty_match_score,
    distance_to_similarity,
    freshness_score,
    impact_score,
)

NOW = datetime(2026, 5, 10, tzinfo=UTC)


# ---------------------------------------------------------------------------
# distance_to_similarity
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_distance_zero_is_perfect_similarity():
    assert distance_to_similarity(0.0) == 1.0


@pytest.mark.unit
def test_distance_two_is_zero_similarity():
    assert distance_to_similarity(2.0) == 0.0


@pytest.mark.unit
def test_distance_one_is_half():
    assert distance_to_similarity(1.0) == pytest.approx(0.5)


@pytest.mark.unit
def test_negative_distance_clamps_to_one():
    assert distance_to_similarity(-0.1) == 1.0


@pytest.mark.unit
def test_huge_distance_clamps_to_zero():
    assert distance_to_similarity(99.0) == 0.0


# ---------------------------------------------------------------------------
# freshness_score
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_freshness_just_updated_is_one():
    assert freshness_score(NOW, now=NOW) == pytest.approx(1.0)


@pytest.mark.unit
def test_freshness_decays():
    fresh = freshness_score(NOW - timedelta(days=1), now=NOW)
    older = freshness_score(NOW - timedelta(days=60), now=NOW)
    ancient = freshness_score(NOW - timedelta(days=365), now=NOW)
    assert fresh > older > ancient


@pytest.mark.unit
def test_freshness_handles_naive_datetime():
    naive = datetime(2026, 5, 1)
    assert 0.0 <= freshness_score(naive, now=NOW) <= 1.0


# ---------------------------------------------------------------------------
# impact_score
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_impact_zero_stars_handled():
    # log10(max(0, 1)) = 0 → 0
    assert impact_score(0) == 0.0


@pytest.mark.unit
def test_impact_caps_at_one():
    assert impact_score(1_000_000) == 1.0


@pytest.mark.unit
def test_impact_increases_with_stars():
    assert impact_score(10) < impact_score(1000) < impact_score(50000)


# ---------------------------------------------------------------------------
# difficulty_match_score
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_difficulty_exact_match():
    assert difficulty_match_score("easy", "easy") == 1.0
    assert difficulty_match_score("hard", "hard") == 1.0


@pytest.mark.unit
def test_difficulty_adjacent_half_credit():
    assert difficulty_match_score("medium", "easy") == 0.5
    assert difficulty_match_score("easy", "medium") == 0.5
    assert difficulty_match_score("medium", "hard") == 0.5


@pytest.mark.unit
def test_difficulty_opposite_quarter_credit():
    assert difficulty_match_score("easy", "hard") == 0.25
    assert difficulty_match_score("hard", "easy") == 0.25


@pytest.mark.unit
def test_difficulty_any_or_unknown_is_neutral():
    assert difficulty_match_score("easy", "any") == 0.7
    assert difficulty_match_score(None, "easy") == 0.7


# ---------------------------------------------------------------------------
# combine
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_combine_all_max_gives_one():
    w = RankingWeights()
    assert combine(
        skill=1, repo_health=1, freshness=1, difficulty=1, impact=1, weights=w,
    ) == pytest.approx(1.0)


@pytest.mark.unit
def test_combine_all_zero_gives_zero():
    w = RankingWeights()
    assert combine(
        skill=0, repo_health=0, freshness=0, difficulty=0, impact=0, weights=w,
    ) == 0.0


@pytest.mark.unit
def test_combine_respects_weight_dominance():
    # If skill_match weight is 100% of total, score should == skill component
    w = RankingWeights(
        skill_match=1.0, repo_health=0, freshness=0, difficulty_match=0, impact=0,
    )
    assert combine(
        skill=0.7, repo_health=1, freshness=1, difficulty=1, impact=1, weights=w,
    ) == pytest.approx(0.7)


@pytest.mark.unit
def test_weights_normalize_to_sum_one():
    w = RankingWeights(
        skill_match=2.0, repo_health=2.0, freshness=2.0,
        difficulty_match=2.0, impact=2.0,
    ).normalized()
    total = (
        w.skill_match + w.repo_health + w.freshness
        + w.difficulty_match + w.impact
    )
    assert total == pytest.approx(1.0)


@pytest.mark.unit
def test_default_weights_already_sum_to_one():
    w = RankingWeights()
    total = (
        w.skill_match + w.repo_health + w.freshness
        + w.difficulty_match + w.impact
    )
    assert total == pytest.approx(1.0)
