"""Patcher-specific errors."""


class PatcherError(Exception):
    """Base — never raised directly."""


class EditApplyError(PatcherError):
    """One specific edit failed to apply (search not found, ambiguous, etc.)."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        super().__init__(message)
        self.path = path


class NoEditsError(PatcherError):
    """LLM returned a valid patch with zero edits — nothing to apply."""
