"""Engine-level checks: extension loads, FK pragma is on, schema is intact."""
from __future__ import annotations

import pytest
from sqlalchemy import text


@pytest.mark.unit
def test_sqlite_vec_extension_is_loaded(engine):
    with engine.connect() as conn:
        version = conn.execute(text("SELECT vec_version()")).scalar()
    assert version is not None
    assert version.startswith("v")


@pytest.mark.unit
def test_foreign_keys_pragma_enabled(engine):
    with engine.connect() as conn:
        fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
    assert fk == 1


@pytest.mark.unit
def test_all_tables_exist(engine):
    expected = {
        "users", "user_skills", "repos", "issues",
        "investigations", "agent_runs",
        "user_skills_vec", "issues_vec",
    }
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type IN ('table')")
        ).all()
    found = {r[0] for r in rows}
    missing = expected - found
    assert not missing, f"Missing tables: {missing}"
