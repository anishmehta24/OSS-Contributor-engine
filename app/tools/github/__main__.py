"""Manual-testing CLI for the GitHub client.

Usage:
    uv run python -m app.tools.github get-user torvalds
    uv run python -m app.tools.github get-repo fastapi/fastapi
    uv run python -m app.tools.github search "label:\\"good first issue\\" language:python"
    uv run python -m app.tools.github rate-limit
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.config import settings
from app.core.logging import configure_logging
from app.tools.github import GitHubClient
from app.tools.github.exceptions import GitHubError


async def cmd_get_user(args: argparse.Namespace) -> int:
    async with GitHubClient(token=settings.github_token) as gh:
        user = await gh.get_user(args.login)
        print(json.dumps(user.model_dump(mode="json"), indent=2, default=str))
    return 0


async def cmd_get_repo(args: argparse.Namespace) -> int:
    async with GitHubClient(token=settings.github_token) as gh:
        repo = await gh.get_repo(args.full_name)
        print(json.dumps(repo.model_dump(mode="json"), indent=2, default=str))
    return 0


async def cmd_search(args: argparse.Namespace) -> int:
    async with GitHubClient(token=settings.github_token) as gh:
        result = await gh.search_issues(args.query, per_page=args.limit)
        print(f"Total matches: {result.total_count} (showing {len(result.items)})\n")
        for issue in result.items:
            repo = issue.repo_full_name or "?"
            print(f"  [{repo}#{issue.number}] {issue.title}")
            print(f"    {issue.html_url}")
    return 0


async def cmd_rate_limit(_: argparse.Namespace) -> int:
    async with GitHubClient(token=settings.github_token) as gh:
        data = await gh.rate_limit()
        core = data["resources"]["core"]
        search = data["resources"]["search"]
        print(f"Core:   {core['remaining']}/{core['limit']}")
        print(f"Search: {search['remaining']}/{search['limit']}")
    return 0


async def cmd_get_issue(args: argparse.Namespace) -> int:
    async with GitHubClient(token=settings.github_token) as gh:
        issue = await gh.get_issue(args.full_name, args.number)
        print(json.dumps(issue.model_dump(mode="json"), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.tools.github")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_user = sub.add_parser("get-user")
    p_user.add_argument("login")
    p_user.set_defaults(func=cmd_get_user)

    p_repo = sub.add_parser("get-repo")
    p_repo.add_argument("full_name", help="owner/repo")
    p_repo.set_defaults(func=cmd_get_repo)

    p_search = sub.add_parser("search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.set_defaults(func=cmd_search)

    p_issue = sub.add_parser("get-issue")
    p_issue.add_argument("full_name")
    p_issue.add_argument("number", type=int)
    p_issue.set_defaults(func=cmd_get_issue)

    p_rl = sub.add_parser("rate-limit")
    p_rl.set_defaults(func=cmd_rate_limit)

    return parser


def main() -> int:
    configure_logging()
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set in .env", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(args.func(args))
    except GitHubError as e:
        print(f"GitHub error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
