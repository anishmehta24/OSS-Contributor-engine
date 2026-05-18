"""Tests for the GSoC org query helpers."""
from __future__ import annotations

import pytest

from app.db.models import GsocOrg
from app.gsoc.queries import (
    find_orgs_for_languages,
    find_orgs_for_topics,
    list_active_orgs,
)


def _seed(session, rows: list[dict]) -> None:
    for r in rows:
        session.add(GsocOrg(
            slug=r["slug"],
            name=r["slug"].title(),
            primary_languages=r.get("languages", []),
            topics=r.get("topics", []),
            years_participated=r.get("years", []),
            last_seen_year=max(r.get("years", [])) if r.get("years") else None,
        ))
    session.commit()


@pytest.mark.unit
def test_list_active_orgs_includes_recent_only(session):
    _seed(session, [
        {"slug": "old", "years": [2018, 2019]},
        {"slug": "mid", "years": [2023]},
        {"slug": "new", "years": [2024, 2025]},
    ])
    active = list_active_orgs(session, recent_years=3)
    slugs = [o.slug for o in active]
    # max year = 2025 -> cutoff 2023 -> excludes "old"
    assert "old" not in slugs
    assert "mid" in slugs
    assert "new" in slugs


@pytest.mark.unit
def test_list_active_orgs_sorted_newest_first(session):
    _seed(session, [
        {"slug": "a", "years": [2024]},
        {"slug": "b", "years": [2025]},
        {"slug": "c", "years": [2023]},
    ])
    active = list_active_orgs(session, recent_years=5)
    assert [o.slug for o in active] == ["b", "a", "c"]


@pytest.mark.unit
def test_list_active_orgs_empty_db(session):
    assert list_active_orgs(session) == []


@pytest.mark.unit
def test_list_active_orgs_limit(session):
    _seed(session, [
        {"slug": f"o{i}", "years": [2025]} for i in range(5)
    ])
    active = list_active_orgs(session, limit=2)
    assert len(active) == 2


@pytest.mark.unit
def test_find_orgs_for_languages_matches_case_insensitively(session):
    _seed(session, [
        {"slug": "py", "languages": ["Python"], "years": [2025]},
        {"slug": "go", "languages": ["Go"], "years": [2025]},
        {"slug": "rs", "languages": ["Rust"], "years": [2025]},
    ])
    out = find_orgs_for_languages(session, ["python", "RUST"])
    slugs = {o.slug for o in out}
    assert slugs == {"py", "rs"}


@pytest.mark.unit
def test_find_orgs_for_languages_excludes_stale(session):
    _seed(session, [
        {"slug": "old-py", "languages": ["Python"], "years": [2018]},
        {"slug": "new-py", "languages": ["Python"], "years": [2025]},
    ])
    out = find_orgs_for_languages(session, ["Python"], recent_years=3)
    assert [o.slug for o in out] == ["new-py"]


@pytest.mark.unit
def test_find_orgs_for_languages_empty_input(session):
    _seed(session, [{"slug": "x", "languages": ["Python"], "years": [2025]}])
    assert find_orgs_for_languages(session, []) == []
    assert find_orgs_for_languages(session, ["   "]) == []


@pytest.mark.unit
def test_find_orgs_for_topics(session):
    _seed(session, [
        {"slug": "ml", "topics": ["ml", "scientific-computing"], "years": [2025]},
        {"slug": "web", "topics": ["web"], "years": [2025]},
    ])
    out = find_orgs_for_topics(session, ["ML"])
    assert [o.slug for o in out] == ["ml"]


@pytest.mark.unit
def test_find_orgs_respects_limit(session):
    _seed(session, [
        {"slug": f"o{i}", "languages": ["Python"], "years": [2025]} for i in range(5)
    ])
    out = find_orgs_for_languages(session, ["Python"], limit=3)
    assert len(out) == 3
