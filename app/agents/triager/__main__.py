"""CLI: rank issues for a profiled user.

Usage:
    uv run python -m app.agents.triager rank <github_login>
    uv run python -m app.agents.triager rank <login> --top 10 --difficulty easy
    uv run python -m app.agents.triager rank <login> --no-explain   # skip LLM
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.agents.triager.triager import rank_for_user
from app.core.config import settings
from app.core.logging import configure_logging
from app.db.session import get_session
from app.llm import build_router
from app.tools.embedder import make_embedder


async def cmd_rank(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    if not settings.embedder_ready:
        print(
            f"ERROR: embedder backend {settings.embedder_backend!r} not ready",
            file=sys.stderr,
        )
        return 1

    router = None
    if args.explain:
        if not settings.has_any_llm:
            print("WARN: No LLM key, --no-explain will be implied", file=sys.stderr)
        else:
            router = build_router()

    async with make_embedder() as embedder:
        with get_session() as session:
            try:
                matches = await rank_for_user(
                    github_login=args.login,
                    session=session,
                    embedder=embedder,
                    router=router,
                    difficulty_pref=args.difficulty,
                    top_n=args.top,
                    explain=args.explain and router is not None,
                )
            except ValueError as e:
                print(f"ERROR: {e}", file=sys.stderr)
                return 1

    if args.pretty:
        if not matches:
            print("No matches. Run the Issue Hunter first to populate candidates.")
            return 0
        for i, m in enumerate(matches, 1):
            print(f"\n[{i}] {m.repo_full_name}#{m.issue_number}  (★{m.stargazers_count})")
            print(f"    {m.title}")
            print(f"    {m.html_url}")
            print(
                f"    score={m.final_score:.3f}  "
                f"skill={m.skill_match:.2f}  health={m.repo_health:.2f}  "
                f"fresh={m.freshness:.2f}  diff={m.difficulty_match:.2f}  "
                f"impact={m.impact:.2f}"
            )
            if m.why_it_fits:
                print(f"    why: {m.why_it_fits}")
    else:
        print(json.dumps([m.model_dump(mode="json") for m in matches], indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.agents.triager")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rank = sub.add_parser("rank")
    p_rank.add_argument("login", help="GitHub username (must be profiled first)")
    p_rank.add_argument("--top", type=int, default=10)
    p_rank.add_argument(
        "--difficulty", choices=["any", "easy", "medium", "hard"], default="any",
    )
    p_rank.add_argument("--no-explain", dest="explain", action="store_false",
                        help="Skip the LLM why-it-fits step")
    p_rank.add_argument("--pretty", action="store_true")
    p_rank.set_defaults(func=cmd_rank)

    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
