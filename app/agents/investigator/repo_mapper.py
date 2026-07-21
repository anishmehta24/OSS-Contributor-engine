"""Repo Mapper: chooses candidate files from a repo's tree for a given issue.

Two-step pipeline:
    1. Filter the raw tree down to "interesting" files (skip lockfiles, vendored
       deps, build artifacts). Pure code, no LLM.
    2. Hand the filtered list (path + size only) to the LLM with the issue
       requirements, ask it to pick the top N candidates and give a reason.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.agents._shared.file_filters import (
    MAX_BLOB_SIZE_BYTES,
    is_interesting_path,
)
from app.agents.investigator.schemas import IssueRequirements, RepoMap
from app.llm import call_llm

log = structlog.get_logger(__name__)

MAX_FILES_FOR_LLM = 200


def filter_tree(tree: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if not path or not is_interesting_path(path):
            continue
        size = entry.get("size", 0) or 0
        if size > MAX_BLOB_SIZE_BYTES:
            continue
        out.append(entry)
    return out[:MAX_FILES_FOR_LLM]


# ---------------------------------------------------------------------------
# LLM step
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are mapping a GitHub repository to find files a developer
would need to read to resolve a specific issue.

Input includes:
- The issue requirements (summary + keywords)
- A filtered list of source files in the repo (path + size)

Return ONE JSON object:
  "repo_summary":    1-2 sentence summary of what this repo does, inferred from
                     the file structure
  "candidate_files": Up to 10 entries, each {"path": "<exact path from list>",
                     "reason": "<one short phrase, max 25 words>"}

Rules:
- Paths must come from the provided list — don't invent files.
- Prefer files whose path mentions the issue's keywords.
- Prefer source files over docs/configs unless the issue is about docs/configs.
- If you can't find any plausible matches, return an empty list.
- No markdown fences in the JSON."""


def build_user_message(
    *,
    issue_reqs: IssueRequirements,
    repo_full_name: str,
    files: list[dict[str, Any]],
) -> str:
    file_lines = "\n".join(
        f"  {f['path']}  ({f.get('size', 0)} bytes)"
        for f in files
    )
    keywords = ", ".join(issue_reqs.technical_keywords[:10]) or "(none extracted)"
    return (
        f"REPO: {repo_full_name}\n\n"
        f"ISSUE SUMMARY:\n{issue_reqs.summary}\n\n"
        f"KEYWORDS: {keywords}\n\n"
        f"REQUIREMENTS:\n"
        + "\n".join(f"  - {r}" for r in issue_reqs.requirements[:8])
        + f"\n\nFILES ({len(files)}):\n{file_lines}"
    )


def run_repo_mapper(
    router,
    *,
    repo_full_name: str,
    issue_reqs: IssueRequirements,
    tree: list[dict[str, Any]],
    investigation_id: str | None = None,
    session: Session | None = None,
) -> RepoMap:
    files = filter_tree(tree)
    if not files:
        log.info("repo_mapper_no_files", repo=repo_full_name)
        return RepoMap(repo_summary="(no inspectable source files found)")

    user_msg = build_user_message(
        issue_reqs=issue_reqs, repo_full_name=repo_full_name, files=files,
    )
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="repo_mapper",
        response_model=RepoMap,
        investigation_id=investigation_id,
        session=session,
        # Headroom so Gemini's thinking tokens don't truncate the JSON.
        max_tokens=2500,
    )
    if parsed is None:
        log.warning("repo_mapper_parse_failed", repo=repo_full_name)
        return RepoMap(repo_summary="(LLM parse failed)")
    return parsed
