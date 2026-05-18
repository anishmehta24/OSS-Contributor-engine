"""Tests for the bundled GSoC org seed loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.db.models import GsocOrg
from app.gsoc.seeds.loader import SEED_PATH, load_seed_orgs


@pytest.mark.unit
def test_seed_file_exists_and_is_a_list():
    assert SEED_PATH.exists(), f"missing seed file: {SEED_PATH}"
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) >= 20  # we curated 30; guard against accidental empties


@pytest.mark.unit
def test_seed_entries_have_required_fields():
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for entry in data:
        assert entry.get("slug"), f"slug missing in {entry}"
        assert entry.get("name"), f"name missing in {entry}"
        assert isinstance(entry.get("primary_languages", []), list)
        assert isinstance(entry.get("topics", []), list)
        assert isinstance(entry.get("years_participated", []), list)


@pytest.mark.unit
def test_loader_populates_db(session):
    count = load_seed_orgs(session)
    session.commit()
    assert count > 0
    row_count = session.execute(select(func.count(GsocOrg.id))).scalar()
    assert row_count == count


@pytest.mark.unit
def test_loader_is_idempotent(session):
    first = load_seed_orgs(session)
    session.commit()
    second = load_seed_orgs(session)
    session.commit()
    assert first == second
    row_count = session.execute(select(func.count(GsocOrg.id))).scalar()
    assert row_count == first


@pytest.mark.unit
def test_loader_computes_last_seen_year(session):
    load_seed_orgs(session)
    session.commit()
    org = session.execute(
        select(GsocOrg).where(GsocOrg.slug == "rust-foundation")
    ).scalar_one()
    assert org.last_seen_year == max(org.years_participated)


@pytest.mark.unit
def test_loader_updates_existing_row_in_place(session, tmp_path):
    seed_a = tmp_path / "a.json"
    seed_a.write_text(json.dumps([
        {"slug": "x", "name": "Old Name", "primary_languages": ["Python"],
         "topics": [], "years_participated": [2022]},
    ]), encoding="utf-8")
    seed_b = tmp_path / "b.json"
    seed_b.write_text(json.dumps([
        {"slug": "x", "name": "New Name", "primary_languages": ["Go"],
         "topics": ["devops"], "years_participated": [2023, 2024]},
    ]), encoding="utf-8")

    load_seed_orgs(session, path=seed_a)
    session.commit()
    load_seed_orgs(session, path=seed_b)
    session.commit()

    rows = session.execute(select(GsocOrg).where(GsocOrg.slug == "x")).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "New Name"
    assert rows[0].primary_languages == ["Go"]
    assert rows[0].topics == ["devops"]
    assert rows[0].last_seen_year == 2024


@pytest.mark.unit
def test_loader_skips_entry_without_slug(session, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([
        {"name": "No Slug"},
        {"slug": "good", "name": "Good"},
    ]), encoding="utf-8")
    count = load_seed_orgs(session, path=bad)
    session.commit()
    assert count == 1
    slugs = [r.slug for r in session.execute(select(GsocOrg)).scalars()]
    assert slugs == ["good"]


@pytest.mark.unit
def test_loader_rejects_non_list_json(session, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_seed_orgs(session, path=Path(bad))
