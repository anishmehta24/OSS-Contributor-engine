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
