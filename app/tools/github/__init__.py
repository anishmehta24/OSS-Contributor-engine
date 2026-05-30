"""Async GitHub API client with rate-limit and ETag handling.

Public API:
    from app.tools.github import GitHubClient, User, Repo, Issue, SearchResult
    from app.tools.github import GitHubError, RateLimitError, NotFoundError, AuthError
"""
from app.tools.github.client import GitHubClient
from app.tools.github.exceptions import (
    AuthError,
    GitHubError,
    NotFoundError,
    RateLimitError,
)
from app.tools.github.models import (
    Commit,
    Issue,
    IssueLabel,
    PullRequest,
    Repo,
    SearchResult,
    User,
)

__all__ = [
    "AuthError",
    "Commit",
    "GitHubClient",
    "GitHubError",
    "Issue",
    "IssueLabel",
    "NotFoundError",
    "PullRequest",
    "RateLimitError",
    "Repo",
    "SearchResult",
    "User",
]
