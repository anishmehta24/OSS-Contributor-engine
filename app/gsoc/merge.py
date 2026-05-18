"""Merge scraped GSoC orgs into the `gsoc_orgs` table.

The manual JSON seed (Batch 17) has hand-curated `primary_languages` and
`topics`. The scraper returns whatever the GSoC site exposes, which is
sometimes sparse or empty. Rules below favor curated data over scraped
noise: scraped fields only overwrite an existing row when the existing
field is missing.

Returns (new_count, updated_count) so callers / the CLI can report.
"""
from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GsocOrg
from app.gsoc.scraper import ScrapedOrg

log = structlog.get_logger(__name__)


def _normalize_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")


def _union_preserving_case(existing: list[str], incoming: list[str]) -> list[str]:
    """Case-insensitive union; keep the first casing we've seen."""
    seen_lower = {x.lower() for x in existing}
    out = list(existing)
    for item in incoming:
        if item.lower() not in seen_lower:
            out.append(item)
            seen_lower.add(item.lower())
    return out


def merge_scraped_orgs(
    session: Session, scraped: list[ScrapedOrg]
) -> tuple[int, int]:
    """Upsert scraped orgs. Returns (new_count, updated_count)."""
    new_count = 0
    updated_count = 0

    existing_rows = list(session.execute(select(GsocOrg)).scalars())
    by_slug = {o.slug: o for o in existing_rows}
    by_norm = {_normalize_slug(o.slug): o for o in existing_rows}

    for s in scraped:
        existing = by_slug.get(s.slug) or by_norm.get(_normalize_slug(s.slug))

        if existing is None:
            row = GsocOrg(
                slug=s.slug,
                name=s.name,
                description=s.description,
                homepage_url=s.homepage_url,
                project_ideas_url=s.project_ideas_url,
                primary_languages=list(s.technologies),
                topics=list(s.topics),
                years_participated=[s.year],
                last_seen_year=s.year,
                seed_source="scraper",
            )
            session.add(row)
            # Track in lookup so a later scraped year for the same new org
            # updates this row instead of inserting a duplicate.
            by_slug[s.slug] = row
            by_norm[_normalize_slug(s.slug)] = row
            new_count += 1
            continue

        years = sorted(set(existing.years_participated or []) | {s.year})
        existing.years_participated = years
        existing.last_seen_year = max(years)

        # Languages: union — scraper sometimes reports new tech a manual
        # entry missed (e.g., Mozilla picking up "Swift" in 2025).
        if s.technologies:
            existing.primary_languages = _union_preserving_case(
                list(existing.primary_languages or []), s.technologies
            )

        # Topics: don't overwrite curated topics. Only fill in if empty.
        if not existing.topics and s.topics:
            existing.topics = list(s.topics)

        # Fill in nulls only; don't clobber curated text.
        if not existing.homepage_url and s.homepage_url:
            existing.homepage_url = s.homepage_url
        if not existing.description and s.description:
            existing.description = s.description
        if not existing.project_ideas_url and s.project_ideas_url:
            existing.project_ideas_url = s.project_ideas_url

        # seed_source records *original* provenance, not last-touched, so
        # we can tell at a glance whether the row started life in the
        # curated JSON or was discovered by the scraper. Don't change it
        # on update.

        updated_count += 1

    session.flush()
    log.info("gsoc_scrape_merged", new=new_count, updated=updated_count)
    return new_count, updated_count
