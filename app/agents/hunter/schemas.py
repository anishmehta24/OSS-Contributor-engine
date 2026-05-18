"""Pydantic schemas for the Issue Hunter."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.hunter.queries import BEGINNER_LABELS, DEFAULT_LANGUAGES

Difficulty = Literal["easy", "medium", "hard"]
HuntMode = Literal["general", "gsoc"]


class HunterConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: HuntMode = "general"
    languages: list[str] = Field(default_factory=lambda: list(DEFAULT_LANGUAGES))
    labels: list[str] = Field(default_factory=lambda: list(BEGINNER_LABELS))
    updated_since_days: int = 30
    min_stars: int = 100
    max_issues_per_query: int = 20
    max_total_issues: int = 200
    enable_difficulty_llm: bool = True
    enable_embeddings: bool = True
    # GSoC mode only — how many recent years count as "active" when
    # selecting orgs from the gsoc_orgs table.
    gsoc_recent_years: int = 3


class IssueCandidate(BaseModel):
    """Lightweight handle for an issue we're about to process."""
    model_config = ConfigDict(extra="ignore")

    repo_full_name: str
    issue_number: int
    issue_id: int
    title: str
    body: str | None
    labels: list[str]
    html_url: str
    issue_created_at: datetime
    issue_updated_at: datetime


class HuntStats(BaseModel):
    """Reported by the hunter at the end of a run."""
    model_config = ConfigDict(extra="ignore")

    queries_executed: int = 0
    issues_seen: int = 0
    issues_kept: int = 0
    issues_persisted: int = 0
    embeddings_generated: int = 0
    difficulty_calls: int = 0
    errors: int = 0
    started_at: datetime
    finished_at: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()
