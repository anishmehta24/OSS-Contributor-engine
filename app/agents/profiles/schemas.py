"""Pydantic schemas for the Skill Profiler agent."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ExperienceSignal = Literal["junior", "mid", "senior"]


class RepoSignal(BaseModel):
    """Per-repo data we collect before LLM synthesis."""
    model_config = ConfigDict(extra="ignore")

    full_name: str
    description: str | None = None
    primary_language: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)  # name -> bytes
    frameworks: list[str] = Field(default_factory=list)
    stars: int = 0
    is_fork: bool = False
    is_archived: bool = False
    pushed_at: datetime | None = None
    recent_commit_messages: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class LLMSynthesis(BaseModel):
    """The structured-output JSON we ask the LLM to return.

    These are the fields the LLM is GOOD at: inferring domains and writing a
    prose summary. The deterministic stuff (languages, frameworks) we extract
    in code from manifests/APIs.
    """
    model_config = ConfigDict(extra="ignore")

    domains: list[str] = Field(
        description="Functional domains the user works in, e.g. ['backend', 'ML', 'devops']",
        max_length=8,
    )
    experience_signal: ExperienceSignal = Field(
        description="Estimated experience level based on repo complexity, count, and history",
    )
    summary: str = Field(
        description="2-3 sentence narrative of the developer's profile",
        max_length=600,
    )


class SkillProfile(BaseModel):
    """Final structured profile we persist and return."""
    model_config = ConfigDict(extra="ignore")

    github_login: str
    github_id: int
    name: str | None = None

    languages: list[str] = Field(default_factory=list)   # top N, deterministic
    frameworks: list[str] = Field(default_factory=list)  # top N, deterministic
    domains: list[str] = Field(default_factory=list)     # LLM-inferred
    experience_signal: ExperienceSignal | None = None    # LLM-inferred
    summary: str | None = None                           # LLM-inferred

    repos_analyzed: int = 0
    profiled_at: datetime
