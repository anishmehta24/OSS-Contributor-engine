"""GitHub client exceptions. Surfaced clearly so callers can handle each case."""
from __future__ import annotations


class GitHubError(Exception):
    """Base for all GitHub client errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthError(GitHubError):
    """401: token missing, expired, or revoked."""


class NotFoundError(GitHubError):
    """404: resource doesn't exist or is inaccessible."""


class RateLimitError(GitHubError):
    """403/429: primary or secondary rate limit hit. Includes retry timing."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
        reset_at: int | None = None,
    ) -> None:
        super().__init__(message, status_code=403)
        self.retry_after_seconds = retry_after_seconds
        self.reset_at = reset_at
