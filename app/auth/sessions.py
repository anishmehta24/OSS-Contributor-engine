"""Signed, time-limited session cookies via itsdangerous.

The cookie payload is just `{"user_id": <int>}` — we look up everything
else from the DB. Cookie is signed (HMAC) with SESSION_SECRET so clients
can't forge sessions. We also expire signatures after SESSION_MAX_AGE_S.

NOT JWTs: smaller payload, no algorithm-confusion class of bugs, simpler
revocation story (we don't bother — just rotate SESSION_SECRET).
"""
from __future__ import annotations

from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.core.config import settings

SESSION_COOKIE_NAME = "oss_engine_session"
OAUTH_STATE_COOKIE_NAME = "oss_engine_oauth_state"
SESSION_SALT = "session.v1"
OAUTH_STATE_SALT = "oauth-state.v1"


class SessionError(Exception):
    """Raised when a session cookie is missing/invalid/expired."""


def _serializer(salt: str) -> URLSafeTimedSerializer:
    if not settings.session_secret:
        raise SessionError("SESSION_SECRET is not configured")
    return URLSafeTimedSerializer(settings.session_secret, salt=salt)


# ---------------------------------------------------------------------------
# Main session (after successful OAuth)
# ---------------------------------------------------------------------------

def sign_session(*, user_id: int) -> str:
    """Produce the signed string to set as the session cookie value."""
    return _serializer(SESSION_SALT).dumps({"user_id": user_id})


def read_session(cookie_value: str | None) -> dict[str, Any]:
    """Validate + decode a session cookie. Raises SessionError on failure."""
    if not cookie_value:
        raise SessionError("No session cookie")
    try:
        return _serializer(SESSION_SALT).loads(
            cookie_value, max_age=settings.session_max_age_s,
        )
    except SignatureExpired as e:
        raise SessionError("Session expired") from e
    except BadSignature as e:
        raise SessionError("Invalid session signature") from e


# ---------------------------------------------------------------------------
# Short-lived OAuth state cookie (CSRF protection)
# ---------------------------------------------------------------------------

def sign_oauth_state(state: str) -> str:
    """Sign a random state token so we can verify it came from us."""
    return _serializer(OAUTH_STATE_SALT).dumps({"state": state})


def read_oauth_state(cookie_value: str | None, *, max_age_s: int = 600) -> str:
    """Read + verify the state cookie. 10-minute default expiry."""
    if not cookie_value:
        raise SessionError("No OAuth state cookie")
    try:
        payload = _serializer(OAUTH_STATE_SALT).loads(cookie_value, max_age=max_age_s)
    except SignatureExpired as e:
        raise SessionError("OAuth state cookie expired") from e
    except BadSignature as e:
        raise SessionError("Invalid OAuth state cookie") from e
    state = payload.get("state")
    if not state:
        raise SessionError("OAuth state cookie missing payload")
    return state
