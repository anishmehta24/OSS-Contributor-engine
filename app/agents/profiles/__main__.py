"""CLI: profile a GitHub user, print + persist the result.

Usage:
    uv run python -m app.agents.profiles <github_login>
    uv run python -m app.agents.profiles <github_login> --no-persist   # don't write to DB
    uv run python -m app.agents.profiles <github_login> --pretty       # pretty-print
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.agents.profiles.skill_profiler import profile_user
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import get_session, init_db
from app.llm import build_router
from app.tools.github import GitHubClient


async def _main_async(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set in .env", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print(
            "ERROR: No LLM provider key set. Add GEMINI_API_KEY and/or GROQ_API_KEY to .env.",
            file=sys.stderr,
        )
        return 1

    router = build_router()

    if args.persist:
        init_db()  # ensure schema exists

    async with GitHubClient(token=settings.github_token) as gh:
        if args.persist:
            with get_session() as session:
                profile = await profile_user(args.login, gh=gh, router=router, session=session)
        else:
            profile = await profile_user(args.login, gh=gh, router=router, session=None)

    if args.pretty:
        print(f"\nGitHub:        {profile.github_login}  (id {profile.github_id})")
        print(f"Name:          {profile.name or '(none)'}")
        print(f"Repos analyzed: {profile.repos_analyzed}")
        print(f"\nLanguages:     {', '.join(profile.languages) or '(none)'}")
        print(f"Frameworks:    {', '.join(profile.frameworks) or '(none)'}")
        print(f"Domains:       {', '.join(profile.domains) or '(none)'}")
        print(f"Experience:    {profile.experience_signal or '(unknown)'}")
        print(f"\nSummary:       {profile.summary or '(LLM synthesis failed)'}")
    else:
        print(json.dumps(profile.model_dump(mode="json"), indent=2, default=str))

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.agents.profiles")
    p.add_argument("login", help="GitHub username")
    p.add_argument("--no-persist", dest="persist", action="store_false",
                   help="Don't write to the database")
    p.add_argument("--pretty", action="store_true", help="Human-readable output")
    return p


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
