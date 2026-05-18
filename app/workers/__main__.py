"""Workers CLI.

Usage:
    uv run python -m app.workers hunt                                   # general mode
    uv run python -m app.workers hunt --languages python,go --max 50
    uv run python -m app.workers hunt --mode gsoc                       # GSoC orgs only
    uv run python -m app.workers hunt --mode gsoc --languages python    # GSoC + lang filter
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from app.agents.hunter.schemas import HunterConfig
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import get_session, init_db
from app.llm import build_router
from app.tools.embedder import make_embedder
from app.tools.github import GitHubClient
from app.workers.issue_hunter import hunt


async def cmd_hunt(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print("ERROR: No LLM provider key set (Gemini/Groq)", file=sys.stderr)
        return 1
    if not settings.embedder_ready:
        print(
            f"ERROR: embedder backend {settings.embedder_backend!r} not ready",
            file=sys.stderr,
        )
        return 1

    init_db()
    languages = args.languages.split(",") if args.languages else None

    if args.mode == "gsoc":
        # Looser defaults — GSoC orgs include smaller research projects
        # with fewer stars, and issues stay open longer waiting for
        # student contributors.
        cfg_kwargs: dict = dict(
            mode="gsoc",
            min_stars=10,
            updated_since_days=60,
            max_total_issues=args.max,
        )
        if languages is not None:
            cfg_kwargs["languages"] = languages
        # In gsoc mode with no language filter, the user is asking
        # "show me everything from GSoC orgs" — keep the default list
        # since it's used only for downstream language-aware features
        # (it doesn't widen the search here).
        config = HunterConfig(**cfg_kwargs)
    else:
        config = HunterConfig(
            mode="general",
            languages=languages if languages is not None else HunterConfig().languages,
            max_total_issues=args.max,
        )

    router = build_router()

    async with (
        GitHubClient(token=settings.github_token) as gh,
        make_embedder() as embedder,
    ):
        with get_session() as session:
            stats = await hunt(
                gh=gh, router=router, embedder=embedder,
                session=session, config=config,
            )

    print()
    print(f"Queries executed:      {stats.queries_executed}")
    print(f"Issues seen:           {stats.issues_seen}")
    print(f"Issues kept:           {stats.issues_kept}")
    print(f"Issues persisted:      {stats.issues_persisted}")
    print(f"Embeddings generated:  {stats.embeddings_generated}")
    print(f"Difficulty LLM calls:  {stats.difficulty_calls}")
    print(f"Errors:                {stats.errors}")
    print(f"Duration:              {stats.duration_seconds:.1f}s")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.workers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hunt = sub.add_parser("hunt")
    p_hunt.add_argument(
        "--mode", choices=["general", "gsoc"], default="general",
        help="general (cross-GitHub) or gsoc (only GSoC-listed orgs)",
    )
    p_hunt.add_argument("--languages", help="Comma-separated languages (default: built-in set)")
    p_hunt.add_argument("--max", type=int, default=50, help="Max total issues to keep")
    p_hunt.set_defaults(func=cmd_hunt)

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
