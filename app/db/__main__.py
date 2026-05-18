"""DB CLI: init / reset / inspect / seed / scrape.

Usage:
    uv run python -m app.db init                       # create tables + vec tables (idempotent)
    uv run python -m app.db reset --yes                # DROP everything + recreate (destructive)
    uv run python -m app.db tables                     # list tables
    uv run python -m app.db counts                     # row counts per table
    uv run python -m app.db seed-gsoc                  # load bundled GSoC org JSON (idempotent)
    uv run python -m app.db scrape-gsoc                # scrape current + past 3 years from GSoC site
    uv run python -m app.db scrape-gsoc --year 2025    # scrape one year
    uv run python -m app.db scrape-gsoc --dry-run      # fetch + parse but skip the DB write
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import httpx
from sqlalchemy import text

from app.core.logging import configure_logging
from app.db import models as m
from app.db.session import get_session, init_db, reset_db, sessionmaker_factory
from app.gsoc.merge import merge_scraped_orgs
from app.gsoc.scraper import DEFAULT_USER_AGENT, scrape_year
from app.gsoc.seeds.loader import load_seed_orgs

DEFAULT_SCRAPE_LOOKBACK_YEARS = 4  # current + past 3
DEFAULT_SCRAPE_CACHE_DIR = Path(".cache/gsoc")


def cmd_init(_: argparse.Namespace) -> int:
    init_db()
    print("Database initialized.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    if not args.yes:
        print("Refusing to reset without --yes. This drops ALL data.")
        return 1
    reset_db()
    print("Database reset.")
    return 0


def cmd_tables(_: argparse.Namespace) -> int:
    sm = sessionmaker_factory()
    with sm() as session:
        rows = session.execute(
            text("SELECT name, type FROM sqlite_master WHERE type IN ('table','virtual') ORDER BY name")
        ).all()
        for name, typ in rows:
            print(f"  {typ:10s}  {name}")
    return 0


def cmd_counts(_: argparse.Namespace) -> int:
    with get_session() as session:
        for model in m.all_models():
            count = session.execute(
                text(f"SELECT COUNT(*) FROM {model.__tablename__}")
            ).scalar()
            print(f"  {model.__tablename__:20s}  {count}")
    return 0


def cmd_seed_gsoc(_: argparse.Namespace) -> int:
    with get_session() as session:
        count = load_seed_orgs(session)
    print(f"Loaded {count} GSoC orgs from bundled seed.")
    return 0


def cmd_scrape_gsoc(args: argparse.Namespace) -> int:
    if args.year:
        years = [args.year]
    else:
        current = date.today().year
        years = list(range(current - DEFAULT_SCRAPE_LOOKBACK_YEARS + 1, current + 1))

    cache_dir = Path(args.cache_dir) if args.cache_dir else DEFAULT_SCRAPE_CACHE_DIR
    all_scraped = []

    with httpx.Client(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    ) as http:
        for year in years:
            try:
                orgs = scrape_year(year, http_client=http, cache_dir=cache_dir)
            except httpx.HTTPError as e:
                print(f"  {year}: FETCH FAILED — {e}")
                continue
            print(f"  {year}: scraped {len(orgs)} orgs")
            all_scraped.extend(orgs)

    if args.dry_run:
        print(f"\nDry run — DB untouched. Would merge {len(all_scraped)} scraped entries.")
        return 0

    if not all_scraped:
        print("\nNo orgs scraped — DB untouched.")
        return 0

    with get_session() as session:
        new, updated = merge_scraped_orgs(session, all_scraped)
    print(f"\nMerged: {new} new, {updated} updated.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--yes", action="store_true", help="confirm destructive reset")
    p_reset.set_defaults(func=cmd_reset)

    sub.add_parser("tables").set_defaults(func=cmd_tables)
    sub.add_parser("counts").set_defaults(func=cmd_counts)
    sub.add_parser("seed-gsoc").set_defaults(func=cmd_seed_gsoc)

    p_scrape = sub.add_parser("scrape-gsoc")
    p_scrape.add_argument("--year", type=int, help="single year to scrape; default: current + past 3")
    p_scrape.add_argument("--cache-dir", help="directory to cache raw HTML (default: .cache/gsoc)")
    p_scrape.add_argument("--dry-run", action="store_true", help="fetch + parse but skip DB write")
    p_scrape.set_defaults(func=cmd_scrape_gsoc)

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
