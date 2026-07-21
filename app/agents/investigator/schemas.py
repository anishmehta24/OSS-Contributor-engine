"""Pydantic schemas for the Investigator crew.

Each sub-agent has its own structured output. The Synthesizer takes all
three and produces the final InvestigationReport.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

EffortEstimate = Literal["under-1-hour", "few-hours", "weekend", "multi-day"]


# ---------------------------------------------------------------------------
# Per-agent outputs
# ---------------------------------------------------------------------------

class IssueRequirements(BaseModel):
    """Issue Analyst output — what the user is actually asking for."""
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(description="2-3 sentence restatement of the issue")
    requirements: list[str] = Field(default_factory=list, max_length=12)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=8)
    open_questions: list[str] = Field(default_factory=list, max_length=6)
    technical_keywords: list[str] = Field(default_factory=list, max_length=12)


class CandidateFile(BaseModel):
    """One file the Repo Mapper thinks is relevant."""
    model_config = ConfigDict(extra="ignore")
    path: str
    reason: str = Field(max_length=200)


class RepoMap(BaseModel):
    """Repo Mapper output — which files to look at and why."""
    model_config = ConfigDict(extra="ignore")
    repo_summary: str = Field(default="", max_length=400)
    candidate_files: list[CandidateFile] = Field(default_factory=list, max_length=15)


class HistoricalContext(BaseModel):
    """History Detective output — what's been changing recently in this area."""
    model_config = ConfigDict(extra="ignore")
    recent_themes: list[str] = Field(default_factory=list, max_length=8)
    notable_commits: list[str] = Field(default_factory=list, max_length=8)
    summary: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Final output
# ---------------------------------------------------------------------------

class InvestigationReport(BaseModel):
    """Synthesizer output — the report a developer would actually read."""
    model_config = ConfigDict(extra="ignore")

    issue_summary: str = ""
    candidate_files: list[CandidateFile] = Field(default_factory=list)
    # No max_length here: an over-long value shouldn't fail validation (that
    # would drop the whole report). The validator caps it instead.
    suggested_approach: str = ""
    open_questions: list[str] = Field(default_factory=list, max_length=6)
    risks: list[str] = Field(default_factory=list, max_length=6)
    estimated_effort: EffortEstimate = "few-hours"

    @field_validator("issue_summary", "suggested_approach", mode="before")
    @classmethod
    def _coerce_text(cls, v: object) -> str:
        """LLMs sometimes return these fields as a JSON array of paragraphs or
        bullet points instead of a single string. Join a list into one markdown
        string and cap the length, so a well-formed answer in the "wrong" shape
        doesn't fail validation and blank the whole report."""
        if v is None:
            return ""
        if isinstance(v, (list, tuple)):
            v = "\n".join(str(item).strip() for item in v if str(item).strip())
        return str(v)[:4000]


class InvestigationResult(BaseModel):
    """End-to-end result returned by the orchestrator."""
    model_config = ConfigDict(extra="ignore")

    investigation_id: str
    repo_full_name: str
    issue_number: int
    issue_url: str
    status: Literal["completed", "failed"]
    report: InvestigationReport | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    markdown_report: str | None = None
