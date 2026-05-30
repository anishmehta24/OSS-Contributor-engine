"""Pilot CLI — autonomous pilot operations on existing investigations.

    # Run the full Explorer + Reviewer loop for an investigation, persisting
    # the PilotRun row:
    uv run python -m app.pilot run <investigation-uuid>

    # Push the accepted diff for a pilot to the user's GitHub fork:
    uv run python -m app.pilot push <pilot-uuid>

    # Open a draft PR upstream from the pushed branch:
    uv run python -m app.pilot pr <pilot-uuid>

    # Show the latest PilotRun row for an investigation (or by pilot id):
    uv run python -m app.pilot show <investigation-uuid>
    uv run python -m app.pilot show --by-pilot-id <pilot-uuid>
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.models import Investigation, PilotRun
from app.db.session import get_session, sessionmaker_factory
from app.llm import build_router
from app.pilot import (
    PilotConfig,
    open_pilot_pr,
    push_pilot_branch,
    run_pilot,
)
from app.sandbox import docker_available


def _ascii(s: str | None) -> str:
    return (s or "").encode("ascii", errors="replace").decode("ascii")


# ---------------------------------------------------------------------------
# `run` — execute the pilot loop
# ---------------------------------------------------------------------------

async def cmd_run(args: argparse.Namespace) -> int:
    if not docker_available():
        print("ERROR: Docker not available.", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print("ERROR: No LLM provider key set.", file=sys.stderr)
        return 1

    sm = sessionmaker_factory()

    with sm() as session:
        inv = session.get(Investigation, args.investigation_id)
        if inv is None:
            print(f"ERROR: investigation {args.investigation_id!r} not found", file=sys.stderr)
            return 1
        if inv.status != "completed":
            print(
                f"ERROR: investigation status is {inv.status!r}; "
                f"need 'completed' (run the Investigator first)",
                file=sys.stderr,
            )
            return 1

        pilot_id = str(uuid.uuid4())
        session.add(PilotRun(
            id=pilot_id,
            investigation_id=inv.id,
            user_id=inv.user_id,
            status="queued",
        ))
        session.commit()

    print(f"Pilot id: {pilot_id}")
    print(f"Investigation: {args.investigation_id}\n")

    cfg = PilotConfig(
        max_attempts=args.attempts,
        max_files=args.max_files,
        test_timeout_s=args.timeout,
    )

    await run_pilot(
        pilot_id=pilot_id,
        investigation_id=args.investigation_id,
        user_id=inv.user_id,
        llm_router=build_router(),
        session_factory=sm,
        config=cfg,
    )

    return _print_row(pilot_id, by_pilot_id=True)


# ---------------------------------------------------------------------------
# `push` — fork + push the accepted diff
# ---------------------------------------------------------------------------

async def cmd_push(args: argparse.Namespace) -> int:
    sm = sessionmaker_factory()

    with sm() as session:
        pilot = session.get(PilotRun, args.pilot_id)
        if pilot is None:
            print(f"ERROR: pilot {args.pilot_id!r} not found", file=sys.stderr)
            return 1
        if pilot.status != "accepted":
            print(
                f"ERROR: pilot status is {pilot.status!r}; "
                f"can only push 'accepted' pilots",
                file=sys.stderr,
            )
            return 1
        if pilot.pushed_at is not None:
            print(
                f"ERROR: pilot already pushed to {pilot.branch_ref!r} "
                f"at {pilot.pushed_at}; won't clobber",
                file=sys.stderr,
            )
            return 1

    print(f"Pushing pilot {args.pilot_id} to the user's GitHub fork...")
    await push_pilot_branch(pilot_id=args.pilot_id, session_factory=sm)

    return _print_row(args.pilot_id, by_pilot_id=True)


# ---------------------------------------------------------------------------
# `pr` — open a draft PR upstream from the pushed branch
# ---------------------------------------------------------------------------

async def cmd_pr(args: argparse.Namespace) -> int:
    sm = sessionmaker_factory()

    with sm() as session:
        pilot = session.get(PilotRun, args.pilot_id)
        if pilot is None:
            print(f"ERROR: pilot {args.pilot_id!r} not found", file=sys.stderr)
            return 1
        if pilot.status != "accepted":
            print(
                f"ERROR: pilot status is {pilot.status!r}; "
                f"can only open PRs for 'accepted' pilots",
                file=sys.stderr,
            )
            return 1
        if pilot.pushed_at is None or not pilot.branch_ref:
            print(
                "ERROR: pilot hasn't been pushed yet — run `push` first",
                file=sys.stderr,
            )
            return 1
        if pilot.pr_url:
            print(
                f"ERROR: PR already opened at {pilot.pr_url} (#{pilot.pr_number}); "
                f"won't reopen",
                file=sys.stderr,
            )
            return 1

    print(f"Opening draft PR for pilot {args.pilot_id}...")
    await open_pilot_pr(pilot_id=args.pilot_id, session_factory=sm)

    return _print_row(args.pilot_id, by_pilot_id=True)


# ---------------------------------------------------------------------------
# `show` — print latest row
# ---------------------------------------------------------------------------

def cmd_show(args: argparse.Namespace) -> int:
    return _print_row(args.id, by_pilot_id=args.by_pilot_id)


# ---------------------------------------------------------------------------
# Shared printer
# ---------------------------------------------------------------------------

def _print_row(pilot_id_or_inv: str, *, by_pilot_id: bool = False) -> int:
    with get_session() as session:
        if by_pilot_id:
            row = session.get(PilotRun, pilot_id_or_inv)
        else:
            from sqlalchemy import select
            row = session.execute(
                select(PilotRun)
                .where(PilotRun.investigation_id == pilot_id_or_inv)
                .order_by(PilotRun.created_at.desc())
                .limit(1),
            ).scalar_one_or_none()

        if row is None:
            print(f"(no pilot run found for {pilot_id_or_inv})")
            return 1

        print(f"\n--- PilotRun {row.id} ---")
        print(f"status:           {row.status}")
        print(f"investigation:    {row.investigation_id}")
        print(f"attempts:         {row.attempts_made}")
        print(f"accepted_attempt: {row.accepted_attempt_number}")
        print(f"started_at:       {row.started_at}")
        print(f"completed_at:     {row.completed_at}")
        if row.summary:
            print(f"summary:          {_ascii(row.summary)}")
        if row.error:
            print(f"error:            {_ascii(row.error)}")

        # Push fields (Batch 34)
        if row.pushed_at or row.fork_url or row.push_error:
            print()
            print(f"fork_url:         {row.fork_url or '(none)'}")
            print(f"branch_ref:       {row.branch_ref or '(none)'}")
            print(f"pushed_at:        {row.pushed_at}")
            if row.push_error:
                print(f"push_error:       {_ascii(row.push_error)}")

        # PR fields (Batch 35)
        if row.pr_url or row.pr_error:
            print()
            print(f"pr_url:           {row.pr_url or '(none)'}")
            print(f"pr_number:        {row.pr_number}")
            print(f"pr_opened_at:     {row.pr_opened_at}")
            if row.pr_error:
                print(f"pr_error:         {_ascii(row.pr_error)}")

        if row.accepted_diff:
            print(f"\n--- accepted diff ({len(row.accepted_diff)} bytes) ---")
            print(row.accepted_diff[:4000])
            if len(row.accepted_diff) > 4000:
                print("\n...(truncated)")
        return 0 if row.status == "accepted" else 2


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.pilot")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run the autonomous pilot loop for an investigation")
    p_run.add_argument("investigation_id", help="UUID of a completed investigation")
    p_run.add_argument("--attempts", type=int, default=3,
                       help="max patch-test-review iterations (default 3)")
    p_run.add_argument("--max-files", type=int, default=5,
                       help="explorer max candidates (default 5)")
    p_run.add_argument("--timeout", type=int, default=120,
                       help="seconds per test phase (default 120)")
    p_run.set_defaults(func=cmd_run)

    p_push = sub.add_parser("push", help="push an accepted pilot's diff to the user's fork")
    p_push.add_argument("pilot_id", help="UUID of an accepted PilotRun")
    p_push.set_defaults(func=cmd_push)

    p_pr = sub.add_parser("pr", help="open a draft PR upstream from a pushed pilot branch")
    p_pr.add_argument("pilot_id", help="UUID of a pushed PilotRun")
    p_pr.set_defaults(func=cmd_pr)

    p_show = sub.add_parser("show", help="print the latest pilot row for an investigation")
    p_show.add_argument("id", help="investigation id by default; pilot id with --by-pilot-id")
    p_show.add_argument("--by-pilot-id", action="store_true",
                        help="treat the argument as a pilot id (not an investigation id)")
    p_show.set_defaults(func=cmd_show)

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    if asyncio.iscoroutinefunction(args.func):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
