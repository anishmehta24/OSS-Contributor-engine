"""Async GitHub REST client with rate-limit and ETag handling.

Design:
    - One async session, reused across calls (connection pooling)
    - All requests funnel through `_request` which handles:
        * search-API token bucket (30/min)
        * core API rate-limit auto-sleep when remaining is low
        * 401 -> AuthError, 404 -> NotFoundError
        * 403 with X-RateLimit-Remaining=0 -> sleep until reset, retry
        * 403 with Retry-After (secondary limit) -> sleep, retry
        * 5xx -> exponential backoff up to MAX_RETRIES
        * ETag-based caching for GET responses
    - Returns Pydantic models, not raw dicts.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.tools.github.exceptions import (
    AuthError,
    GitHubError,
    NotFoundError,
    RateLimitError,
)
from app.tools.github.models import (
    Commit,
    Issue,
    Repo,
    SearchResult,
    User,
)
from app.tools.github.rate_limiter import TokenBucket

log = structlog.get_logger(__name__)

GITHUB_API = "https://api.github.com"
MAX_RETRIES = 3
LOW_RATE_THRESHOLD = 50  # auto-sleep when this few core requests remain


class _ETagEntry:
    __slots__ = ("etag", "data", "stored_at")

    def __init__(self, etag: str, data: Any) -> None:
        self.etag = etag
        self.data = data
        self.stored_at = time.time()


class GitHubClient:
    """Async GitHub client. Use as an async context manager.

    Example:
        async with GitHubClient(token=...) as gh:
            user = await gh.get_user("torvalds")
    """

    def __init__(
        self,
        token: str,
        *,
        base_url: str = GITHUB_API,
        user_agent: str = "oss-engine/0.1 (httpx)",
        timeout: float = 30.0,
    ) -> None:
        if not token:
            raise ValueError("GitHub token is required")
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": user_agent,
            },
            timeout=timeout,
        )
        self._search_bucket = TokenBucket(rate=30, period=60)
        # in-memory ETag cache; persistent caching is a later batch
        self._etags: dict[str, _ETagEntry] = {}
        # last-known core rate limit (updated from response headers)
        self.core_remaining: int | None = None
        self.core_reset_at: int | None = None

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    # -----------------------------
    # Internal request pipeline
    # -----------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        is_search: bool = False,
        use_etag: bool = True,
    ) -> Any:
        if is_search:
            await self._search_bucket.acquire()
        await self._respect_core_rate_limit()

        cache_key = self._cache_key(method, path, params)
        headers: dict[str, str] = {}
        if use_etag and method == "GET" and cache_key in self._etags:
            headers["If-None-Match"] = self._etags[cache_key].etag

        for attempt in range(MAX_RETRIES + 1):
            response = await self._client.request(
                method, path, params=params, json=json, headers=headers
            )
            self._update_rate_limit_from_headers(response.headers)

            # 304 Not Modified -> serve cached payload
            if response.status_code == 304 and cache_key in self._etags:
                log.debug("github_etag_hit", path=path)
                return self._etags[cache_key].data

            if response.status_code == 200 or response.status_code == 201:
                data = response.json() if response.content else None
                if (
                    use_etag
                    and method == "GET"
                    and "etag" in response.headers
                    and data is not None
                ):
                    self._etags[cache_key] = _ETagEntry(response.headers["etag"], data)
                return data

            if response.status_code == 401:
                raise AuthError("Invalid or expired GitHub token", status_code=401)

            if response.status_code == 404:
                raise NotFoundError(f"Not found: {path}", status_code=404)

            if response.status_code in (403, 429):
                wait = self._compute_rate_limit_wait(response)
                if wait is None or attempt == MAX_RETRIES:
                    raise RateLimitError(
                        f"Rate limit hit (status {response.status_code})",
                        retry_after_seconds=wait,
                    )
                log.warning(
                    "github_rate_limit_sleep",
                    path=path,
                    sleep_s=wait,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)
                continue

            if 500 <= response.status_code < 600:
                if attempt == MAX_RETRIES:
                    raise GitHubError(
                        f"Server error {response.status_code} after {MAX_RETRIES} retries",
                        status_code=response.status_code,
                    )
                backoff = 2**attempt
                log.warning("github_5xx_retry", path=path, sleep_s=backoff, attempt=attempt + 1)
                await asyncio.sleep(backoff)
                continue

            # any other 4xx: surface immediately
            raise GitHubError(
                f"GitHub returned {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

        raise GitHubError("Exhausted retries without resolution")

    @staticmethod
    def _cache_key(method: str, path: str, params: dict[str, Any] | None) -> str:
        if not params:
            return f"{method} {path}"
        ordered = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{method} {path}?{ordered}"

    def _update_rate_limit_from_headers(self, headers: httpx.Headers) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        resource = headers.get("X-RateLimit-Resource")
        if remaining is not None and resource == "core":
            with contextlib.suppress(ValueError):
                self.core_remaining = int(remaining)
        if reset is not None and resource == "core":
            with contextlib.suppress(ValueError):
                self.core_reset_at = int(reset)

    async def _respect_core_rate_limit(self) -> None:
        """If we're nearly out of core quota, sleep until reset."""
        if self.core_remaining is None or self.core_reset_at is None:
            return
        if self.core_remaining > LOW_RATE_THRESHOLD:
            return
        wait = max(0, self.core_reset_at - int(time.time())) + 1
        if wait > 0:
            log.warning("github_core_quota_low", remaining=self.core_remaining, sleep_s=wait)
            await asyncio.sleep(wait)

    @staticmethod
    def _compute_rate_limit_wait(response: httpx.Response) -> float | None:
        """Pick the right sleep duration from the response headers."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                return None
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining == "0" and reset:
            try:
                return max(0.0, int(reset) - time.time()) + 1.0
            except ValueError:
                return None
        return None

    # -----------------------------
    # Public API
    # -----------------------------

    async def get_user(self, login: str) -> User:
        data = await self._request("GET", f"/users/{login}")
        return User.model_validate(data)

    async def get_authenticated_user(self) -> User:
        data = await self._request("GET", "/user")
        return User.model_validate(data)

    async def get_user_repos(
        self,
        login: str,
        *,
        max_repos: int = 100,
        sort: str = "pushed",
    ) -> list[Repo]:
        repos: list[Repo] = []
        page = 1
        per_page = min(100, max_repos)
        while len(repos) < max_repos:
            data = await self._request(
                "GET",
                f"/users/{login}/repos",
                params={"per_page": per_page, "page": page, "sort": sort, "type": "owner"},
            )
            if not data:
                break
            repos.extend(Repo.model_validate(r) for r in data)
            if len(data) < per_page:
                break
            page += 1
        return repos[:max_repos]

    async def get_repo(self, full_name: str) -> Repo:
        data = await self._request("GET", f"/repos/{full_name}")
        return Repo.model_validate(data)

    async def get_repo_languages(self, full_name: str) -> dict[str, int]:
        return await self._request("GET", f"/repos/{full_name}/languages")

    async def get_repo_file(self, full_name: str, path: str, ref: str | None = None) -> str | None:
        """Return the decoded text of a file at `path`, or None if missing."""
        params = {"ref": ref} if ref else None
        try:
            data = await self._request(
                "GET", f"/repos/{full_name}/contents/{path}", params=params
            )
        except NotFoundError:
            return None
        if not isinstance(data, dict) or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        except Exception:
            return None

    async def get_issue(self, full_name: str, number: int) -> Issue:
        data = await self._request("GET", f"/repos/{full_name}/issues/{number}")
        return Issue.model_validate(data)

    async def search_issues(
        self,
        query: str,
        *,
        sort: str = "updated",
        order: str = "desc",
        per_page: int = 30,
        page: int = 1,
    ) -> SearchResult[Issue]:
        data = await self._request(
            "GET",
            "/search/issues",
            params={
                "q": query,
                "sort": sort,
                "order": order,
                "per_page": per_page,
                "page": page,
            },
            is_search=True,
        )
        return SearchResult[Issue].model_validate(
            {
                "total_count": data.get("total_count", 0),
                "incomplete_results": data.get("incomplete_results", False),
                "items": data.get("items", []),
            }
        )

    async def get_recent_commits(self, full_name: str, limit: int = 20) -> list[Commit]:
        try:
            data = await self._request(
                "GET", f"/repos/{full_name}/commits", params={"per_page": min(100, limit)}
            )
        except GitHubError as e:
            # 409 = "Git Repository is empty" — fresh repo with no commits yet.
            # Treat as "no commits" rather than a real error.
            if e.status_code == 409:
                return []
            raise
        commits: list[Commit] = []
        for entry in data[:limit]:
            commit_section = entry.get("commit", {})
            author_section = commit_section.get("author", {}) or {}
            user_section = entry.get("author") or {}
            author_date_raw = author_section.get("date")
            commits.append(
                Commit(
                    sha=entry["sha"],
                    message=commit_section.get("message", ""),
                    author_login=user_section.get("login"),
                    author_date=(
                        datetime.fromisoformat(author_date_raw.replace("Z", "+00:00")).astimezone(
                            UTC
                        )
                        if author_date_raw
                        else None
                    ),
                    html_url=entry.get("html_url", ""),
                )
            )
        return commits

    async def rate_limit(self) -> dict[str, Any]:
        return await self._request("GET", "/rate_limit", use_etag=False)

    async def get_repo_tree(
        self,
        full_name: str,
        *,
        ref: str | None = None,
        max_entries: int = 2000,
    ) -> list[dict[str, Any]]:
        """Return the (recursive) file tree for the default branch.

        Each entry: {"path": "...", "type": "blob"|"tree", "sha": "...", "size": N}
        GitHub truncates results past ~7MB; we just return whatever it gave us.
        """
        sha = ref or "HEAD"
        data = await self._request(
            "GET", f"/repos/{full_name}/git/trees/{sha}", params={"recursive": "1"}
        )
        tree = data.get("tree", []) if isinstance(data, dict) else []
        return tree[:max_entries]

    async def get_issue_comments(
        self,
        full_name: str,
        number: int,
        *,
        max_comments: int = 30,
    ) -> list[dict[str, Any]]:
        """Return raw comment dicts for an issue (we only need body + login)."""
        data = await self._request(
            "GET",
            f"/repos/{full_name}/issues/{number}/comments",
            params={"per_page": min(100, max_comments)},
        )
        if not isinstance(data, list):
            return []
        return data[:max_comments]
