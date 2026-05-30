"""Shared pytest fixtures.

Every DB test gets a fresh in-memory SQLite engine with sqlite-vec preloaded
and the schema created. No state leaks between tests.

API tests also get a `client` fixture: a TestClient over a FastAPI app
wired to the test engine, with no external services configured by default.
Individual tests inject fakes via `api_app.state.github = ...` etc.
"""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import get_db_session
from app.api.errors import register_exception_handlers
from app.api.routes import (
    admin,
    auth,
    health,
    investigations,
    matches,
    pilot,
    users,
)
from app.db.base import Base
from app.db.session import VEC_TABLES_SQL, make_engine

# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine(tmp_path):
    """File-backed SQLite per test.

    File-based (not :memory:) so background tasks spawned via asyncio in
    the same process can each get their own connection from the pool —
    the StaticPool we use for :memory: serializes everything onto one
    connection and dead-locks the moment two sessions overlap.
    """
    db_file = tmp_path / "test.db"
    eng = make_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        Base.metadata.create_all(conn)
        for stmt in VEC_TABLES_SQL:
            conn.exec_driver_sql(stmt)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    sm = sessionmaker(engine, expire_on_commit=False)
    with sm() as s:
        yield s


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def api_app(engine) -> FastAPI:
    """FastAPI app wired to the in-memory test engine, no external services."""
    app = FastAPI(title="test")
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(matches.router)
    app.include_router(investigations.router)
    app.include_router(pilot.router)
    app.include_router(admin.router)

    app.state.github = None
    app.state.voyage = None
    app.state.llm_router = None

    sm = sessionmaker(engine, expire_on_commit=False)

    def _override_session() -> Iterator[Session]:
        with sm() as s:
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise

    app.dependency_overrides[get_db_session] = _override_session
    # Background tasks (Batch 9) pull this from app.state instead of the
    # global sessionmaker_factory so they hit the test engine.
    app.state.session_factory = sm
    return app


@pytest.fixture
def client(api_app) -> Iterator[TestClient]:
    with TestClient(api_app) as c:
        yield c


# ---------------------------------------------------------------------------
# Auth helpers (Batch 14)
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_secret(monkeypatch):
    """Set a fresh SESSION_SECRET for every test that needs auth."""
    from cryptography.fernet import Fernet

    from app.auth import crypto as crypto_mod
    from app.auth import sessions as sess_mod

    secret = Fernet.generate_key().decode()
    for mod in (sess_mod, crypto_mod):
        monkeypatch.setattr(mod.settings, "session_secret", secret)
    crypto_mod._get_fernet.cache_clear()
    yield secret
    crypto_mod._get_fernet.cache_clear()


@pytest.fixture
def make_logged_in_user(client, session, auth_secret):
    """Factory that seeds a User + OAuthToken and sets the session cookie.

    Usage:
        def test_x(make_logged_in_user, client):
            user = make_logged_in_user(github_login="dev")
            r = client.get("/users/me")
    """
    from app.auth.crypto import encrypt_token
    from app.auth.sessions import SESSION_COOKIE_NAME, sign_session
    from app.db.models import OAuthToken, User

    def _make(*, github_login: str = "dev", github_id: int = 1,
              name: str | None = None, access_token: str = "gho_test") -> User:
        user = User(github_login=github_login, github_id=github_id, name=name)
        session.add(user)
        session.flush()
        session.add(OAuthToken(
            user_id=user.id,
            encrypted_access_token=encrypt_token(access_token),
            scopes=["read:user"],
        ))
        session.commit()
        client.cookies.set(SESSION_COOKIE_NAME, sign_session(user_id=user.id))
        return user

    return _make
