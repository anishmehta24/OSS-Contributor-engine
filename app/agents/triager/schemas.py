"""Pydantic schemas for the Triager."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DifficultyPref = Literal["any", "easy", "medium", "hard"]


class RankingWeights(BaseModel):
    """Weights applied to each scoring component. Should sum to ~1.0."""
    model_config = ConfigDict(extra="ignore")

    skill_match: float = 0.50      # cosine sim user_skill vs issue
    repo_health: float = 0.20
    freshness: float = 0.15        # how recently the issue was updated
    difficulty_match: float = 0.10
    impact: float = 0.05           # log(stars) proxy

    def normalized(self) -> RankingWeights:
        total = (
            self.skill_match + self.repo_health + self.freshness
            + self.difficulty_match + self.impact
        )
        if total == 0:
            return self
        return RankingWeights(
            skill_match=self.skill_match / total,
            repo_health=self.repo_health / total,
            freshness=self.freshness / total,
            difficulty_match=self.difficulty_match / total,
            impact=self.impact / total,
        )


class RankedMatch(BaseModel):
    """One row in the ranked output."""
    model_config = ConfigDict(extra="ignore")

    issue_id: int
    issue_number: int
    repo_full_name: str
    title: str
    html_url: str
    labels: list[str] = Field(default_factory=list)
    difficulty: str | None = None

    # Score breakdown — useful for explainability and debugging
    skill_match: float
    repo_health: float
    freshness: float
    difficulty_match: float
    impact: float
    final_score: float

    # 1-line LLM-generated explanation (optional)
    why_it_fits: str | None = None

    issue_updated_at: datetime
    stargazers_count: int
