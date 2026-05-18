"""Pydantic schemas for the Pitch Writer."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Tone = Literal["respectful", "casual"]


class PitchDraft(BaseModel):
    """The structured output the LLM produces.

    The user-facing markdown lives in `comment_md` — that's the comment a
    developer could paste onto the GitHub issue. The other fields are
    metadata for the UI / telemetry.
    """
    model_config = ConfigDict(extra="ignore")

    comment_md: str = Field(
        max_length=2000,
        description="The drafted comment, formatted in GitHub-flavored markdown.",
    )
    asks_questions: bool = Field(
        description="True if the comment includes at least one clarifying question.",
    )
    estimated_timeline: str | None = Field(
        default=None,
        max_length=80,
        description="Human-readable timeline mentioned in the comment, e.g. 'this weekend'.",
    )
    tone: Tone = "respectful"
