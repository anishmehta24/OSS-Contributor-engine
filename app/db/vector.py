"""Sync helpers for the vec0 virtual tables.

Why these helpers exist:
    - sqlite-vec needs vectors packed as raw bytes (struct.pack of float32)
    - Similarity queries use the `match` operator, which is sqlite-vec specific
      and not part of SQLAlchemy's expression language

The vec0 tables (`user_skills_vec`, `issues_vec`) are created in
`app/db/session.py:init_db`. They link to the main tables by rowid:
    user_skills_vec.rowid == user_skills.id
    issues_vec.rowid       == issues.id
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


def serialize_f32(values: Sequence[float]) -> bytes:
    """Pack a Python sequence of floats into bytes (little-endian f32)."""
    return struct.pack(f"{len(values)}f", *values)


def insert_vector(
    session: Session,
    table: str,
    rowid: int,
    embedding: Sequence[float],
) -> None:
    """Insert (or replace) a vector at the given rowid.

    sqlite-vec's vec0 virtual tables don't support `INSERT OR REPLACE`
    conflict resolution on the primary key, so we DELETE then INSERT.
    """
    _validate_table(table)
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
    """Return the k nearest neighbors of query_embedding, sorted ascending by distance."""
    _validate_table(table)
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
