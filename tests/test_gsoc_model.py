"""Smoke tests for the GsocOrg ORM model and table shape."""
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import GsocOrg


@pytest.mark.unit
def test_gsoc_org_round_trip(session):
    org = GsocOrg(
        slug="example",
        name="Example",
        github_login="example-gh",
        description="An example org",
        homepage_url="https://example.org",
        primary_languages=["Python", "Go"],
        topics=["web"],
        years_participated=[2023, 2024],
        last_seen_year=2024,
        seed_source="manual",
    )
    session.add(org)
    session.commit()

    fetched = session.execute(
        select(GsocOrg).where(GsocOrg.slug == "example")
    ).scalar_one()
    assert fetched.id is not None
    assert fetched.primary_languages == ["Python", "Go"]
    assert fetched.years_participated == [2023, 2024]
    assert fetched.last_seen_year == 2024
    assert fetched.seed_source == "manual"


@pytest.mark.unit
def test_gsoc_slug_must_be_unique(session):
    session.add(GsocOrg(slug="dup", name="A"))
    session.commit()
    session.add(GsocOrg(slug="dup", name="B"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


@pytest.mark.unit
def test_gsoc_defaults_for_json_columns(session):
    org = GsocOrg(slug="minimal", name="Minimal")
    session.add(org)
    session.commit()
    session.refresh(org)
    assert org.primary_languages == []
    assert org.topics == []
    assert org.years_participated == []
    assert org.seed_source == "manual"
    assert org.last_seen_year is None
