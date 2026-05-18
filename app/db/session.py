"""Sync SQLAlchemy engine + session factory.

Why sync (not async): SQLite serializes file writes anyway, so async gains
nothing here, and avoids the greenlet C-extension that's flaky on Windows.
FastAPI routes that hit the DB will use `run_in_threadpool` if needed
(Batch 7) — for SQLite that's still effectively non-blocking.

The connect listener loads sqlite-vec into every connection so vector
queries work transparently.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import sqlite_vec
import structlog
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Build a sync SQLAlchemy engine and wire sqlite-vec + FK pragma.

    `check_same_thread=False` lets FastAPI's thread pool reuse pooled
    connections. SQLAlchemy guarantees serialized access via its pool so
    we never actually share a connection across threads concurrently.

    For in-memory SQLite (tests), we use StaticPool so the same connection
    persists across the whole engine — otherwise each new connection sees
    an empty `:memory:` DB.
    """
    final_url = url or settings.database_url
    is_in_memory = ":memory:" in final_url

    kwargs: dict = {
        "echo": echo,
        "future": True,
        "connect_args": {"check_same_thread": False},
    }
    if is_in_memory:
        kwargs["poolclass"] = StaticPool

    engine = create_engine(final_url, **kwargs)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _connection_record):
        # Load sqlite-vec on every new connection so vector queries always work.
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)
        cur = dbapi_conn.cursor()
        # Enforce foreign-key constraints (off by default in SQLite).
        cur.execute("PRAGMA foreign_keys = ON")
        # WAL mode allows multiple readers + 1 writer concurrently. Default
        # DELETE mode serializes everything and causes "database is locked"
        # when uvicorn and a worker process hit the same .db file.
        if not is_in_memory:
            cur.execute("PRAGMA journal_mode = WAL")
            cur.execute("PRAGMA synchronous = NORMAL")
        # Wait up to 5s for the lock instead of failing immediately.
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.close()

    return engine


# ---------------------------------------------------------------------------
# Process-wide singletons (used by the app; tests build their own engine)
# ---------------------------------------------------------------------------

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def sessionmaker_factory() -> sessionmaker[Session]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = make_engine()
        _sessionmaker = sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a session, committing on success and rolling back on exception."""
    sm = sessionmaker_factory()
    with sm() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ---------------------------------------------------------------------------
# Bootstrap helpers
# ---------------------------------------------------------------------------

# Imported here so create_all() sees them.
from app.db import models as _models  # noqa: E402,F401

# Vector tables (vec0 virtual tables) — created via raw SQL since they live
# outside SQLAlchemy's metadata. Dimension comes from settings so we can
# swap embedder backends (Voyage 1024 vs sentence-transformers 384) by
# changing `EMBEDDER_BACKEND` + running `db reset`. The tables MUST match
# the producer's output dim or inserts fail.
VEC_DIM = settings.embedder_dim

VEC_TABLES_SQL = [
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS user_skills_vec USING vec0(
        rowid INTEGER PRIMARY KEY,
        embedding FLOAT[{VEC_DIM}]
    )
    """,
    f"""
    CREATE VIRTUAL TABLE IF NOT EXISTS issues_vec USING vec0(
        rowid INTEGER PRIMARY KEY,
        embedding FLOAT[{VEC_DIM}]
    )
    """,
]


def init_db(engine: Engine | None = None) -> None:
    """Create all ORM tables + vec0 virtual tables. Idempotent."""
    eng = engine or sessionmaker_factory().kw["bind"]
    with eng.begin() as conn:
        Base.metadata.create_all(conn)
        for stmt in VEC_TABLES_SQL:
            conn.exec_driver_sql(stmt)
    log.info("db_initialized", url=str(eng.url))


def reset_db(engine: Engine | None = None) -> None:
    """Drop everything and recreate. DESTRUCTIVE — dev/test only."""
    eng = engine or sessionmaker_factory().kw["bind"]
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS issues_vec")
        conn.exec_driver_sql("DROP TABLE IF EXISTS user_skills_vec")
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
        for stmt in VEC_TABLES_SQL:
            conn.exec_driver_sql(stmt)
    log.warning("db_reset", url=str(eng.url))
