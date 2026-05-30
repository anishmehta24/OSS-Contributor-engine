"""Test Runner CLI — runs the full Explorer → Patcher → Tests pipeline,
or just the test phases against an existing workspace.

    # Full pipeline (issue → clone → explore → patch → test):
    uv run python -m app.agents.test_runner acme/widget 42

    # Skip the LLM stages, just probe an already-cloned repo:
    uv run python -m app.agents.test_runner --workspace .sandbox/inv-abc
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from app.agents.explorer import explore
from app.agents.patcher import write_patch
from app.agents.test_runner import run_tests
from app.core.config import settings
from app.core.logging import configure_logging
from app.llm import build_router
from app.sandbox import SandboxRunner, Workspace, docker_available
from app.tools.github import GitHubClient


def _ascii(s: str) -> str:
    return s.encode("ascii", errors="replace").decode("ascii")


async def cmd_run(args: argparse.Namespace) -> int:
    if not docker_available():
        print("ERROR: Docker not available. Start Docker Desktop.", file=sys.stderr)
        return 1

    # ---- Mode A: probe an existing workspace, skip LLM ----
    if args.workspace:
        from pathlib import Path
        ws_path = Path(args.workspace).resolve()
        if not ws_path.is_dir():
            print(f"ERROR: workspace dir not found: {ws_path}", file=sys.stderr)
            return 1
        # Find the cloned repo dir inside the workspace.
        repo_dirs = [p for p in ws_path.iterdir() if p.is_dir()]
        if not repo_dirs:
            print(f"ERROR: no repo dir in {ws_path}", file=sys.stderr)
            return 1
        # Construct a Workspace handle without recreating the dir.
        ws = Workspace(investigation_id=ws_path.name, host_path=ws_path)
        result = await run_tests(
            ws, repo_dirs[0], runner=SandboxRunner(),
        )
        _print_human(result)
        return _exit_code_for(result.classification)

    # ---- Mode B: full pipeline ----
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

    inv_id = f"runtest-{uuid.uuid4().hex[:8]}"
    ws = Workspace.create(inv_id)
    try:
        print(f"\n[1/4] cloning {args.repo}...", flush=True)
        try:
            repo_dir = ws.clone(args.repo)
        except Exception as e:
            print(f"ERROR cloning: {e}", file=sys.stderr)
            return 1

        print(f"[2/4] exploring (max {args.max_files} candidate files)...", flush=True)
        exploration = await explore(
            repo=args.repo, repo_path=repo_dir,
            issue_title=title, issue_body=body, issue_labels=labels,
            router=router, max_candidates=args.max_files,
        )
        if not exploration.candidates:
            print("\n(explorer found no candidates — can't run a patch test)")
            return 2
        for c in exploration.candidates:
            print(f"        - [{c.confidence:.2f}] {c.path}")

        print("\n[3/4] writing patch...", flush=True)
        patch = await write_patch(
            repo=args.repo, repo_path=repo_dir,
            issue_title=title, issue_body=body, issue_labels=labels,
            candidates=exploration.candidates, router=router,
        )
        print(
            f"      patch: success={patch.success}, confidence={patch.confidence:.2f}, "
            f"{len(patch.edits_applied)} edit(s) applied",
        )
        if not patch.success:
            print(f"      reason: {_ascii(patch.error or '(unknown)')}")
            if not patch.edits_applied:
                # Nothing on disk to test — skip.
                return 3

        changed = [e.path for e in patch.edits_applied]

        print("\n[4/4] running tests in sandbox...", flush=True)
        result = await run_tests(
            ws, repo_dir,
            changed_files=changed,
            runner=SandboxRunner(),
            timeout_s=args.timeout,
        )
        _print_human(result)
        return _exit_code_for(result.classification)
    finally:
        if not args.keep_workspace:
            ws.cleanup()
        else:
            print(f"\n(workspace kept at {ws.host_path})", file=sys.stderr)


def _print_human(result) -> None:
    print(
        f"\n--- Test Runner result ---\n"
        f"language:       {result.language}\n"
        f"classification: {result.classification}\n"
        f"summary:        {_ascii(result.summary)}\n"
        f"duration:       {result.duration_s:.2f}s\n"
        f"phases:         {len(result.phases)}",
    )
    for p in result.phases:
        status = "skipped" if p.skipped else (
            "timeout" if p.timed_out else f"exit {p.exit_code}"
        )
        argv_short = " ".join(p.argv[:4]) + (" ..." if len(p.argv) > 4 else "")
        print(f"\n  [{p.name}] {status}  ({p.duration_s:.2f}s)")
        print(f"    $ {argv_short}")
        if p.stdout.strip():
            print("    stdout:")
            for line in p.stdout.splitlines()[-10:]:
                print(f"      {line}")
        if p.stderr.strip():
            print("    stderr:")
            for line in p.stderr.splitlines()[-10:]:
                print(f"      {line}")
    if result.failure_excerpt:
        print("\n  failure excerpt (for retry feedback):")
        for line in result.failure_excerpt.splitlines()[-15:]:
            print(f"      {line}")


def _exit_code_for(classification: str) -> int:
    return {
        "pass": 0,
        "needs_env": 0,  # not a patch problem, so don't fail the script
        "fail": 1,
        "error": 2,
        "no_project": 3,
    }.get(classification, 4)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.agents.test_runner")
    p.add_argument("repo", nargs="?", help="owner/name on GitHub (mode B)")
    p.add_argument("issue_number", nargs="?", type=int, help="issue number (mode B)")
    p.add_argument(
        "--workspace",
        help="probe an existing workspace dir instead of running the pipeline (mode A)",
    )
    p.add_argument("--max-files", type=int, default=5, help="explorer max candidates")
    p.add_argument("--timeout", type=int, default=120, help="seconds per phase")
    p.add_argument(
        "--keep-workspace", action="store_true",
        help="don't clean up the workspace after running (for debugging)",
    )
    return p


def main() -> int:
    configure_logging()
    args = build_parser().parse_args()
    if not args.workspace and (not args.repo or args.issue_number is None):
        print("ERROR: provide REPO + ISSUE_NUMBER, or --workspace DIR.",
              file=sys.stderr)
        return 1
    return asyncio.run(cmd_run(args))


if __name__ == "__main__":
    sys.exit(main())
