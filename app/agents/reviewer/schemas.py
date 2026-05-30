"""Pydantic schemas for the Reviewer agent.

The Reviewer is the loop controller: per iteration it asks Patch Writer
for a fix, runs Test Runner, and decides whether to retry, accept, or
give up. Each iteration is recorded as an `Attempt` for transparency and
so the next iteration's prompt can include "here's what didn't work".
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agents.patcher import PatchResult
from app.agents.test_runner.schemas import TestRunResult

# Outcome of the deterministic decision the Reviewer makes after each attempt.
Decision = Literal[
    "retry",       # patch produced output but test_runner says it's broken — try again
    "accept",      # tests passed, ship it
    "give_up",     # something we can't fix from here (no edits, needs_env, error, no_project)
]


class Attempt(BaseModel):
    """One iteration of the patch → test → decide loop."""
    model_config = ConfigDict(extra="ignore")

    attempt_number: int = Field(ge=1)
    patch_result: PatchResult
    test_result: TestRunResult | None = Field(
        default=None,
        description="None when the patch never reached the test phase "
                    "(e.g. patch generation itself failed).",
    )
    decision: Decision
    decision_reason: str = Field(
        description="One-line explanation of why we picked `decision`.",
    )


class ReviewerResult(BaseModel):
    """Final outcome of the loop. Always returned — never raised on logic-level
    failures. Errors that would raise (workspace corrupted, etc.) are bugs."""
    model_config = ConfigDict(extra="ignore")

    success: bool = Field(
        description="True iff some attempt reached `decision='accept'`.",
    )
    summary: str = Field(description="One-line human summary.")
    attempts: list[Attempt] = Field(default_factory=list)
    accepted_attempt_number: int | None = Field(
        default=None,
        description="The attempt index that succeeded, when `success=True`.",
    )
    final_diff: str = Field(
        default="",
        description="Unified diff of the accepted patch, or empty when "
                    "no attempt was accepted.",
    )
    rate_limited: bool = Field(
        default=False,
        description="True when the loop stopped because every LLM provider "
                    "was rate-limited / unavailable — a transient capacity "
                    "wall, not a genuine failure to fix. The Pilot maps this "
                    "to status='rate_limited' so the UI prompts a retry.",
    )
    elapsed_s: float = Field(ge=0.0, default=0.0)
