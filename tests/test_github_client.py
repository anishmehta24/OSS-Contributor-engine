"""GitHub client tests with respx-mocked HTTP responses.

These tests never hit the real network. They cover:
    - happy path with a typed Pydantic return
    - 401 -> AuthError
    - 404 -> NotFoundError
    - 304 ETag cache hit returns cached payload
    - 403 with X-RateLimit-Remaining=0 retries after sleeping
    - 5xx exponential-backoff retry, then surface as GitHubError
"""
from __future__ import annotations

import time

import httpx
import pytest
import respx

from app.tools.github import (
    AuthError,
    GitHubClient,
    GitHubError,
    NotFoundError,
)

API = "https://api.github.com"


@pytest.fixture
async def client():
    gh = GitHubClient(token="test-token")
    yield gh
    await gh.close()


@pytest.mark.unit
@respx.mock
async def test_get_user_happy_path(client: GitHubClient):
    respx.get(f"{API}/users/octocat").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 1, "login": "octocat",
                "html_url": "https://github.com/octocat",
                "name": "The Octocat", "public_repos": 8,
            },
            headers={"X-RateLimit-Remaining": "4999", "X-RateLimit-Resource": "core"},
        )
    )
    user = await client.get_user("octocat")
    assert user.login == "octocat"
    assert user.public_repos == 8
    assert client.core_remaining == 4999


@pytest.mark.unit
@respx.mock
async def test_401_raises_auth_error(client: GitHubClient):
    respx.get(f"{API}/users/x").mock(return_value=httpx.Response(401, json={"message": "Bad creds"}))
    with pytest.raises(AuthError):
        await client.get_user("x")


@pytest.mark.unit
@respx.mock
async def test_404_raises_not_found(client: GitHubClient):
    respx.get(f"{API}/users/does-not-exist").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )
    with pytest.raises(NotFoundError):
        await client.get_user("does-not-exist")


@pytest.mark.unit
@respx.mock
async def test_etag_cache_returns_stored_payload_on_304(client: GitHubClient):
    payload = {
        "id": 1, "login": "octocat",
        "html_url": "https://github.com/octocat", "public_repos": 8,
    }
    route = respx.get(f"{API}/users/octocat").mock(
        side_effect=[
            httpx.Response(200, json=payload, headers={"ETag": '"abc"'}),
            httpx.Response(304),  # second request: not modified
        ]
    )
    first = await client.get_user("octocat")
    second = await client.get_user("octocat")
    assert first.login == second.login == "octocat"
    assert route.call_count == 2
    # second request should have sent If-None-Match
    sent_headers = route.calls[1].request.headers
    assert sent_headers.get("if-none-match") == '"abc"'


@pytest.mark.unit
@respx.mock
async def test_403_with_remaining_zero_sleeps_then_retries(
    client: GitHubClient, monkeypatch
):
    """We don't want the test to actually sleep — patch asyncio.sleep to a no-op."""
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    reset_at = int(time.time()) + 2
    respx.get(f"{API}/users/octocat").mock(
        side_effect=[
            httpx.Response(
                403,
                headers={
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
                json={"message": "rate limit"},
            ),
            httpx.Response(
                200,
                json={
                    "id": 1, "login": "octocat",
                    "html_url": "https://github.com/octocat", "public_repos": 1,
                },
            ),
        ]
    )
    user = await client.get_user("octocat")
    assert user.login == "octocat"
    assert sleeps, "expected at least one sleep before retry"


@pytest.mark.unit
@respx.mock
async def test_5xx_retries_and_eventually_raises(client: GitHubClient, monkeypatch):
    async def fake_sleep(_):
        return None

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    route = respx.get(f"{API}/users/octocat").mock(
        return_value=httpx.Response(503, text="upstream down")
    )
    with pytest.raises(GitHubError):
        await client.get_user("octocat")
    # MAX_RETRIES=3 => 1 initial + 3 retries = 4 attempts
    assert route.call_count == 4


@pytest.mark.unit
async def test_init_without_token_raises():
    with pytest.raises(ValueError):
        GitHubClient(token="")


# ---------------------------------------------------------------------------
# fork_repo + wait_for_repo_ready (Batch 34)
# ---------------------------------------------------------------------------

_REPO_PAYLOAD = {
    "id": 1296269,
    "name": "Hello-World",
    "full_name": "octocat/Hello-World",
    "html_url": "https://github.com/octocat/Hello-World",
    "description": "My first repository on GitHub!",
    "language": "Python",
    "stargazers_count": 80,
    "forks_count": 9,
    "open_issues_count": 0,
    "archived": False,
    "fork": False,
    "default_branch": "main",
    "topics": [],
}


@pytest.mark.unit
@respx.mock
async def test_fork_repo_returns_typed_repo(client: GitHubClient):
    route = respx.post(f"{API}/repos/upstream/widget/forks").mock(
        return_value=httpx.Response(202, json=_REPO_PAYLOAD),
    )
    repo = await client.fork_repo("upstream/widget")
    assert route.called
    assert repo.full_name == "octocat/Hello-World"
    # POST went out as POST, not GET.
    assert route.calls[0].request.method == "POST"


@pytest.mark.unit
@respx.mock
async def test_fork_repo_surfaces_auth_error(client: GitHubClient):
    respx.post(f"{API}/repos/upstream/widget/forks").mock(
        return_value=httpx.Response(401, json={"message": "Bad creds"}),
    )
    with pytest.raises(AuthError):
        await client.fork_repo("upstream/widget")


@pytest.mark.unit
@respx.mock
async def test_wait_for_repo_ready_polls_until_200(
    client: GitHubClient, monkeypatch,
):
    """First two calls 404 (fork still provisioning), third succeeds."""
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    route = respx.get(f"{API}/repos/me/widget").mock(
        side_effect=[
            httpx.Response(404, json={"message": "Not Found"}),
            httpx.Response(404, json={"message": "Not Found"}),
            httpx.Response(200, json=_REPO_PAYLOAD),
        ],
    )
    repo = await client.wait_for_repo_ready(
        "me/widget", max_wait_s=10, poll_interval_s=0.1,
    )
    assert repo.full_name == "octocat/Hello-World"
    assert route.call_count == 3
    assert len(sleeps) == 2  # slept twice between the three calls


@pytest.mark.unit
@respx.mock
async def test_wait_for_repo_ready_gives_up_after_max_wait(
    client: GitHubClient, monkeypatch,
):
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    monkeypatch.setattr("asyncio.sleep", fake_sleep)

    respx.get(f"{API}/repos/me/ghost").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"}),
    )
    with pytest.raises(NotFoundError):
        await client.wait_for_repo_ready(
            "me/ghost", max_wait_s=0.5, poll_interval_s=0.2,
        )


