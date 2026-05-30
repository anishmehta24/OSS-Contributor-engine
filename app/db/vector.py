"""Sync helpers for the vector tables — dual-dialect.

Why these helpers exist:
    - sqlite-vec stores vectors as raw bytes (struct.pack of float32) and
      queries them with a `MATCH` operator that's not part of SQLAlchemy.
    - pgvector stores them as a real `vector(N)` column and queries them
      with operator overloads (`<=>` for cosine distance).

Both dialects use the same logical tables:
    user_skills_vec  ↔  user_skills.id
    issues_vec       ↔  issues.id

Call sites are dialect-agnostic — they pass a Session and these helpers
inspect `session.bind.dialect.name` to pick the right write/read path.
The SQLite path uses `rowid` (vec0's PK), the Postgres path uses `id`
(real BIGINT column on a normal table). Both store at the same logical
ID, so dedup/replace semantics match.
"""
from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

ALLOWED_TABLES = {"user_skills_vec", "issues_vec"}


@dataclass(frozen=True)
class SimilarityHit:
    rowid: int
    distance: float


def _validate_table(table: str) -> None:
    if table not in ALLOWED_TABLES:
        # Defensive: prevent injection via table-name interpolation.
        raise ValueError(f"Unknown vec table: {table!r}. Allowed: {sorted(ALLOWED_TABLES)}")


def _is_postgres(session: Session) -> bool:
    bind = session.get_bind()
    return bind.dialect.name == "postgresql"


def serialize_f32(values: Sequence[float]) -> bytes:
    """Pack a Python sequence of floats into bytes (little-endian f32).
    SQLite path only — Postgres uses pgvector's text literal form."""
    return struct.pack(f"{len(values)}f", *values)


def _pgvector_literal(values: Sequence[float]) -> str:
    """Render a Python sequence as pgvector's text literal: '[v1,v2,...]'.
    Bound via :param then cast `::vector` in the SQL — avoids needing the
    psycopg vector type adapter to be registered on every connection."""
    return "[" + ",".join(format(v, ".7g") for v in values) + "]"


def insert_vector(
    session: Session,
    table: str,
    rowid: int,
    embedding: Sequence[float],
) -> None:
    """Insert-or-replace a vector at the given id.

    SQLite path: vec0 doesn't support `INSERT OR REPLACE` on the PK, so
    delete-then-insert. Postgres path: ON CONFLICT DO UPDATE.
    """
    _validate_table(table)
    if _is_postgres(session):
        session.execute(
            text(
                f"""
                INSERT INTO {table} (id, embedding)
                VALUES (:id, CAST(:emb AS vector))
                ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding
                """
            ),
            {"id": rowid, "emb": _pgvector_literal(embedding)},
        )
        return

    blob = serialize_f32(embedding)
    session.execute(
        text(f"DELETE FROM {table} WHERE rowid = :r"),
        {"r": rowid},
    )
    session.execute(
        text(f"INSERT INTO {table}(rowid, embedding) VALUES (:r, :e)"),
        {"r": rowid, "e": blob},
    )


def delete_vector(session: Session, table: str, rowid: int) -> None:
    _validate_table(table)
    if _is_postgres(session):
        session.execute(
            text(f"DELETE FROM {table} WHERE id = :r"),
            {"r": rowid},
        )
        return
    session.execute(
        text(f"DELETE FROM {table} WHERE rowid = :r"),
        {"r": rowid},
    )


def search_similar(
    session: Session,
    table: str,
    query_embedding: Sequence[float],
    *,
    k: int = 10,
) -> list[SimilarityHit]:
    """Return the k nearest neighbors of query_embedding, sorted ascending by
    distance. Both dialects use cosine distance for parity (sqlite-vec's
    default MATCH metric is also cosine for FLOAT vectors)."""
    _validate_table(table)
    if _is_postgres(session):
        result = session.execute(
            text(
                f"""
                SELECT id, embedding <=> CAST(:q AS vector) AS distance
                FROM {table}
                WHERE embedding IS NOT NULL
                ORDER BY distance
                LIMIT :k
                """
            ),
            {"q": _pgvector_literal(query_embedding), "k": k},
        )
        return [SimilarityHit(rowid=row[0], distance=float(row[1])) for row in result.all()]

    blob = serialize_f32(query_embedding)
    result = session.execute(
        text(
            f"""
            SELECT rowid, distance
            FROM {table}
            WHERE embedding MATCH :q
            ORDER BY distance
            LIMIT :k
            """
        ),
        {"q": blob, "k": k},
    )
    return [SimilarityHit(rowid=row[0], distance=row[1]) for row in result.all()]
