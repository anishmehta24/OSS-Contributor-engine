"""Pydantic schemas for the Test Runner agent.

A run consists of one or more PHASES — independent commands executed
in the sandbox. Today: phase 1 = syntax check, phase 2 = test collection.
The Reviewer (Batch 32) reads the classification to decide whether to
loop back to the Patch Writer.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Public enums
# ---------------------------------------------------------------------------

Language = Literal["python", "javascript", "go", "rust", "unknown"]

# What the run tells us about the patch:
#   pass        — every phase exited 0
#   fail        — syntax phase failed (clear "patch broke it" signal)
#   needs_env   — syntax OK but a later phase failed (probably missing
#                 deps the sandbox can't install yet; NOT necessarily
#                 the patch's fault)
#   error       — sandbox infra problem (image missing, timeout, etc.)
#   no_project  — couldn't figure out what kind of project this is
Classification = Literal["pass", "fail", "needs_env", "error", "no_project"]


# ---------------------------------------------------------------------------
# Per-phase result
# ---------------------------------------------------------------------------

class PhaseResult(BaseModel):
    """One command run inside the sandbox."""
    model_config = ConfigDict(extra="ignore")

    name: str = Field(description="Stable id like 'syntax_check' or 'collect_tests'.")
    argv: list[str]
    exit_code: int
    duration_s: float = Field(ge=0.0)
    stdout: str = Field(default="", description="Tail-truncated.")
    stderr: str = Field(default="", description="Tail-truncated.")
    timed_out: bool = False
    skipped: bool = Field(
        default=False,
        description=(
            "True when the runner short-circuited (e.g. skipped collection "
            "because syntax check already failed)."
        ),
    )

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.skipped


# ---------------------------------------------------------------------------
# Top-level result
# ---------------------------------------------------------------------------

class TestRunResult(BaseModel):
    """Everything the Reviewer / human needs to read."""
    model_config = ConfigDict(extra="ignore")

    language: Language
    classification: Classification
    summary: str = Field(description="One-line human-readable summary.")
    phases: list[PhaseResult] = Field(default_factory=list)
    duration_s: float = Field(ge=0.0, default=0.0)
    # The Reviewer can quote this verbatim to the Patch Writer on retry.
    failure_excerpt: str = Field(
        default="",
        description=(
            "First ~2KB of the failing phase's stderr+stdout, intended for "
            "feedback to a downstream agent. Empty for clean runs."
        ),
    )
