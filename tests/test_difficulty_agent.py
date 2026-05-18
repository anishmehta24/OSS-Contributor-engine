"""Tests for the difficulty estimator (heuristic + LLM fallback)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.hunter.difficulty import (
    estimate_difficulty,
    heuristic_difficulty,
)

# ---------------------------------------------------------------------------
# Heuristic-only path
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_heuristic_matches_good_first_issue():
    assert heuristic_difficulty(["good first issue", "bug"]) == "easy"


@pytest.mark.unit
def test_heuristic_matches_hard_label():
    assert heuristic_difficulty(["epic", "feature"]) == "hard"


@pytest.mark.unit
def test_heuristic_returns_none_when_ambiguous():
    assert heuristic_difficulty(["bug", "enhancement"]) is None


@pytest.mark.unit
def test_heuristic_handles_case_insensitive():
    assert heuristic_difficulty(["Good First Issue"]) == "easy"
    assert heuristic_difficulty(["EPIC"]) == "hard"


# ---------------------------------------------------------------------------
# LLM fallback path
# ---------------------------------------------------------------------------

class _FakeRouter:
    def __init__(self, json_str: str):
        self._json = json_str
        self.call_count = 0
        self.model_list = [{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}]

    def completion(self, **_):
        self.call_count += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._json))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=20),
            _hidden_params={"response_cost": 0.0001},
        )


@pytest.mark.unit
def test_estimate_calls_llm_when_heuristic_silent(session):
    router = _FakeRouter('{"difficulty": "medium", "reason": "multiple files"}')
    result = estimate_difficulty(
        router,
        title="Refactor request handler", body="Need to touch handlers and tests",
        labels=["bug"], session=session,
    )
    assert result == "medium"
    assert router.call_count == 1


@pytest.mark.unit
def test_estimate_skips_llm_when_heuristic_decides(session):
    router = _FakeRouter('{"difficulty": "hard", "reason": "x"}')
    result = estimate_difficulty(
        router,
        title="Typo in README", body="One char fix",
        labels=["good first issue"], session=session,
    )
    assert result == "easy"
    assert router.call_count == 0


@pytest.mark.unit
def test_estimate_falls_back_to_medium_on_llm_parse_failure(session):
    router = _FakeRouter("not valid json")
    result = estimate_difficulty(
        router,
        title="x", body="y", labels=["bug"], session=session,
    )
    assert result == "medium"
