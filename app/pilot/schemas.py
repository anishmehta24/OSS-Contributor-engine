"""HTTP-shape Pydantic models for the Pilot Coordinator.

ORM-shape lives in `app/db/models.py`. The schemas here are the read-side
projections returned by FastAPI routes — they intentionally narrow the
ORM surface (no relationships, ISO timestamps as strings, transcript
already parsed).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PilotStatus = Literal[
    "queued", "running", "accepted", "rejected", "rate_limited", "failed",
]


class PilotRunRow(BaseModel):
    """One row from /investigations/{id}/pilot."""
    model_config = ConfigDict(extra="ignore")

    id: str
    investigation_id: str
    status: PilotStatus
    summary: str | None = None
    attempts_made: int = 0
    accepted_attempt_number: int | None = None
    accepted_diff: str | None = None
    transcript: dict | None = Field(
        default=None,
        description="The full ReviewerResult dump, parsed for the client.",
    )
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    # ---- Push (Batch 34) ----
    # All null until the accepted diff is pushed to the user's fork.
    fork_url: str | None = None
    branch_ref: str | None = None
    pushed_at: str | None = None
    push_error: str | None = None

    # ---- Draft PR opened on upstream (Batch 35) ----
    # All null until the PR is opened. pr_error fills on failure; the
    # others stay null until success.
    pr_url: str | None = None
    pr_number: int | None = None
    pr_opened_at: str | None = None
    pr_error: str | None = None


class CreatePilotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pilot_id: str
    status: PilotStatus = "queued"


class PushPilotResponse(BaseModel):
    """Response from POST .../pilot/{pilot_id}/push."""
    model_config = ConfigDict(extra="forbid")
    pilot_id: str
    status: Literal["push_queued"] = "push_queued"


class OpenPRResponse(BaseModel):
    """Response from POST .../pilot/{pilot_id}/pr."""
    model_config = ConfigDict(extra="forbid")
    pilot_id: str
    status: Literal["pr_queued"] = "pr_queued"


class PilotConfig(BaseModel):
    """Caller-overridable knobs. All optional — sensible defaults baked in."""
    model_config = ConfigDict(extra="forbid")
    max_attempts: int = Field(default=3, ge=1, le=8)
    max_files: int = Field(default=5, ge=1, le=15)
    test_timeout_s: int = Field(default=120, ge=10, le=600)
