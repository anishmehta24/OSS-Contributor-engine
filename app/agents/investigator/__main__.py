"""CLI: investigate a single issue end-to-end.

Usage:
    uv run python -m app.agents.investigator <user_login> <owner/repo> <issue_number>

Example:
    uv run python -m app.agents.investigator anishmehta24 fastapi/fastapi 1234
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.agents.investigator.investigator import investigate
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import get_session, init_db
from app.llm import build_router
from app.tools.github import GitHubClient


async def _main_async(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print("ERROR: No LLM provider key set", file=sys.stderr)
        return 1

    init_db()
    router = build_router()

    async with GitHubClient(token=settings.github_token) as gh:
        with get_session() as session:
            result = await investigate(
                user_login=args.user_login,
                repo_full_name=args.repo,
                issue_number=args.issue_number,
                gh=gh, router=router, session=session,
            )

    if args.markdown:
        print(result.markdown_report or "(no report)")
    else:
        print(json.dumps(result.model_dump(mode="json"), indent=2, default=str))

    return 0 if result.status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.agents.investigator")
    parser.add_argument("user_login", help="GitHub username (must be profiled)")
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("issue_number", type=int)
    parser.add_argument("--markdown", action="store_true",
                        help="Print the human-readable markdown report")
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
