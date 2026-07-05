"""Sync SQLAlchemy engine + session factory.

Why sync (not async): SQLite serializes file writes anyway, so async gains
nothing here, and avoids the greenlet C-extension that's flaky on Windows.
FastAPI routes that hit the DB will use `run_in_threadpool` if needed
(Batch 7) — for SQLite that's still effectively non-blocking.

Dual-dialect support:
    - sqlite:///...  — local dev + test default. Loads sqlite-vec into every
      connection and creates `user_skills_vec` / `issues_vec` virtual tables.
    - postgresql://  — deploy target (Render/Neon). Skips sqlite-vec, ensures
      the pgvector extension exists, and creates parallel `*_vec` tables with
      a real `vector(N)` column managed by pgvector.

The vector helpers (app/db/vector.py) dispatch on `session.bind.dialect.name`,
so call sites stay agnostic.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import structlog
from sqlalchemy import Engine, create_engine, event, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------

def _is_sqlite(url: str) -> bool:
    return make_url(url).get_backend_name() == "sqlite"


def make_engine(url: str | None = None, *, echo: bool = False) -> Engine:
    """Build a sync SQLAlchemy engine for the given DATABASE_URL.

    SQLite path: `check_same_thread=False` lets FastAPI's thread pool reuse
    pooled connections, sqlite-vec is loaded into every connection, and we
    set WAL + a few PRAGMAs. In-memory SQLite (tests) uses StaticPool so
    the same connection persists.

    Postgres path: standard psycopg connection pool, no extension loading
    (pgvector is a server-side extension, enabled in init_db via CREATE
    EXTENSION) — and PRAGMAs are SQLite-only.
    """
    final_url = url or settings.database_url

    if _is_sqlite(final_url):
        return _make_sqlite_engine(final_url, echo=echo)
    return _make_postgres_engine(final_url, echo=echo)


def _make_sqlite_engine(url: str, *, echo: bool) -> Engine:
    is_in_memory = ":memory:" in url
    kwargs: dict = {
        "echo": echo,
        "future": True,
        "connect_args": {"check_same_thread": False},
    }
    if is_in_memory:
        kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **kwargs)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _connection_record):
        # Load sqlite-vec on every new connection so vector queries always work.
        import sqlite_vec
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


def _make_postgres_engine(url: str, *, echo: bool) -> Engine:
    # Render-style URLs sometimes use the bare `postgres://` scheme that
    # SQLAlchemy 2 doesn't recognize — normalize to the canonical name.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(
        url,
        echo=echo,
        future=True,
        # Free-tier Postgres (Neon) idles connections aggressively — recycle
        # before the upstream drops them to avoid "server closed the
        # connection unexpectedly" on the next query.
        pool_pre_ping=True,
        pool_recycle=300,
    )


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

# Vector tables live OUTSIDE the ORM metadata because each dialect needs a
# different storage backend (sqlite-vec virtual table vs pgvector column).
# Dimension comes from settings so swapping embedder backends (Voyage 1024
# vs local 384) is a config change + `db reset`, not a code edit.
VEC_DIM = settings.embedder_dim

# SQLite: sqlite-vec's vec0 virtual table — blob storage + MATCH operator.
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

# Postgres: a real table with a pgvector `vector(N)` column. `id` mirrors the
# parent table's PK (UserSkill.id, Issue.id) so it can be FK-joined if needed
# later. BIGINT covers both (Issue.id is GitHub's, can be large).
VEC_TABLES_SQL_PG = [
    f"""
    CREATE TABLE IF NOT EXISTS user_skills_vec (
        id BIGINT PRIMARY KEY,
        embedding vector({VEC_DIM})
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS issues_vec (
        id BIGINT PRIMARY KEY,
        embedding vector({VEC_DIM})
    )
    """,
]


def init_db(engine: Engine | None = None) -> None:
    """Create all ORM tables + vector tables. Idempotent across both dialects.

    Also runs a best-effort additive column migration: `create_all` makes
    NEW tables but never alters EXISTING ones, so a column added to a model
    after its table already exists would otherwise 500 every query with
    'no such column'. `_add_missing_columns` closes that gap for the
    common additive case.
    """
    eng = engine or sessionmaker_factory().kw["bind"]
    is_pg = eng.dialect.name == "postgresql"

    with eng.begin() as conn:
        if is_pg:
            # pgvector is a server-side extension. Idempotent — no-op if
            # already present. Requires the role to have CREATE on the DB
            # (Neon / Supabase grant this on the default user by default).
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        Base.metadata.create_all(conn)
        _add_missing_columns(conn)
        if is_pg:
            _widen_bigint_columns(conn)
        for stmt in (VEC_TABLES_SQL_PG if is_pg else VEC_TABLES_SQL):
            conn.exec_driver_sql(stmt)
        if is_pg:
            _ensure_pg_vec_dim(conn)
    log.info("db_initialized", url=str(eng.url), dialect=eng.dialect.name)


def _add_missing_columns(conn) -> None:
    """Add columns present in the ORM models but missing from the live DB.

    A poor-man's migration: handles ONLY additive changes (new nullable
    columns, or columns with a server/Python default). It never drops,
    renames, or retypes — those need a real migration (Alembic), which is
    the right long-term answer. This is a safety net so additive schema
    drift doesn't brick a dev's existing SQLite file (or a hosted DB
    between deploys).

    On SQLite, `ALTER TABLE ADD COLUMN` can't add a NOT NULL column without
    a default, so we skip those with a loud warning. Postgres has the same
    limitation for existing rows, so the skip applies there too.
    """
    from sqlalchemy import inspect as sa_inspect

    inspector = sa_inspect(conn)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all already built it with all columns
        live_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name in live_cols:
                continue
            has_default = (
                col.nullable
                or col.default is not None
                or col.server_default is not None
            )
            if not has_default:
                log.warning(
                    "db_skip_missing_required_column",
                    table=table.name,
                    column=col.name,
                    reason="NOT NULL without default — needs a real migration",
                )
                continue
            col_type = col.type.compile(dialect=conn.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col_type}'
            conn.exec_driver_sql(ddl)
            log.warning(
                "db_auto_added_column",
                table=table.name, column=col.name, type=str(col_type),
            )


def _widen_bigint_columns(conn) -> None:
    """Postgres-only: widen GitHub-ID columns from INTEGER (int4) to BIGINT.

    GitHub's numeric IDs (user/repo/issue) now exceed 2^31, which overflows
    Postgres INTEGER — an Issue Hunter run 500s with "integer out of range".
    SQLite's INTEGER is already 64-bit, so this only matters on Postgres.

    `create_all` never retypes an existing column, so a DB created before the
    models were corrected keeps the old int4 columns. This migration fixes
    them in place: drop the coupling FKs, widen every target column, re-add
    the FKs. Idempotent — no-ops once everything is already BIGINT.
    """
    from sqlalchemy import inspect as sa_inspect

    # (table, column) pairs that store a GitHub numeric ID.
    targets = [
        ("users", "github_id"),
        ("repos", "id"),
        ("issues", "id"),
        ("issues", "repo_id"),
        ("investigations", "issue_id"),
    ]
    # FK columns whose int type is coupled to a target PK — Postgres rejects a
    # type change that leaves the pair mismatched, so drop then recreate.
    # (table, column, ref_table, ref_column) — all ON DELETE CASCADE per models.
    fks = [
        ("issues", "repo_id", "repos", "id"),
        ("investigations", "issue_id", "issues", "id"),
    ]

    inspector = sa_inspect(conn)
    existing = set(inspector.get_table_names())

    def needs_widen(table: str, column: str) -> bool:
        if table not in existing:
            return False
        col = next(
            (c for c in inspector.get_columns(table) if c["name"] == column), None
        )
        return col is not None and "BIGINT" not in str(col["type"]).upper()

    if not any(needs_widen(t, c) for t, c in targets):
        return  # already migrated — fast path on every subsequent boot

    dropped: set[tuple[str, str]] = set()
    for table, column, _rt, _rc in fks:
        if table not in existing:
            continue
        for fk in inspector.get_foreign_keys(table):
            if column in fk.get("constrained_columns", []) and fk.get("name"):
                conn.exec_driver_sql(
                    f'ALTER TABLE "{table}" DROP CONSTRAINT "{fk["name"]}"'
                )
                dropped.add((table, column))

    for table, column in targets:
        if needs_widen(table, column):
            conn.exec_driver_sql(
                f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE BIGINT'
            )
            log.warning("db_widened_to_bigint", table=table, column=column)

    for table, column, ref_table, ref_column in fks:
        if (table, column) in dropped:
            conn.exec_driver_sql(
                f'ALTER TABLE "{table}" ADD CONSTRAINT "{table}_{column}_fkey" '
                f'FOREIGN KEY ("{column}") REFERENCES "{ref_table}" ("{ref_column}") '
                f"ON DELETE CASCADE"
            )


def _ensure_pg_vec_dim(conn) -> None:
    """Postgres-only: rebuild pgvector tables whose dimension no longer matches
    the configured embedder.

    The vec tables are created `vector(embedder_dim)` — 384 for the local
    backend, 1024 for Voyage. `CREATE TABLE IF NOT EXISTS` never resizes an
    existing table, so switching EMBEDDER_BACKEND (local↔voyage) leaves a
    stale dimension and every insert fails with "expected N dimensions".

    A dimension change invalidates all cached embeddings anyway, so dropping
    and recreating these (regenerable) tables is the correct, safe response.
    Idempotent: no-ops once the dimensions already match.
    """
    import re

    from sqlalchemy import text

    want = settings.embedder_dim
    # VEC_TABLES_SQL_PG is [user_skills_vec, issues_vec] — same order here.
    specs = {
        "user_skills_vec": VEC_TABLES_SQL_PG[0],
        "issues_vec": VEC_TABLES_SQL_PG[1],
    }
    for table, create_sql in specs.items():
        row = conn.execute(
            text(
                "SELECT format_type(a.atttypid, a.atttypmod) "
                "FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid "
                "WHERE c.relname = :t AND a.attname = 'embedding'"
            ),
            {"t": table},
        ).first()
        if row is None or not row[0]:
            continue  # table/column not present yet
        m = re.search(r"\((\d+)\)", row[0])  # 'vector(384)' -> 384
        if not m:
            continue
        current = int(m.group(1))
        if current == want:
            continue
        conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table}")
        conn.exec_driver_sql(create_sql)
        log.warning(
            "db_vec_table_rebuilt", table=table, old_dim=current, new_dim=want
        )


def reset_db(engine: Engine | None = None) -> None:
    """Drop everything and recreate. DESTRUCTIVE — dev/test only."""
    eng = engine or sessionmaker_factory().kw["bind"]
    is_pg = eng.dialect.name == "postgresql"
    with eng.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS issues_vec")
        conn.exec_driver_sql("DROP TABLE IF EXISTS user_skills_vec")
        Base.metadata.drop_all(conn)
        if is_pg:
            conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        Base.metadata.create_all(conn)
        for stmt in (VEC_TABLES_SQL_PG if is_pg else VEC_TABLES_SQL):
            conn.exec_driver_sql(stmt)
    log.warning("db_reset", url=str(eng.url), dialect=eng.dialect.name)
