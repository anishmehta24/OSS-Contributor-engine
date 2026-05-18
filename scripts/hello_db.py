"""Smoke test: SQLite + sqlite-vec extension load + basic vector ops.

Verifies:
    - sqlite3 stdlib works
    - sqlite-vec extension loads
    - We can create a vector table, insert, and run a similarity query

Usage:  uv run python scripts/hello_db.py
"""
import sqlite3
import struct
import sys
from pathlib import Path

import sqlite_vec


def serialize_f32(values: list[float]) -> bytes:
    """Pack a Python list of floats into the bytes format sqlite-vec expects."""
    return struct.pack(f"{len(values)}f", *values)


def main() -> int:
    db_path = Path(__file__).parent.parent / "smoke_test.db"
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    sqlite_version, vec_version = conn.execute(
        "select sqlite_version(), vec_version()"
    ).fetchone()
    print(f"SQLite version:     {sqlite_version}")
    print(f"sqlite-vec version: {vec_version}")

    conn.execute(
        "create virtual table items using vec0(embedding float[4])"
    )

    items = [
        (1, [0.1, 0.1, 0.1, 0.1]),
        (2, [0.2, 0.2, 0.2, 0.2]),
        (3, [0.9, 0.9, 0.9, 0.9]),
        (4, [1.0, 1.0, 1.0, 1.0]),
    ]
    for rowid, vec in items:
        conn.execute(
            "insert into items(rowid, embedding) values (?, ?)",
            (rowid, serialize_f32(vec)),
        )

    query = serialize_f32([0.15, 0.15, 0.15, 0.15])
    rows = conn.execute(
        """
        select rowid, distance
        from items
        where embedding match ?
        order by distance
        limit 3
        """,
        (query,),
    ).fetchall()

    print("\nNearest neighbors to [0.15, 0.15, 0.15, 0.15]:")
    for rowid, dist in rows:
        print(f"  rowid={rowid}  distance={dist:.4f}")

    conn.close()
    db_path.unlink(missing_ok=True)
    print("\nSQLite + sqlite-vec OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
