"""Read-side helpers for the `gsoc_orgs` table.

These are the lookup queries the Issue Hunter will use in GSoC mode
(Batch 19) — given a user's languages/topics, narrow the candidate orgs
to those that have actually shipped GSoC projects recently.

"Active" = participated within the last N years (default 3). The cutoff
year is computed from the freshest `last_seen_year` we have on file —
not from `date.today().year` — so the helpers stay deterministic in
tests and don't go silent if the seed list is older than expected.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import GsocOrg

DEFAULT_RECENT_YEARS = 3


def _normalize(values: Iterable[str] | None) -> set[str]:
    return {v.strip().lower() for v in (values or []) if v and v.strip()}


def _max_seen_year(session: Session) -> int | None:
    return session.execute(select(func.max(GsocOrg.last_seen_year))).scalar()


def list_active_orgs(
    session: Session,
    *,
    recent_years: int = DEFAULT_RECENT_YEARS,
    limit: int | None = None,
) -> list[GsocOrg]:
    """Orgs whose `last_seen_year` falls within the most recent N years.

    With the default `recent_years=3` and a freshest year of 2025, this
    returns every org with last_seen_year >= 2023.
    """
    max_year = _max_seen_year(session)
    stmt = select(GsocOrg)
    if max_year is not None:
        cutoff = max_year - max(0, recent_years - 1)
        stmt = stmt.where(GsocOrg.last_seen_year >= cutoff)
    stmt = stmt.order_by(GsocOrg.last_seen_year.desc(), GsocOrg.name)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars())


def find_orgs_for_languages(
    session: Session,
    languages: Iterable[str],
    *,
    recent_years: int = DEFAULT_RECENT_YEARS,
    limit: int = 20,
) -> list[GsocOrg]:
    """Active orgs whose primary_languages overlap the user's languages.

    Matching happens in Python because primary_languages is stored as a
    JSON list — SQLite has no first-class array containment operator and
    the table is small (<200 rows even with the scraper).
    """
    wanted = _normalize(languages)
    if not wanted:
        return []
    active = list_active_orgs(session, recent_years=recent_years)
    matches = [
        org for org in active if wanted & _normalize(org.primary_languages)
    ]
    return matches[:limit]


def find_orgs_for_topics(
    session: Session,
    topics: Iterable[str],
    *,
    recent_years: int = DEFAULT_RECENT_YEARS,
    limit: int = 20,
) -> list[GsocOrg]:
    """Active orgs whose topics overlap the user's domains/interests."""
    wanted = _normalize(topics)
    if not wanted:
        return []
    active = list_active_orgs(session, recent_years=recent_years)
    matches = [org for org in active if wanted & _normalize(org.topics)]
    return matches[:limit]
