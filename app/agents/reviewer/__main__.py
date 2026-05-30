"""Reviewer CLI — the autonomous-pilot end-to-end.

    uv run python -m app.agents.reviewer acme/widget 42
    uv run python -m app.agents.reviewer acme/widget 42 --attempts 5
    uv run python -m app.agents.reviewer acme/widget 42 --max-files 4 --keep-workspace

Flow per run:
    1. Fetch the issue
    2. Clone into a sandbox workspace
    3. Code Explorer picks candidate files
    4. Reviewer loops: Patch Writer -> Test Runner -> decide
    5. Print transcript of all attempts and the final diff

This is the first batch where you see a single command produce a real
multi-iteration LLM-driven attempt at fixing an open-source issue.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.agents.explorer import explore
from app.agents.reviewer import review_and_iterate
from app.core.config import settings
from app.core.logging import configure_logging
from app.llm import build_router
from app.sandbox import SandboxRunner, Workspace, docker_available
from app.tools.github import GitHubClient


def _ascii(s: str) -> str:
    return s.encode("ascii", errors="replace").decode("ascii")


async def cmd_review(args: argparse.Namespace) -> int:
    if not docker_available():
        print("ERROR: Docker not available. Start Docker Desktop.", file=sys.stderr)
        return 1
    if not settings.has_github:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    if not settings.has_any_llm:
        print("ERROR: no LLM provider key set", file=sys.stderr)
        return 1

    router = build_router()

    async with GitHubClient(token=settings.github_token) as gh:
        try:
            issue = await gh.get_issue(args.repo, args.issue_number)
        except Exception as e:
            print(f"ERROR fetching issue: {e}", file=sys.stderr)
            return 1

    title = issue.title
    body = issue.body or ""
    labels = [lbl.name for lbl in issue.labels]

    print(f"\n=== {args.repo}#{args.issue_number} ===")
    print(f"Title: {_ascii(title)}")
    if labels:
        print(f"Labels: {', '.join(labels)}")

    inv_id = f"review-{uuid.uuid4().hex[:8]}"
    ws = Workspace.create(inv_id)
    try:
        print(f"\n[1/3] cloning {args.repo}...", flush=True)
        try:
            repo_dir = ws.clone(args.repo)
        except Exception as e:
            print(f"ERROR cloning: {e}", file=sys.stderr)
            return 1

        print(f"[2/3] exploring (max {args.max_files} candidates)...", flush=True)
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
            print("\n(explorer found no candidates)")
            return 2
        for c in exploration.candidates:
            print(f"        - [{c.confidence:.2f}] {c.path}")

        print(f"\n[3/3] reviewer loop (max {args.attempts} attempts)...", flush=True)
        result = await review_and_iterate(
            repo=args.repo,
            repo_path=repo_dir,
            workspace=ws,
            issue_title=title,
            issue_body=body,
            issue_labels=labels,
            candidates=exploration.candidates,
            router=router,
            max_attempts=args.attempts,
            test_timeout_s=args.timeout,
            sandbox_runner=SandboxRunner(),
        )

        _print_human(result)
        return 0 if result.success else 3
    finally:
        if not args.keep_workspace:
            ws.cleanup()
        else:
            print(f"\n(workspace kept at {ws.host_path})", file=sys.stderr)


def _print_human(result) -> None:
    print(
        f"\n=== Reviewer result ===\n"
        f"success:  {result.success}\n"
        f"summary:  {_ascii(result.summary)}\n"
        f"attempts: {len(result.attempts)}\n"
        f"elapsed:  {result.elapsed_s:.2f}s",
    )

    for a in result.attempts:
        sep = ">" if (
            result.accepted_attempt_number == a.attempt_number
        ) else "-"
        cls = a.test_result.classification if a.test_result else "no_tests"
        print(
            f"\n  {sep} Attempt {a.attempt_number}: "
            f"decision={a.decision}, test={cls}",
        )
        print(f"    patch:  success={a.patch_result.success}, "
              f"confidence={a.patch_result.confidence:.2f}, "
              f"edits={len(a.patch_result.edits_applied)}")
        if a.patch_result.summary:
            print(f"            {_ascii(a.patch_result.summary[:200])}")
        print(f"    reason: {_ascii(a.decision_reason)}")
        if a.patch_result.error:
            print(f"    error:  {_ascii(a.patch_result.error)}")

    if result.success and result.final_diff:
        print("\n--- ACCEPTED DIFF ---\n")
        print(result.final_diff)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.agents.reviewer")
    p.add_argument("repo", help="owner/name on GitHub")
    p.add_argument("issue_number", type=int)
    p.add_argument("--attempts", type=int, default=3,
                   help="max patch-test-review iterations (default 3)")
    p.add_argument("--max-files", type=int, default=5,
                   help="explorer max candidates (default 5)")
    p.add_argument("--timeout", type=int, default=120,
                   help="seconds per test phase (default 120)")
    p.add_argument(
        "--keep-workspace", action="store_true",
        help="don't clean up after running (for debugging)",
    )
    return p


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    return asyncio.run(cmd_review(args))


if __name__ == "__main__":
    sys.exit(main())
