"""GitHub OAuth flow primitives.

Three operations:
    build_authorize_url(state)  -> str    # where to redirect the browser
    exchange_code(code)         -> dict   # code -> access token
    fetch_github_user(token)    -> dict   # whoami

No state about the user or session lives here — that's in dependencies/routes.
This module just speaks to GitHub.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

# Scopes:
#   read:user    — log me in + read my profile
#   public_repo  — the Autonomous Pilot forks the target repo, pushes a branch,
#                  and opens a PR on the user's behalf. Required for the pilot's
#                  push/PR steps; without it those GitHub calls 403.
DEFAULT_SCOPES = ["read:user", "public_repo"]


class OAuthError(Exception):
    pass


def build_authorize_url(*, state: str, scopes: list[str] | None = None) -> str:
    """Return the URL we redirect the user's browser to."""
    if not settings.github_oauth_client_id:
        raise OAuthError("GITHUB_OAUTH_CLIENT_ID not configured")
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "scope": " ".join(scopes or DEFAULT_SCOPES),
        "state": state,
        "allow_signup": "true",
    }
    return f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict[str, Any]:
    """Trade the auth code GitHub gave us for an access token.

    Returns: {"access_token": str, "scope": str, "token_type": "bearer"}
    Raises OAuthError on any non-success response.
    """
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise OAuthError("GitHub OAuth client_id / client_secret not configured")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": settings.oauth_redirect_uri,
            },
        )
    if response.status_code != 200:
        raise OAuthError(
            f"GitHub token endpoint returned {response.status_code}: {response.text[:200]}"
        )
    payload = response.json()
    if "error" in payload:
        raise OAuthError(
            f"GitHub OAuth error: {payload.get('error')} — "
            f"{payload.get('error_description', '')}"
        )
    if not payload.get("access_token"):
        raise OAuthError("GitHub token response missing access_token")
    return payload


async def fetch_github_user(access_token: str) -> dict[str, Any]:
    """Get the authenticated user's GitHub profile."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    if response.status_code != 200:
        raise OAuthError(
            f"GitHub /user returned {response.status_code}: {response.text[:200]}"
        )
    return response.json()
