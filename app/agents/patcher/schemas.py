"""Pydantic schemas for the Patch Writer agent.

Two layers:
  - LLM-facing: `PatchAttempt`, `CodeEdit`. These match the JSON shape we
    ask the model for and validate with `call_llm(response_model=...)`.
  - Caller-facing: `PatchResult`, `AppliedEdit`. What `write_patch` returns.

Keeping them separate means a flaky LLM that returns garbage doesn't
contaminate the public type; we always materialize a PatchResult that
records what happened (good or bad).
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CodeEdit(BaseModel):
    """One search-and-replace edit on one file.

    We deliberately use search-and-replace instead of line numbers or raw
    unified diffs — LLMs are reliable at the former and terrible at the
    latter (line counts drift, context blocks misalign). Aider, Cline,
    and friends all landed on the same answer.
    """
    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="Repo-relative POSIX path.")
    search: str = Field(
        default="",
        description=(
            "EXACT text to find. Whitespace-sensitive. Must match exactly "
            "once in the file. Empty = create a new file with `replace` as "
            "its content."
        ),
    )
    replace: str = Field(
        default="",
        description="Text to substitute in place of `search`.",
    )
    explanation: str = Field(
        default="",
        max_length=400,
        description="One-sentence rationale for THIS edit, ≤25 words.",
    )


class PatchAttempt(BaseModel):
    """Full LLM response — what the model thinks the right fix looks like."""
    model_config = ConfigDict(extra="ignore")

    summary: str = Field(
        default="",
        max_length=1000,
        description="1-2 sentence narrative of the overall fix.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0-1, how confident the model is this resolves the issue.",
    )
    edits: list[CodeEdit] = Field(default_factory=list)


class AppliedEdit(BaseModel):
    """One edit that we successfully wrote to disk."""
    model_config = ConfigDict(extra="ignore")

    path: str
    explanation: str = ""
    new_file: bool = False
    # Byte-level deltas — used for telemetry + the "is this too big?" check.
    bytes_added: int = Field(default=0, ge=0)
    bytes_removed: int = Field(default=0, ge=0)


class PriorAttempt(BaseModel):
    """One failed patch attempt — passed back into the Patch Writer prompt
    so the LLM can learn from what didn't work.

    Used by the Reviewer (Batch 32). Stays narrow on purpose: just enough
    that the model can spot "I tried X and it failed for reason Y, so
    don't try X again".
    """
    model_config = ConfigDict(extra="ignore")

    attempt_number: int = Field(ge=1)
    summary: str = ""
    failure_excerpt: str = Field(
        default="",
        description="stderr/stdout tail from the failing test phase.",
    )
    edits_applied_paths: list[str] = Field(default_factory=list)


class PatchResult(BaseModel):
    """Top-level result returned by `write_patch`.

    `success=True` only when every requested edit applied AND a non-empty
    diff was produced. The caller (Reviewer in Batch 32) inspects `error`
    and `edits_attempted - len(edits_applied)` to decide whether to retry.
    """
    model_config = ConfigDict(extra="ignore")

    success: bool
    summary: str = ""
    confidence: float = 0.0
    edits_attempted: int = 0
    edits_applied: list[AppliedEdit] = Field(default_factory=list)
    unified_diff: str = Field(
        default="",
        description="Output of `git diff` in the workspace after applying.",
    )
    error: str | None = None
    rate_limited: bool = Field(
        default=False,
        description="True when the failure was every LLM provider being "
                    "rate-limited / unavailable (a transient capacity wall, "
                    "not a real inability to fix). Callers should retry, not "
                    "treat this as a rejection.",
    )
