"""Validation that our Pydantic models accept realistic GitHub payloads."""
from __future__ import annotations

import pytest

from app.tools.github.models import Issue, Repo, SearchResult, User


@pytest.mark.unit
def test_user_minimal_payload():
    payload = {
        "id": 1,
        "login": "octocat",
        "html_url": "https://github.com/octocat",
        "name": "The Octocat",
        "public_repos": 8,
    }
    u = User.model_validate(payload)
    assert u.login == "octocat"
    assert u.public_repos == 8
    assert u.name == "The Octocat"


@pytest.mark.unit
def test_user_extra_fields_ignored():
    payload = {
        "id": 1,
        "login": "octocat",
        "html_url": "https://github.com/octocat",
        "node_id": "MDQ6VXNlcjE=",
        "avatar_url": "https://...",
        "gravatar_id": "",
    }
    u = User.model_validate(payload)
    assert u.login == "octocat"


@pytest.mark.unit
def test_repo_realistic_payload():
    payload = {
        "id": 12345,
        "full_name": "fastapi/fastapi",
        "name": "fastapi",
        "description": "FastAPI framework",
        "language": "Python",
        "stargazers_count": 75000,
        "forks_count": 6300,
        "open_issues_count": 25,
        "archived": False,
        "fork": False,
        "default_branch": "master",
        "html_url": "https://github.com/fastapi/fastapi",
        "topics": ["python", "api"],
        "pushed_at": "2024-10-01T12:00:00Z",
        "created_at": "2018-12-08T08:21:47Z",
        "updated_at": "2024-10-01T12:00:00Z",
    }
    r = Repo.model_validate(payload)
    assert r.full_name == "fastapi/fastapi"
    assert r.stargazers_count == 75000
    assert r.language == "Python"
    assert r.topics == ["python", "api"]


@pytest.mark.unit
def test_issue_repo_full_name_extracted_from_url():
    payload = {
        "id": 1,
        "number": 42,
        "title": "Bug",
        "state": "open",
        "labels": [{"name": "bug", "color": "ff0000"}],
        "comments": 3,
        "html_url": "https://github.com/foo/bar/issues/42",
        "created_at": "2024-09-01T00:00:00Z",
        "updated_at": "2024-09-02T00:00:00Z",
        "repository_url": "https://api.github.com/repos/foo/bar",
    }
    i = Issue.model_validate(payload)
    assert i.repo_full_name == "foo/bar"
    assert i.number == 42
    assert len(i.labels) == 1
    assert i.labels[0].name == "bug"


@pytest.mark.unit
def test_issue_without_repository_url_returns_none():
    payload = {
        "id": 1,
        "number": 1,
        "title": "x",
        "state": "open",
        "html_url": "https://github.com/foo/bar/issues/1",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    i = Issue.model_validate(payload)
    assert i.repo_full_name is None


@pytest.mark.unit
def test_search_result_generic():
    payload = {
        "total_count": 2,
        "incomplete_results": False,
        "items": [
            {
                "id": 1, "number": 1, "title": "a", "state": "open",
                "html_url": "https://x/y/issues/1",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "repository_url": "https://api.github.com/repos/x/y",
            },
            {
                "id": 2, "number": 2, "title": "b", "state": "open",
                "html_url": "https://x/y/issues/2",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "repository_url": "https://api.github.com/repos/x/y",
            },
        ],
    }
    result = SearchResult[Issue].model_validate(payload)
    assert result.total_count == 2
    assert len(result.items) == 2
    assert all(isinstance(i, Issue) for i in result.items)
