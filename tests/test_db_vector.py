"""vec0 virtual-table sanity: insert + similarity search return correct order."""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db.session import VEC_DIM
from app.db.vector import (
    _validate_table,
    delete_vector,
    insert_vector,
    search_similar,
    serialize_f32,
)


def _zero_vec() -> list[float]:
    return [0.0] * VEC_DIM


def _unit_at(i: int, value: float = 1.0) -> list[float]:
    v = _zero_vec()
    v[i] = value
    return v


@pytest.mark.unit
def test_serialize_f32_byte_count():
    blob = serialize_f32([1.0, 2.0, 3.0])
    assert len(blob) == 12  # 3 floats * 4 bytes


@pytest.mark.unit
def test_unknown_table_rejected():
    with pytest.raises(ValueError):
        _validate_table("evil_table")


@pytest.mark.unit
def test_insert_and_search_returns_nearest_first(session):
    insert_vector(session, "issues_vec", rowid=1, embedding=_unit_at(0, 1.0))
    insert_vector(session, "issues_vec", rowid=2, embedding=_unit_at(1, 1.0))
    insert_vector(session, "issues_vec", rowid=3, embedding=_unit_at(2, 1.0))
    insert_vector(session, "issues_vec", rowid=4, embedding=_unit_at(3, 1.0))
    session.commit()

    query = _unit_at(0, 0.9)
    hits = search_similar(session, "issues_vec", query, k=2)
    assert len(hits) == 2
    assert hits[0].rowid == 1
    assert hits[0].distance < hits[1].distance


@pytest.mark.unit
def test_insert_or_replace_overwrites(session):
    insert_vector(session, "user_skills_vec", rowid=1, embedding=_unit_at(0, 1.0))
    session.commit()
    insert_vector(session, "user_skills_vec", rowid=1, embedding=_unit_at(5, 1.0))
    session.commit()

    rows = session.execute(text("SELECT COUNT(*) FROM user_skills_vec")).scalar()
    assert rows == 1

    hits = search_similar(session, "user_skills_vec", _unit_at(5, 0.9), k=1)
    assert hits[0].rowid == 1


@pytest.mark.unit
def test_delete_vector_removes_row(session):
    insert_vector(session, "issues_vec", rowid=10, embedding=_unit_at(0, 1.0))
    insert_vector(session, "issues_vec", rowid=11, embedding=_unit_at(1, 1.0))
    session.commit()
    delete_vector(session, "issues_vec", rowid=10)
    session.commit()

    hits = search_similar(session, "issues_vec", _unit_at(0, 0.9), k=5)
    rowids = {h.rowid for h in hits}
    assert 10 not in rowids
    assert 11 in rowids


@pytest.mark.unit
def test_search_in_empty_table_returns_no_hits(session):
    hits = search_similar(session, "issues_vec", _unit_at(0, 1.0), k=10)
    assert hits == []
