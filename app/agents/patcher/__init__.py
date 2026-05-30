"""Patch Writer agent (v3 — Autonomous Contribution Pilot).

Public surface:
    from app.agents.patcher import write_patch, PatchResult, AppliedEdit
"""
from app.agents.patcher.exceptions import (
    EditApplyError,
    NoEditsError,
    PatcherError,
)
from app.agents.patcher.patcher import write_patch
from app.agents.patcher.schemas import (
    AppliedEdit,
    CodeEdit,
    PatchAttempt,
    PatchResult,
    PriorAttempt,
)

__all__ = [
    "AppliedEdit",
    "CodeEdit",
    "EditApplyError",
    "NoEditsError",
    "PatchAttempt",
    "PatchResult",
    "PatcherError",
    "PriorAttempt",
    "write_patch",
]
