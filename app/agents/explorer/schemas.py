"""Pydantic schemas for the Code Explorer agent."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ScannedFile(BaseModel):
    """One file the deterministic scanner found and pre-ranked.

    Internal — exposed only because the LLM prompt builder needs it and a few
    tests assert on it. Not part of the agent's external return value.
    """
    model_config = ConfigDict(extra="ignore")

    path: str = Field(description="POSIX path relative to repo root")
    size_bytes: int = Field(ge=0)
    score: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(
        default_factory=list,
        description="Human-readable reasons the scanner ranked this file "
                    "(e.g. 'keyword:auth', 'ref:src/auth.py', 'dir:tests/')",
    )


class FileCandidate(BaseModel):
    """A file the Code Explorer believes is relevant to the issue.

    `confidence` is the LLM's post-rerank judgment (or, if the LLM step was
    skipped, the raw deterministic score normalized to 0-1).

    `signals` always carries the deterministic evidence so a downstream
    Patch Writer can tell whether a file made the list because it actually
    matches the issue (`ref:`, `keyword:`) or just because it lives in a
    suggestive directory (`dir:`).
    """
    model_config = ConfigDict(extra="ignore")

    path: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(
        default="",
        description="One-sentence LLM rationale, ≤30 words. Empty when "
                    "LLM rerank was skipped.",
    )
    signals: list[str] = Field(default_factory=list)
    size_bytes: int = Field(default=0, ge=0)


class ExplorationResult(BaseModel):
    """Top-level Code Explorer output."""
    model_config = ConfigDict(extra="ignore")

    repo: str = Field(description="owner/name")
    issue_title: str
    candidates: list[FileCandidate] = Field(
        default_factory=list,
        description="Sorted by confidence, descending.",
    )

    # Telemetry — useful for tuning weights later.
    files_scanned: int = Field(ge=0, default=0)
    files_pre_ranked: int = Field(ge=0, default=0)
    used_llm_rerank: bool = False
    elapsed_s: float = Field(ge=0.0, default=0.0)


# Inner schema the LLM is asked to produce. Kept module-private — callers
# get an `ExplorationResult` instead.
class _LLMRankItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=400)


class _LLMRankOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    candidates: list[_LLMRankItem] = Field(default_factory=list)
