"""Tests for the additive-column auto-migration in init_db()."""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.db.session import _add_missing_columns


@pytest.mark.integration
def test_adds_missing_nullable_column(engine):
    """Simulate schema drift: drop a column from the live table, then run
    the migrator and confirm it's re-added."""
    # `engine` fixture already created all tables. Simulate an older DB by
    # rebuilding pilot_runs without the pr_url column.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS pilot_runs")
        # Minimal older-shape table: missing all the Batch 34/35 columns.
        conn.exec_driver_sql("""
            CREATE TABLE pilot_runs (
                id VARCHAR(36) PRIMARY KEY,
                investigation_id VARCHAR(36) NOT NULL,
                user_id INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

    # Before: the new columns are absent.
    insp = inspect(engine)
    cols_before = {c["name"] for c in insp.get_columns("pilot_runs")}
    assert "pr_url" not in cols_before
    assert "fork_url" not in cols_before

    # Run the migrator.
    with engine.begin() as conn:
        _add_missing_columns(conn)

    # After: all the model's columns exist.
    insp2 = inspect(engine)
    cols_after = {c["name"] for c in insp2.get_columns("pilot_runs")}
    for expected in (
        "fork_url", "branch_ref", "pushed_at", "push_error",
        "pr_url", "pr_number", "pr_opened_at", "pr_error",
        "summary", "accepted_diff", "transcript_json",
    ):
        assert expected in cols_after, f"{expected} should have been added"


@pytest.mark.integration
def test_idempotent_when_schema_current(engine):
    """Running the migrator on an up-to-date schema is a no-op (no error)."""
    with engine.begin() as conn:
        _add_missing_columns(conn)
        _add_missing_columns(conn)  # twice — must not raise


@pytest.mark.integration
def test_migrated_table_is_queryable(engine):
    """After migration, a SELECT touching the new columns must succeed —
    this is the exact failure the safety net prevents."""
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS pilot_runs")
        conn.exec_driver_sql("""
            CREATE TABLE pilot_runs (
                id VARCHAR(36) PRIMARY KEY,
                investigation_id VARCHAR(36) NOT NULL,
                user_id INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        _add_missing_columns(conn)
        # This SELECT references pr_url — would have thrown
        # 'no such column' before the migration.
        result = conn.execute(
            text("SELECT pr_url, fork_url, pr_number FROM pilot_runs"),
        ).all()
    assert result == []
