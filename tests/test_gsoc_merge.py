"""Tests for merge_scraped_orgs — how scraper output combines with seeded rows."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.db.models import GsocOrg
from app.gsoc.merge import merge_scraped_orgs
from app.gsoc.scraper import ScrapedOrg


def _seed_manual(session, **kwargs) -> GsocOrg:
    defaults = dict(
        slug="apache",
        name="Apache",
        primary_languages=["Java"],
        topics=["infrastructure"],
        years_participated=[2023, 2024],
        last_seen_year=2024,
        seed_source="manual",
    )
    defaults.update(kwargs)
    org = GsocOrg(**defaults)
    session.add(org)
    session.commit()
    return org


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_new_scraped_org_is_inserted(session):
    scraped = [ScrapedOrg(
        slug="newcomer", name="New Org", year=2025,
        description="Brand new",
        homepage_url="https://x.com",
        technologies=["Go"],
        topics=["devops"],
    )]
    new, updated = merge_scraped_orgs(session, scraped)
    session.commit()
    assert (new, updated) == (1, 0)

    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "newcomer")).scalar_one()
    assert row.primary_languages == ["Go"]
    assert row.years_participated == [2025]
    assert row.last_seen_year == 2025
    assert row.seed_source == "scraper"


@pytest.mark.unit
def test_same_new_org_across_multiple_years_collapses_to_one_row(session):
    scraped = [
        ScrapedOrg(slug="nv", name="N", year=2023, technologies=["Python"]),
        ScrapedOrg(slug="nv", name="N", year=2024, technologies=["Python"]),
        ScrapedOrg(slug="nv", name="N", year=2025, technologies=["Python"]),
    ]
    new, updated = merge_scraped_orgs(session, scraped)
    session.commit()
    assert (new, updated) == (1, 2)

    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "nv")).scalar_one()
    assert row.years_participated == [2023, 2024, 2025]
    assert row.last_seen_year == 2025


# ---------------------------------------------------------------------------
# Updates — preservation of curated fields
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_scraped_org_adds_year_to_existing(session):
    _seed_manual(session)
    new, updated = merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025),
    ])
    session.commit()
    assert (new, updated) == (0, 1)

    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.years_participated == [2023, 2024, 2025]
    assert row.last_seen_year == 2025


@pytest.mark.unit
def test_seed_source_stays_manual_after_scrape(session):
    """Provenance = original source, not last-touched."""
    _seed_manual(session)
    merge_scraped_orgs(session, [ScrapedOrg(slug="apache", name="Apache", year=2025)])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.seed_source == "manual"


@pytest.mark.unit
def test_curated_topics_not_overwritten_by_scraper(session):
    _seed_manual(session, topics=["infrastructure", "web", "big-data"])
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025, topics=["random-noise"]),
    ])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.topics == ["infrastructure", "web", "big-data"]


@pytest.mark.unit
def test_topics_filled_in_when_existing_empty(session):
    _seed_manual(session, topics=[])
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025, topics=["new-topic"]),
    ])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.topics == ["new-topic"]


@pytest.mark.unit
def test_languages_are_unioned_case_insensitively(session):
    _seed_manual(session, primary_languages=["Java", "Python"])
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025,
                   technologies=["java", "Scala"]),  # java is dup-different-case
    ])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    # Java preserved with original casing; Scala appended.
    assert row.primary_languages == ["Java", "Python", "Scala"]


@pytest.mark.unit
def test_homepage_only_filled_when_null(session):
    _seed_manual(session, homepage_url="https://curated.example/")
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025,
                   homepage_url="https://scraped.example/"),
    ])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.homepage_url == "https://curated.example/"


@pytest.mark.unit
def test_homepage_filled_when_missing(session):
    _seed_manual(session, homepage_url=None)
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="apache", name="Apache", year=2025,
                   homepage_url="https://scraped.example/"),
    ])
    session.commit()
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "apache")).scalar_one()
    assert row.homepage_url == "https://scraped.example/"


# ---------------------------------------------------------------------------
# Slug matching
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_slugs_match_through_normalization(session):
    # Existing row uses "the-apache-foundation"; scraper returns "The_Apache_Foundation"
    _seed_manual(session, slug="the-apache-foundation", name="ASF")
    merge_scraped_orgs(session, [
        ScrapedOrg(slug="The_Apache_Foundation", name="ASF", year=2025),
    ])
    session.commit()
    rows = list(session.execute(select(GsocOrg)).scalars())
    assert len(rows) == 1
    assert 2025 in rows[0].years_participated


# ---------------------------------------------------------------------------
# Idempotency / no-op
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_rerunning_merge_is_a_noop_for_unchanged_data(session):
    scraped = [ScrapedOrg(slug="x", name="X", year=2025, technologies=["Go"])]
    new1, updated1 = merge_scraped_orgs(session, scraped)
    session.commit()
    new2, updated2 = merge_scraped_orgs(session, scraped)
    session.commit()
    assert (new1, updated1) == (1, 0)
    assert (new2, updated2) == (0, 1)
    row = session.execute(select(GsocOrg).where(GsocOrg.slug == "x")).scalar_one()
    assert row.years_participated == [2025]


@pytest.mark.unit
def test_empty_input_is_noop(session):
    _seed_manual(session)
    new, updated = merge_scraped_orgs(session, [])
    assert (new, updated) == (0, 0)