# ---------------------------------------------------------------------------
# create_pull_request (Batch 35)
# ---------------------------------------------------------------------------

_PR_PAYLOAD = {
    "id": 555,
    "number": 42,
    "state": "open",
    "draft": True,
    "title": "[oss-engine] Attempted fix for #1: a bug",
    "body": "AI generated",
    "html_url": "https://github.com/upstream/widget/pull/42",
    "created_at": "2026-05-23T12:00:00Z",
    "merged_at": None,
}


@pytest.mark.unit
@respx.mock
async def test_create_pull_request_happy_path(client: GitHubClient):
    route = respx.post(f"{API}/repos/upstream/widget/pulls").mock(
        return_value=httpx.Response(201, json=_PR_PAYLOAD),
    )
    pr = await client.create_pull_request(
        "upstream/widget",
        title="[oss-engine] Attempted fix for #1: a bug",
        body="AI generated",
        head="dev-login:oss-engine/pilot-abc-issue-1",
        base="main",
    )
    assert pr.number == 42
    assert pr.draft is True
    assert pr.html_url.endswith("/pull/42")

    # Body shape was correct.
    body = route.calls[0].request.read().decode("utf-8")
    import json as _json
    posted = _json.loads(body)
    assert posted["draft"] is True
    assert posted["head"] == "dev-login:oss-engine/pilot-abc-issue-1"
    assert posted["base"] == "main"


@pytest.mark.unit
@respx.mock
async def test_create_pull_request_defaults_to_draft(client: GitHubClient):
    """draft=True must default ON — we don't want non-draft PRs by accident."""
    route = respx.post(f"{API}/repos/upstream/widget/pulls").mock(
        return_value=httpx.Response(201, json=_PR_PAYLOAD),
    )
    await client.create_pull_request(
        "upstream/widget", title="t", body="b", head="x:y", base="main",
    )
    import json as _json
    posted = _json.loads(route.calls[0].request.read().decode("utf-8"))
    assert posted["draft"] is True


@pytest.mark.unit
@respx.mock
async def test_create_pull_request_surfaces_auth_error(client: GitHubClient):
    respx.post(f"{API}/repos/upstream/widget/pulls").mock(
        return_value=httpx.Response(401, json={"message": "Bad creds"}),
    )
    with pytest.raises(AuthError):
        await client.create_pull_request(
            "upstream/widget", title="t", body="b", head="x:y", base="main",
        )


@pytest.mark.unit
@respx.mock
async def test_create_pull_request_surfaces_already_exists_as_github_error(
    client: GitHubClient,
):
    """GitHub returns 422 with a specific message when a PR already exists
    for this head -> base pair."""
    respx.post(f"{API}/repos/upstream/widget/pulls").mock(
        return_value=httpx.Response(422, json={
            "message": "Validation Failed",
            "errors": [{
                "resource": "PullRequest",
                "code": "custom",
                "message": "A pull request already exists for dev-login:oss-engine/pilot-abc-issue-1.",
            }],
        }),
    )
    with pytest.raises(GitHubError) as excinfo:
        await client.create_pull_request(
            "upstream/widget", title="t", body="b", head="x:y", base="main",
        )
    assert "already exists" in str(excinfo.value)
