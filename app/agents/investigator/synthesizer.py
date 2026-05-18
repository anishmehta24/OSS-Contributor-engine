"""Synthesizer: merges the three sub-agent outputs into one report.

This is the most prompt-heavy agent. Other agents extract facts; this one
makes judgments — suggested approach, risks, effort estimate.
"""
from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.agents.investigator.schemas import (
    HistoricalContext,
    InvestigationReport,
    IssueRequirements,
    RepoMap,
)
from app.llm import call_llm

log = structlog.get_logger(__name__)


SYSTEM_PROMPT = """You are writing an investigation report for a developer who
just claimed a GitHub issue and needs to know where to start.

Inputs (from three upstream agents):
- Issue requirements (what the issue asks for)
- Repo map (which files are likely relevant)
- Historical context (recent commit patterns)

Return ONE JSON object:
  "issue_summary":      One paragraph (≤ 4 sentences) restating the issue
  "candidate_files":    Carry forward from repo_map (same shape: path + reason).
                        You may reorder or drop ones that don't fit; you may NOT
                        add files that weren't in the input.
  "suggested_approach": A concrete plan in 3-6 short paragraphs OR a bulleted
                        list (max ~1500 chars). Mention specific files. Mention
                        whether tests should be added.
  "open_questions":     Up to 6 things to ask the maintainer before starting.
                        Include anything important the issue didn't specify.
  "risks":              Up to 6 things that could go sideways. Be specific:
                        "Touching this file may break the migration in PR #123"
                        is good. "Could have bugs" is bad.
  "estimated_effort":   One of "under-1-hour", "few-hours", "weekend", "multi-day"

Rules:
- Be concrete. If you don't know, say "I don't know" — don't bluff.
- If history shows the area was recently refactored, flag that as a risk.
- Don't invent file paths."""


def build_user_message(
    *,
    issue_reqs: IssueRequirements,
    repo_map: RepoMap,
    history: HistoricalContext,
    repo_full_name: str,
    issue_number: int,
) -> str:
    return (
        f"REPO: {repo_full_name}\n"
        f"ISSUE: #{issue_number}\n\n"
        f"=== Issue requirements ===\n"
        f"Summary: {issue_reqs.summary}\n"
        f"Requirements:\n"
        + "\n".join(f"  - {r}" for r in issue_reqs.requirements)
        + "\n\nAcceptance criteria:\n"
        + "\n".join(f"  - {a}" for a in issue_reqs.acceptance_criteria)
        + "\n\nOpen questions:\n"
        + "\n".join(f"  - {q}" for q in issue_reqs.open_questions)
        + "\n\n=== Repo map ===\n"
        f"Repo summary: {repo_map.repo_summary}\n"
        f"Candidate files:\n"
        + "\n".join(f"  - {f.path}: {f.reason}" for f in repo_map.candidate_files)
        + "\n\n=== Historical context ===\n"
        f"Summary: {history.summary}\n"
        f"Recent themes: {', '.join(history.recent_themes) or '(none)'}\n"
        f"Notable commits:\n"
        + "\n".join(f"  - {c}" for c in history.notable_commits)
    )


def run_synthesizer(
    router,
    *,
    issue_reqs: IssueRequirements,
    repo_map: RepoMap,
    history: HistoricalContext,
    repo_full_name: str,
    issue_number: int,
    investigation_id: str | None = None,
    session: Session | None = None,
) -> InvestigationReport:
    user_msg = build_user_message(
        issue_reqs=issue_reqs,
        repo_map=repo_map,
        history=history,
        repo_full_name=repo_full_name,
        issue_number=issue_number,
    )
    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="synthesizer",
        response_model=InvestigationReport,
        investigation_id=investigation_id,
        session=session,
        max_tokens=2000,
    )
    if parsed is None:
        log.warning("synthesizer_parse_failed", repo=repo_full_name, issue=issue_number)
        # Fallback: stitch what we already have so the user gets *something*
        return InvestigationReport(
            issue_summary=issue_reqs.summary,
            candidate_files=repo_map.candidate_files,
            suggested_approach="(synthesis failed — see candidate files and try again)",
            open_questions=issue_reqs.open_questions,
            estimated_effort="few-hours",
        )
    return parsed


def report_to_markdown(
    *,
    report: InvestigationReport,
    repo_full_name: str,
    issue_number: int,
    issue_url: str,
) -> str:
    """Render the InvestigationReport as a human-readable markdown blob."""
    lines: list[str] = []
    lines.append(f"# Investigation: {repo_full_name}#{issue_number}")
    lines.append("")
    lines.append(f"**Issue:** {issue_url}")
    lines.append(f"**Estimated effort:** `{report.estimated_effort}`")
    lines.append("")
    lines.append("## Summary")
    lines.append(report.issue_summary)
    lines.append("")
    if report.candidate_files:
        lines.append("## Files to look at")
        for f in report.candidate_files:
            lines.append(f"- `{f.path}` — {f.reason}")
        lines.append("")
    lines.append("## Suggested approach")
    lines.append(report.suggested_approach or "(none)")
    lines.append("")
    if report.open_questions:
        lines.append("## Open questions for the maintainer")
        for q in report.open_questions:
            lines.append(f"- {q}")
        lines.append("")
    if report.risks:
        lines.append("## Risks")
        for r in report.risks:
            lines.append(f"- {r}")
        lines.append("")
    return "\n".join(lines)
