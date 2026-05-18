"""Request/response schemas for the HTTP API.

Internal schemas (SkillProfile, RankedMatch, HuntStats, etc.) come from the
agent modules. This file defines API-shaped wrappers, request bodies, and
the error envelope.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.hunter.schemas import HuntMode, HuntStats
from app.agents.profiles.schemas import SkillProfile
from app.agents.triager.schemas import RankedMatch

# ---------------------------------------------------------------------------
# Error envelope (used by the global exception handler)
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: str
    detail: str | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["ok"] = "ok"
    version: str
    services: dict[str, bool]  # name -> configured


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class CreateUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    github_login: str = Field(min_length=1, max_length=64)


class UserSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    github_login: str
    github_id: int
    name: str | None = None
    has_skill_profile: bool
    created_at: datetime
    updated_at: datetime


# Re-exports so the OpenAPI schema includes them under one module
class ProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: SkillProfile


class RankedMatchesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    github_login: str
    count: int
    matches: list[RankedMatch]


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class HuntRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: HuntMode = "general"
    languages: list[str] | None = None
    max_total_issues: int = Field(default=50, ge=1, le=500)
    enable_difficulty_llm: bool = True
    enable_embeddings: bool = True


class HuntResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stats: HuntStats


class DbStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    users: int
    user_skills: int
    repos: int
    issues: int
    investigations: int
    agent_runs: int
    issues_with_embeddings: int
