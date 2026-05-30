"""Code Explorer CLI.

End-to-end run against a real GitHub issue:

    uv run python -m app.agents.explorer acme/widget 42
    uv run python -m app.agents.explorer acme/widget 42 --no-llm
    uv run python -m app.agents.explorer acme/widget 42 --max 5 --json
    uv run python -m app.agents.explorer acme/widget 42 --keep-workspace

Steps:
  1. Fetch the issue via GitHub API (needs GITHUB_TOKEN).
  2. Clone the repo into a temporary sandbox workspace.
  3. Run the Code Explorer.
  4. Print human-readable or JSON output.
  5. Cleanup the workspace (unless --keep-workspace).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.agents.explorer import explore
from app.core.config import settings
from app.core.logging import configure_logging
from app.llm import build_router
from app.sandbox import Workspace
from app.tools.github import GitHubClient


async def cmd_explore(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set in .env", file=sys.stderr)
        return 1

    router = None
    if not args.no_llm:
        if not settings.has_any_llm:
            print(
                "ERROR: No LLM provider key set (GEMINI/GROQ). "
                "Pass --no-llm to skip the LLM rerank step.",
                file=sys.stderr,
            )
            return 1
        router = build_router()

    repo = args.repo
    issue_number = args.issue_number

    # 1. Fetch issue
    async with GitHubClient(token=settings.github_token) as gh:
        try:
            issue = await gh.get_issue(repo, issue_number)
        except Exception as e:
            print(f"ERROR fetching {repo}#{issue_number}: {e}", file=sys.stderr)
            return 1

    title = issue.title
    body = issue.body or ""
    labels = [lbl.name for lbl in issue.labels]

    # 2. Clone into a fresh sandbox workspace
    inv_id = f"explore-{uuid.uuid4().hex[:8]}"
    ws = Workspace.create(inv_id)
    try:
        try:
            repo_dir = ws.clone(repo)
        except Exception as e:
            print(f"ERROR cloning {repo}: {e}", file=sys.stderr)
            return 1

        # 3. Explore
        result = await explore(
            repo=repo,
            repo_path=repo_dir,
            issue_title=title,
            issue_body=body,
            issue_labels=labels,
            router=router,
            max_candidates=args.max,
        )

        # 4. Print
        if args.json:
            print(result.model_dump_json(indent=2))
        else:
            _print_human(result)
        return 0
    finally:
        if not args.keep_workspace:
            ws.cleanup()
        else:
            print(f"\n(workspace kept at {ws.host_path})", file=sys.stderr)


def _print_human(result) -> None:
    # ASCII-only — Windows console defaults to cp1252 and chokes on
    # box-drawing characters / em-dashes.
    def _ascii(s: str) -> str:
        return s.encode("ascii", errors="replace").decode("ascii")

    print(f"\n{result.repo} -- {_ascii(result.issue_title)}")
    print(
        f"scanned={result.files_scanned}  "
        f"pre-ranked={result.files_pre_ranked}  "
        f"llm_rerank={result.used_llm_rerank}  "
        f"elapsed={result.elapsed_s:.2f}s",
    )
    if not result.candidates:
        print("\n(no candidate files found)")
        return
    print(f"\nTop {len(result.candidates)} candidate file(s):\n")
    for i, c in enumerate(result.candidates, start=1):
        bar = "=" * int(round(c.confidence * 10))
        print(f"  {i}. [{c.confidence:.2f}] {bar:<10}  {c.path}")
        if c.reason:
            print(f"        why: {_ascii(c.reason)}")
        if c.signals:
            print(f"        signals: {', '.join(c.signals[:4])}")
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.agents.explorer")
    parser.add_argument("repo", help="owner/name on GitHub")
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--max", type=int, default=8, help="max candidate files to return",
    )
    parser.add_argument(
        "--no-llm", action="store_true",
        help="skip LLM rerank — use deterministic scoring only",
    )
    parser.add_argument(
        "--keep-workspace", action="store_true",
        help="don't clean up the workspace dir on exit (for debugging)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit ExplorationResult as JSON",
    )
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(cmd_explore(args))


if __name__ == "__main__":
    sys.exit(main())
