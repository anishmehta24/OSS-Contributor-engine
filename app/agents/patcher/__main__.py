"""Patch Writer CLI — full end-to-end pipeline against a real GitHub issue.

    uv run python -m app.agents.patcher acme/widget 42
    uv run python -m app.agents.patcher acme/widget 42 --max-files 3
    uv run python -m app.agents.patcher acme/widget 42 --keep-workspace
    uv run python -m app.agents.patcher acme/widget 42 --json

Steps:
  1. Fetch the issue via GitHub API
  2. Clone the repo into a fresh sandbox workspace
  3. Run the Code Explorer to pick candidate files
  4. Hand those to the Patch Writer
  5. Print the resulting unified diff (or a clear failure reason)

This is the first batch where you can see the v3 pipeline as a single
sequential demo: issue text in → real diff out.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.agents.explorer import explore
from app.agents.patcher import write_patch
from app.core.config import settings
from app.core.logging import configure_logging
from app.llm import build_router
from app.sandbox import Workspace
from app.tools.github import GitHubClient


def _ascii(s: str) -> str:
    return s.encode("ascii", errors="replace").decode("ascii")


async def cmd_patch(args: argparse.Namespace) -> int:
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set in .env", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print("ERROR: No LLM provider key set (GEMINI/GROQ)", file=sys.stderr)
        return 1

    router = build_router()

    # 1. Fetch issue
    async with GitHubClient(token=settings.github_token) as gh:
        try:
            issue = await gh.get_issue(args.repo, args.issue_number)
        except Exception as e:
            print(f"ERROR fetching {args.repo}#{args.issue_number}: {e}", file=sys.stderr)
            return 1

    title = issue.title
    body = issue.body or ""
    labels = [lbl.name for lbl in issue.labels]

    print(f"\n=== {args.repo}#{args.issue_number} ===")
    print(f"Title: {_ascii(title)}")
    if labels:
        print(f"Labels: {', '.join(labels)}")

    # 2. Clone
    inv_id = f"patch-{uuid.uuid4().hex[:8]}"
    ws = Workspace.create(inv_id)
    try:
        print(f"\n[1/3] cloning {args.repo}...", flush=True)
        try:
            repo_dir = ws.clone(args.repo)
        except Exception as e:
            print(f"ERROR cloning {args.repo}: {e}", file=sys.stderr)
            return 1

        # 3. Explore
        print(f"[2/3] running Code Explorer (max {args.max_files} files)...", flush=True)
        exploration = await explore(
            repo=args.repo,
            repo_path=repo_dir,
            issue_title=title,
            issue_body=body,
            issue_labels=labels,
            router=router,
            max_candidates=args.max_files,
        )
        if not exploration.candidates:
            print("\n(explorer found no candidate files — can't generate a patch)")
            return 2

        print(f"      found {len(exploration.candidates)} candidate(s):")
        for c in exploration.candidates:
            print(f"        - [{c.confidence:.2f}] {c.path}")

        # 4. Patch
        print("\n[3/3] running Patch Writer...", flush=True)
        result = await write_patch(
            repo=args.repo,
            repo_path=repo_dir,
            issue_title=title,
            issue_body=body,
            issue_labels=labels,
            candidates=exploration.candidates,
            router=router,
        )

        # 5. Print
        if args.json:
            # Don't include the diff in JSON — readers usually want it
            # rendered separately. Print metadata only.
            print(result.model_dump_json(
                exclude={"unified_diff"}, indent=2,
            ))
            print("\n--- unified_diff (raw) ---")
            print(result.unified_diff)
        else:
            _print_human(result)
        return 0 if result.success else 3
    finally:
        if not args.keep_workspace:
            ws.cleanup()
        else:
            print(f"\n(workspace kept at {ws.host_path})", file=sys.stderr)


def _print_human(result) -> None:
    print(
        f"\n--- Patch Writer result ---\n"
        f"success:    {result.success}\n"
        f"confidence: {result.confidence:.2f}\n"
        f"attempted:  {result.edits_attempted} edits\n"
        f"applied:    {len(result.edits_applied)} edits",
    )
    if result.summary:
        print(f"summary:    {_ascii(result.summary)}")
    if result.error:
        print(f"\nERROR: {_ascii(result.error)}")

    if result.edits_applied:
        print("\nApplied edits:")
        for e in result.edits_applied:
            kind = "NEW " if e.new_file else "EDIT"
            print(
                f"  [{kind}] {e.path}  "
                f"(+{e.bytes_added}B / -{e.bytes_removed}B)",
            )
            if e.explanation:
                print(f"         why: {_ascii(e.explanation)}")

    if result.unified_diff:
        print("\n--- unified diff ---")
        print(result.unified_diff)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.agents.patcher")
    parser.add_argument("repo", help="owner/name on GitHub")
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--max-files", type=int, default=5,
        help="max candidate files to consider (default 5)",
    )
    parser.add_argument(
        "--keep-workspace", action="store_true",
        help="don't clean up the workspace dir on exit (for debugging)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON result")
    return parser


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(cmd_patch(args))


if __name__ == "__main__":
    sys.exit(main())
