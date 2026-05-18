"""GitHub OAuth endpoints.

Flow:
    GET  /auth/login     → set state cookie + redirect to GitHub
    GET  /auth/callback  → exchange code, upsert user + token, set session
    POST /auth/logout    → clear cookies
    GET  /auth/me        → return current user (or 401)
"""
from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import SessionDep
from app.auth.crypto import encrypt_token
from app.auth.dependencies import OptionalUserDep
from app.auth.oauth import (
    OAuthError,
    build_authorize_url,
    exchange_code,
    fetch_github_user,
)
from app.auth.sessions import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SessionError,
    read_oauth_state,
    sign_oauth_state,
    sign_session,
)
from app.core.config import settings
from app.db.models import OAuthToken, User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# In production behind HTTPS, set both cookies with Secure=True.
# For localhost dev (http) we leave Secure off so they actually get set.
_COOKIE_KWARGS = {
    "httponly": True,
    "samesite": "lax",
    "secure": False,  # flip to True when deploying behind HTTPS
}

# Module-level deps to keep ruff's B008 happy.
_OAuthStateCookie = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME)


class MeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    github_login: str
    github_id: int
    name: str | None
    has_oauth_token: bool


@router.get("/login")
async def login() -> RedirectResponse:
    """Kick off the OAuth dance. Sets a short-lived state cookie + redirects."""
    if not settings.has_oauth:
        raise HTTPException(
            status_code=503,
            detail="OAuth not configured (set GITHUB_OAUTH_CLIENT_ID / SECRET / SESSION_SECRET)",
        )
    state = secrets.token_urlsafe(24)
    authorize_url = build_authorize_url(state=state)
    response = RedirectResponse(url=authorize_url, status_code=307)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=sign_oauth_state(state),
        max_age=600,  # 10 min — user must complete OAuth in this window
        **_COOKIE_KWARGS,
    )
    return response


@router.get("/callback")
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    state_cookie: str | None = _OAuthStateCookie,
    session: Session = SessionDep,
) -> RedirectResponse:
    """GitHub redirects here with `code` and `state`. Exchange + create session."""
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"GitHub OAuth refused: {error} ({error_description or 'no detail'})",
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    # CSRF: state in URL must match what we signed into the cookie
    try:
        expected_state = read_oauth_state(state_cookie)
    except SessionError as e:
        raise HTTPException(status_code=400, detail=f"OAuth state invalid: {e}") from e
    if state != expected_state:
        raise HTTPException(status_code=400, detail="OAuth state mismatch (CSRF check)")

    # Exchange code → access token
    try:
        token_payload = await exchange_code(code)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    access_token = token_payload["access_token"]
    scopes = [s for s in (token_payload.get("scope") or "").split(",") if s]

    # Who is this user?
    try:
        gh_user = await fetch_github_user(access_token)
    except OAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    github_id = int(gh_user["id"])
    github_login = gh_user["login"]
    name = gh_user.get("name")

    # Upsert user
    user = session.execute(
        select(User).where(User.github_id == github_id)
    ).scalar_one_or_none()
    if user is None:
        user = User(github_id=github_id, github_login=github_login, name=name)
        session.add(user)
        session.flush()
    else:
        user.github_login = github_login  # they may have renamed
        user.name = name
        session.flush()

    # Upsert token (encrypted)
    token_row = session.execute(
        select(OAuthToken).where(OAuthToken.user_id == user.id)
    ).scalar_one_or_none()
    encrypted = encrypt_token(access_token)
    if token_row is None:
        token_row = OAuthToken(
            user_id=user.id,
            provider="github",
            encrypted_access_token=encrypted,
            scopes=scopes,
            token_type=token_payload.get("token_type", "bearer"),
        )
        session.add(token_row)
    else:
        token_row.encrypted_access_token = encrypted
        token_row.scopes = scopes
        token_row.token_type = token_payload.get("token_type", "bearer")

    session.commit()
    log.info("oauth_login_success", user_id=user.id, github_login=github_login)

    # Cross-origin bridge: Streamlit lives on a different port and can't read
    # cookies set on this domain, so we ALSO pass the signed session value as
    # a one-time URL param. Streamlit reads it and forwards it as a Cookie
    # header on its server-side API calls. The cookie is still set normally,
    # so direct browser usage of the API also works.
    signed_session = sign_session(user_id=user.id)
    redirect_target = settings.oauth_post_login_redirect
    separator = "&" if "?" in redirect_target else "?"
    handoff_url = f"{redirect_target}{separator}session={signed_session}"

    response = RedirectResponse(url=handoff_url, status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=signed_session,
        max_age=settings.session_max_age_s,
        **_COOKIE_KWARGS,
    )
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    return response


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
async def me(
    user: User | None = OptionalUserDep,
    session: Session = SessionDep,
) -> MeResponse:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    has_token = session.execute(
        select(OAuthToken).where(OAuthToken.user_id == user.id)
    ).scalar_one_or_none() is not None
    return MeResponse(
        id=user.id,
        github_login=user.github_login,
        github_id=user.github_id,
        name=user.name,
        has_oauth_token=has_token,
    )
