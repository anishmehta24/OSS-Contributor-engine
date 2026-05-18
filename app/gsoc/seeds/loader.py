"""Load the bundled GSoC org seed JSON into the `gsoc_orgs` table.

Idempotent: keyed by `slug`, so re-running updates existing rows in place
rather than creating duplicates. Used by `python -m app.db seed-gsoc` and
by tests that need a populated org list.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GsocOrg

log = structlog.get_logger(__name__)

SEED_PATH = Path(__file__).with_name("orgs.json")


def _read_seed(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or SEED_PATH
    with target.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Seed file {target} must contain a JSON list")
    return data


def load_seed_orgs(session: Session, *, path: Path | None = None) -> int:
    """Upsert every org from the seed JSON. Returns count of rows touched.

    Existing rows (matched by slug) are updated so curated changes in the
    JSON propagate without needing to reset the DB.
    """
    entries = _read_seed(path)
    touched = 0
    for entry in entries:
        slug = entry.get("slug")
        if not slug:
            log.warning("gsoc_seed_skip_no_slug", entry=entry)
            continue

        years = entry.get("years_participated") or []
        last_seen = max(years) if years else None

        existing = session.execute(
            select(GsocOrg).where(GsocOrg.slug == slug)
        ).scalar_one_or_none()

        if existing is None:
            session.add(
                GsocOrg(
                    slug=slug,
                    name=entry["name"],
                    github_login=entry.get("github_login"),
                    description=entry.get("description"),
                    homepage_url=entry.get("homepage_url"),
                    project_ideas_url=entry.get("project_ideas_url"),
                    primary_languages=entry.get("primary_languages") or [],
                    topics=entry.get("topics") or [],
                    years_participated=years,
                    last_seen_year=last_seen,
                    seed_source="manual",
                )
            )
        else:
            existing.name = entry["name"]
            existing.github_login = entry.get("github_login")
            existing.description = entry.get("description")
            existing.homepage_url = entry.get("homepage_url")
            existing.project_ideas_url = entry.get("project_ideas_url")
            existing.primary_languages = entry.get("primary_languages") or []
            existing.topics = entry.get("topics") or []
            existing.years_participated = years
            existing.last_seen_year = last_seen
            # don't overwrite seed_source if a scraper has since updated it
            if existing.seed_source == "manual":
                existing.seed_source = "manual"

        touched += 1

    session.flush()
    log.info("gsoc_seed_loaded", count=touched)
    return touched
