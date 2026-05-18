"""ORM models. Vectors live in separate vec0 virtual tables (see app/db/vector.py).

Tables:
    users               — one row per GitHub user we've ever profiled
    user_skills         — one row per user (1:1 with users), Skill Profiler output
    repos               — cached repo metadata (Issue Hunter populates)
    issues              — candidate OSS issues (Issue Hunter populates)
    investigations      — one row per "investigate this issue for this user" request
    agent_runs          — telemetry: every LLM call writes here (tokens, cost, latency)
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utcnow() -> datetime:
    """Used as default at app level (db default uses func.now() server-side)."""
    return datetime.utcnow()


def _uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Users + skill profile
# ---------------------------------------------------------------------------

class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    github_login: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    github_id: Mapped[int] = mapped_column(unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(128))

    skill: Mapped[UserSkill | None] = relationship(
        "UserSkill", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    investigations: Mapped[list[Investigation]] = relationship(
        "Investigation", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User #{self.id} {self.github_login}>"


class UserSkill(Base, TimestampMixin):
    __tablename__ = "user_skills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    frameworks: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    domains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    experience_signal: Mapped[str | None] = mapped_column(String(16))  # junior/mid/senior
    summary: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship("User", back_populates="skill")

    def __repr__(self) -> str:
        return f"<UserSkill user_id={self.user_id} langs={self.languages}>"


# ---------------------------------------------------------------------------
# Repos + issues (Issue Hunter populates)
# ---------------------------------------------------------------------------

class Repo(Base, TimestampMixin):
    __tablename__ = "repos"

    # Use GitHub's numeric id as the PK so we can upsert cleanly.
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
    full_name: Mapped[str] = mapped_column(String(256), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(64), index=True)
    stargazers_count: Mapped[int] = mapped_column(default=0, nullable=False)
    forks_count: Mapped[int] = mapped_column(default=0, nullable=False)
    open_issues_count: Mapped[int] = mapped_column(default=0, nullable=False)
    archived: Mapped[bool] = mapped_column(default=False, nullable=False)
    fork: Mapped[bool] = mapped_column(default=False, nullable=False)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime)
    default_branch: Mapped[str] = mapped_column(String(64), default="main", nullable=False)
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Computed by Issue Hunter (Batch 5).
    health_score: Mapped[float | None] = mapped_column()

    issues: Mapped[list[Issue]] = relationship(
        "Issue", back_populates="repo", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Repo {self.full_name} ★{self.stargazers_count}>"


class Issue(Base, TimestampMixin):
    __tablename__ = "issues"
    __table_args__ = (
        UniqueConstraint("repo_id", "number", name="uq_issue_repo_number"),
        Index("ix_issue_state_difficulty", "state", "difficulty"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)  # GitHub's id
    repo_id: Mapped[int] = mapped_column(
        ForeignKey("repos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    labels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    comments_count: Mapped[int] = mapped_column(default=0, nullable=False)
    html_url: Mapped[str] = mapped_column(String(512), nullable=False)
    issue_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    issue_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    # LLM-assigned (Batch 5)
    difficulty: Mapped[str | None] = mapped_column(String(16))  # easy/medium/hard

    repo: Mapped[Repo] = relationship("Repo", back_populates="issues")

    def __repr__(self) -> str:
        return f"<Issue {self.repo.full_name if self.repo else '?'}#{self.number}>"


# ---------------------------------------------------------------------------
# Investigations + agent telemetry
# ---------------------------------------------------------------------------

class Investigation(Base, TimestampMixin):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", nullable=False, index=True)
    # queued | running | completed | failed
    report_md: Mapped[str | None] = mapped_column(Text)
    pitch_md: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship("User", back_populates="investigations")
    issue: Mapped[Issue] = relationship("Issue")
    agent_runs: Mapped[list[AgentRun]] = relationship(
        "AgentRun", back_populates="investigation", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Investigation {self.id[:8]} status={self.status}>"


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_run_investigation_status", "investigation_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    investigation_id: Mapped[str | None] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # gemini/groq/ollama
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_depth: Mapped[int] = mapped_column(default=0, nullable=False)
    tokens_in: Mapped[int] = mapped_column(default=0, nullable=False)
    tokens_out: Mapped[int] = mapped_column(default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(default=0.0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="success", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)

    investigation: Mapped[Investigation | None] = relationship(
        "Investigation", back_populates="agent_runs"
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent_name} {self.provider} {self.tokens_in}+{self.tokens_out}>"


# ---------------------------------------------------------------------------
# OAuth tokens (Batch 13)
# ---------------------------------------------------------------------------

class OAuthToken(Base, TimestampMixin):
    """One row per user — the latest GitHub OAuth token, encrypted at rest.

    Replacing on re-login (not appending) keeps the table small and avoids
    juggling rotation of stale tokens.
    """
    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), default="github", nullable=False)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer", nullable=False)

    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return f"<OAuthToken user_id={self.user_id} scopes={self.scopes}>"


# ---------------------------------------------------------------------------
# GSoC orgs (Batch 17) — orgs that participate in Google Summer of Code
# ---------------------------------------------------------------------------

class GsocOrg(Base, TimestampMixin):
    """One row per organization that has participated in GSoC.

    Populated by:
      - JSON seed loader (Batch 17) — well-known orgs hard-coded
      - GSoC org scraper (Batch 18) — pulls official lists per year

    The Issue Hunter consults this table to restrict its search to orgs that
    are GSoC-relevant when running in GSoC mode.
    """
    __tablename__ = "gsoc_orgs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    github_login: Mapped[str | None] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    homepage_url: Mapped[str | None] = mapped_column(String(512))
    project_ideas_url: Mapped[str | None] = mapped_column(String(512))
    primary_languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    years_participated: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)
    last_seen_year: Mapped[int | None] = mapped_column(index=True)
    seed_source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # "manual" (JSON seed) | "scraper" (GSoC site)

    def __repr__(self) -> str:
        return f"<GsocOrg {self.slug} gh={self.github_login} years={self.years_participated}>"


# Re-export for convenience.
__all__ = [
    "AgentRun",
    "GsocOrg",
    "Investigation",
    "Issue",
    "OAuthToken",
    "Repo",
    "User",
    "UserSkill",
]


def all_models() -> list[type[Base]]:
    """Used by tests and init scripts to enumerate tables."""
    return [User, UserSkill, Repo, Issue, Investigation, AgentRun, OAuthToken, GsocOrg]


# Type stub to silence linters about Any below.
_ = Any
