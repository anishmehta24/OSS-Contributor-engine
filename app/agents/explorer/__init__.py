"""Code Explorer agent (v3 — Autonomous Contribution Pilot).

Public surface:
    from app.agents.explorer import explore, ExplorationResult, FileCandidate
"""
from app.agents.explorer.explorer import explore
from app.agents.explorer.schemas import (
    ExplorationResult,
    FileCandidate,
    ScannedFile,
)

__all__ = ["ExplorationResult", "FileCandidate", "ScannedFile", "explore"]
