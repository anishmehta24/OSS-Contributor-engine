"""End-to-end HTTP tests for the OAuth flow.

GitHub's endpoints are mocked with respx — we never hit the real GitHub.
"""
from __future__ import annotations

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.auth import crypto as crypto_mod
from app.auth import sessions as sess_mod
from app.auth.sessions import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    sign_oauth_state,
    sign_session,
)
from app.db.models import OAuthToken, User

OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
OAUTH_USER_URL = "https://api.github.com/user"


@pytest.fixture(autouse=True)
def _wire_auth(monkeypatch):
    """Provide working OAuth settings + secret for the whole module."""
    secret = Fernet.generate_key().decode()
    for mod in (sess_mod, crypto_mod):
        monkeypatch.setattr(mod.settings, "session_secret", secret)
    crypto_mod._get_fernet.cache_clear()
    monkeypatch.setattr(
        "app.api.routes.auth.settings.github_oauth_client_id", "test_client",
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.routes.auth.settings.github_oauth_client_secret", "test_secret",
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.routes.auth.settings.session_secret", secret, raising=False,
    )
    monkeypatch.setattr(
        "app.auth.oauth.settings.github_oauth_client_id", "test_client",
        raising=False,
    )
    monkeypatch.setattr(
        "app.auth.oauth.settings.github_oauth_client_secret", "test_secret",
        raising=False,
    )
    yield


# ---------------------------------------------------------------------------
# /auth/login
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_login_503_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.auth.settings.github_oauth_client_id", "",
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.routes.auth.settings.github_oauth_client_secret", "",
        raising=False,
    )
    monkeypatch.setattr(
        "app.api.routes.auth.settings.session_secret", "",
        raising=False,
    )
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 503


@pytest.mark.unit
def test_login_redirects_to_github_with_state_cookie(client):
    response = client.get("/auth/login", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://github.com/login/oauth/authorize")
    assert "client_id=test_client" in location
    assert "state=" in location
    # State cookie must be set
    assert OAUTH_STATE_COOKIE_NAME in response.cookies


# ---------------------------------------------------------------------------
# /auth/callback
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_callback_400_when_missing_code(client):
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.status_code == 400


@pytest.mark.unit
def test_callback_400_when_no_state_cookie(client):
    response = client.get(
        "/auth/callback?code=ABC&state=xyz", follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.unit
def test_callback_400_when_state_mismatch(client):
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, sign_oauth_state("expected"))
    response = client.get(
        "/auth/callback?code=ABC&state=different",
        follow_redirects=False,
    )
    assert response.status_code == 400


@pytest.mark.unit
@respx.mock
def test_callback_happy_path_creates_user_and_session(client, session):
    state = "matching-state"
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, sign_oauth_state(state))

    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "gho_test_token",
                   "scope": "read:user", "token_type": "bearer"},
    ))
    respx.get(OAUTH_USER_URL).mock(return_value=httpx.Response(
        200, json={"id": 12345, "login": "newcomer",
                   "name": "New Comer", "html_url": "https://github.com/newcomer",
                   "public_repos": 3},
    ))

    response = client.get(
        f"/auth/callback?code=AUTH_CODE&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert SESSION_COOKIE_NAME in response.cookies
    # Cross-origin handoff: callback URL includes ?session=<token>
    assert "session=" in response.headers["location"]

    # User + token persisted
    user = session.execute(
        select(User).where(User.github_id == 12345)
    ).scalar_one()
    assert user.github_login == "newcomer"
    token = session.execute(
        select(OAuthToken).where(OAuthToken.user_id == user.id)
    ).scalar_one()
    assert token.encrypted_access_token != "gho_test_token"  # encrypted
    assert "read:user" in token.scopes


@pytest.mark.unit
@respx.mock
def test_callback_re_login_updates_token_not_creates_new(client, session):
    """Re-logging-in upserts; we never accumulate stale tokens."""
    state = "matching-state"
    client.cookies.set(OAUTH_STATE_COOKIE_NAME, sign_oauth_state(state))

    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "first_token",
                   "scope": "read:user", "token_type": "bearer"},
    ))
    respx.get(OAUTH_USER_URL).mock(return_value=httpx.Response(
        200, json={"id": 999, "login": "repeat", "name": None,
                   "html_url": "x", "public_repos": 0},
    ))

    client.get(f"/auth/callback?code=A&state={state}", follow_redirects=False)

    client.cookies.set(OAUTH_STATE_COOKIE_NAME, sign_oauth_state(state))
    respx.post(OAUTH_TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "second_token",
                   "scope": "read:user", "token_type": "bearer"},
    ))
    client.get(f"/auth/callback?code=A&state={state}", follow_redirects=False)

    # Still one user, one token row
    users = session.execute(select(User).where(User.github_id == 999)).scalars().all()
    tokens = session.execute(
        select(OAuthToken).where(OAuthToken.user_id == users[0].id)
    ).scalars().all()
    assert len(users) == 1
    assert len(tokens) == 1


# ---------------------------------------------------------------------------
# /auth/logout
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_logout_clears_session_cookie(client, session):
    user = User(github_login="dev", github_id=1)
    session.add(user)
    session.commit()
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(user_id=user.id))

    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_me_returns_401_when_not_logged_in(client):
    response = client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.unit
def test_me_returns_user_when_logged_in(client, session):
    user = User(github_login="alice", github_id=42, name="Alice")
    session.add(user)
    session.flush()
    session.add(OAuthToken(
        user_id=user.id,
        encrypted_access_token=crypto_mod.encrypt_token("gho_x"),
        scopes=["read:user"],
    ))
    session.commit()

    client.cookies.set(SESSION_COOKIE_NAME, sign_session(user_id=user.id))
    response = client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["github_login"] == "alice"
    assert body["github_id"] == 42
    assert body["has_oauth_token"] is True


@pytest.mark.unit
def test_me_401_when_user_deleted_under_session(client, session):
    """Edge case: valid session cookie but user was deleted from DB."""
    client.cookies.set(SESSION_COOKIE_NAME, sign_session(user_id=99999))
    response = client.get("/auth/me")
    # optional_current_user returns None, then me() raises 401
    assert response.status_code == 401
