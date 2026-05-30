"""Pydantic models for GitHub API responses.

Only the fields we actually use. Adding more fields later is cheap;
parsing fields we don't use isn't.
"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class _GHModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class User(_GHModel):
    id: int
    login: str
    name: str | None = None
    bio: str | None = None
    company: str | None = None
    public_repos: int = 0
    followers: int = 0
    html_url: str


class IssueLabel(_GHModel):
    name: str
    color: str | None = None
    description: str | None = None


class Repo(_GHModel):
    id: int
    full_name: str  # "owner/name"
    name: str
    description: str | None = None
    language: str | None = None
    stargazers_count: int = Field(default=0, alias="stargazers_count")
    forks_count: int = Field(default=0, alias="forks_count")
    open_issues_count: int = Field(default=0, alias="open_issues_count")
    archived: bool = False
    fork: bool = False
    pushed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    default_branch: str = "main"
    html_url: str
    topics: list[str] = Field(default_factory=list)


class Issue(_GHModel):
    id: int
    number: int
    title: str
    body: str | None = None
    state: str  # "open" | "closed"
    labels: list[IssueLabel] = Field(default_factory=list)
    comments: int = 0
    html_url: str
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    repository_url: str | None = None  # present in search results

    @property
    def repo_full_name(self) -> str | None:
        """Extract 'owner/repo' from repository_url when present."""
        if not self.repository_url:
            return None
        # repository_url format: https://api.github.com/repos/{owner}/{repo}
        return self.repository_url.split("/repos/", 1)[-1]


class Commit(_GHModel):
    sha: str
    message: str
    author_login: str | None = None
    author_date: datetime | None = None
    html_url: str


class SearchResult(_GHModel, Generic[T]):
    total_count: int
    incomplete_results: bool = False
    items: list[T]


class PullRequest(_GHModel):
    """Slim view of a created PR — what we surface back to the caller of
    `create_pull_request`. GitHub returns much more; we ignore the rest."""

    id: int
    number: int
    state: str  # "open" | "closed"
    draft: bool = False
    title: str
    body: str | None = None
    html_url: str
    created_at: datetime | None = None
    merged_at: datetime | None = None
