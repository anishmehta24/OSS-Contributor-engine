"""FastAPI dependencies for resolving the current user from the session cookie."""
from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session
from app.auth.crypto import TokenCryptoError, decrypt_token
from app.auth.sessions import SESSION_COOKIE_NAME, SessionError, read_session
from app.db.models import OAuthToken, User

# Module-level singletons keep ruff's B008 happy.
_DbSession = Depends(get_db_session)
_SessionCookie = Cookie(default=None, alias=SESSION_COOKIE_NAME)


def _load_user(session: Session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session references a deleted user")
    return user


def current_user(
    session: Session = _DbSession,
    session_cookie: str | None = _SessionCookie,
) -> User:
    """Required-auth dependency. Raises 401 if no valid session cookie."""
    try:
        payload = read_session(session_cookie)
    except SessionError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Not authenticated: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e
    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Session payload malformed")
    return _load_user(session, user_id)


def optional_current_user(
    session: Session = _DbSession,
    session_cookie: str | None = _SessionCookie,
) -> User | None:
    """Optional-auth: returns None if no session, never raises."""
    try:
        payload = read_session(session_cookie)
    except SessionError:
        return None
    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        return None
    return session.get(User, user_id)


# Module-level dep for routes that need the current user
CurrentUserDep = Depends(current_user)
OptionalUserDep = Depends(optional_current_user)


def current_user_github_token(
    session: Session = _DbSession,
    user: User = CurrentUserDep,
) -> str:
    """Decrypt and return the current user's GitHub OAuth access token.

    Raises 401 if the user has no token stored (shouldn't normally happen
    if they have a session, but defensive).
    """
    token_row = session.execute(
        select(OAuthToken).where(OAuthToken.user_id == user.id)
    ).scalar_one_or_none()
    if token_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No OAuth token on file — please re-authenticate via GitHub",
        )
    try:
        return decrypt_token(token_row.encrypted_access_token)
    except TokenCryptoError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token decrypt failed: {e}",
        ) from e
