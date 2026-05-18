"""DB CLI: init / reset / inspect.

Usage:
    uv run python -m app.db init           # create tables + vec tables (idempotent)
    uv run python -m app.db reset --yes    # DROP everything + recreate (destructive)
    uv run python -m app.db tables         # list tables
    uv run python -m app.db counts         # row counts per table
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from app.core.logging import configure_logging
from app.db import models as m
from app.db.session import get_session, init_db, reset_db, sessionmaker_factory


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.db")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init").set_defaults(func=cmd_init)

    p_reset = sub.add_parser("reset")
    p_reset.add_argument("--yes", action="store_true", help="confirm destructive reset")
    p_reset.set_defaults(func=cmd_reset)

    sub.add_parser("tables").set_defaults(func=cmd_tables)
    sub.add_parser("counts").set_defaults(func=cmd_counts)

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
