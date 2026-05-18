"""Investigator orchestrator.

Flow:
    1. Create Investigation row (status=running)
    2. Fetch (in parallel): issue, comments, repo tree, recent commits
    3. Run Issue Analyst (LLM)
    4. Run Repo Mapper (LLM, needs Issue Analyst output)
    5. Run History Detective (LLM)
    6. Run Synthesizer (LLM, needs all three above)
    7. Persist report + close investigation row
    8. Return InvestigationResult

Step 2 is parallel (cheap I/O). Steps 3-6 are sequential — they have
data dependencies, and parallelizing LLM calls is a Batch 9 problem
(needs asyncio.to_thread).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.investigator.history_detective import run_history_detective
from app.agents.investigator.issue_analyst import run_issue_analyst
from app.agents.investigator.repo_mapper import run_repo_mapper
from app.agents.investigator.schemas import (
    InvestigationReport,
    InvestigationResult,
)
from app.agents.investigator.synthesizer import (
    report_to_markdown,
    run_synthesizer,
)
from app.db.models import Investigation, Issue, Repo, User
from app.streaming import publish
from app.tools.github import GitHubClient

log = structlog.get_logger(__name__)

MAX_COMMITS_FOR_HISTORY = 30
MAX_COMMENTS = 30


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _ensure_issue_row(
    session: Session, repo_full_name: str, issue_number: int, gh_issue, gh_repo,
) -> tuple[Repo, Issue]:
    """Make sure repo + issue rows exist so investigations.issue_id FK is valid."""
    repo = session.execute(
        select(Repo).where(Repo.id == gh_repo.id)
    ).scalar_one_or_none()
    if repo is None:
        repo = Repo(
            id=gh_repo.id,
            full_name=gh_repo.full_name,
            name=gh_repo.name,
            description=gh_repo.description,
            language=gh_repo.language,
            stargazers_count=gh_repo.stargazers_count,
            forks_count=gh_repo.forks_count,
            open_issues_count=gh_repo.open_issues_count,
            archived=gh_repo.archived,
            fork=gh_repo.fork,
            pushed_at=gh_repo.pushed_at,
            default_branch=gh_repo.default_branch,
            html_url=gh_repo.html_url,
            topics=gh_repo.topics,
        )
        session.add(repo)
        session.flush()

    issue = session.execute(
        select(Issue).where(Issue.id == gh_issue.id)
    ).scalar_one_or_none()
    if issue is None:
        issue = Issue(
            id=gh_issue.id,
            repo_id=repo.id,
            number=gh_issue.number,
            title=gh_issue.title,
            body=gh_issue.body,
            state=gh_issue.state,
            labels=[lbl.name for lbl in gh_issue.labels],
            comments_count=gh_issue.comments,
            html_url=gh_issue.html_url,
            issue_created_at=gh_issue.created_at,
            issue_updated_at=gh_issue.updated_at,
        )
        session.add(issue)
        session.flush()
    return repo, issue


def _create_investigation_row(
    session: Session,
    user_id: int,
    issue_id: int,
    *,
    investigation_id: str | None = None,
) -> Investigation:
    kwargs: dict = {
        "user_id": user_id,
        "issue_id": issue_id,
        "status": "running",
        "started_at": datetime.now(UTC).replace(tzinfo=None),
    }
    if investigation_id is not None:
        kwargs["id"] = investigation_id
    inv = Investigation(**kwargs)
    session.add(inv)
    session.flush()
    return inv


def _finalize_investigation(
    session: Session,
    inv: Investigation,
    *,
    status: str,
    report_md: str | None,
    error: str | None,
) -> None:
    inv.status = status
    inv.report_md = report_md
    inv.error = error
    inv.completed_at = datetime.now(UTC).replace(tzinfo=None)
    session.commit()


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

async def investigate(
    *,
    user_login: str,
    repo_full_name: str,
    issue_number: int,
    gh: GitHubClient,
    router,
    session: Session,
    investigation_id: str | None = None,
) -> InvestigationResult:
    """Run the full Investigator crew and persist a report.

    If `investigation_id` is provided, the persisted row uses that id
    (lets API callers know the id before the row exists). Otherwise a
    fresh UUID is generated.
    """
    user = session.execute(
        select(User).where(User.github_login == user_login)
    ).scalar_one_or_none()
    if user is None:
        raise ValueError(
            f"User {user_login!r} not found — POST /users to profile them first"
        )

    started = datetime.now(UTC).replace(tzinfo=None)
    log.info(
        "investigation_starting",
        user=user_login, repo=repo_full_name, issue=issue_number,
    )

    # ---- 1. Parallel data gathering ----
    issue_task = gh.get_issue(repo_full_name, issue_number)
    comments_task = gh.get_issue_comments(repo_full_name, issue_number, max_comments=MAX_COMMENTS)
    tree_task = gh.get_repo_tree(repo_full_name)
    commits_task = gh.get_recent_commits(repo_full_name, limit=MAX_COMMITS_FOR_HISTORY)
    repo_task = gh.get_repo(repo_full_name)

    gh_issue, comments, tree, commits, gh_repo = await asyncio.gather(
        issue_task, comments_task, tree_task, commits_task, repo_task,
    )

    # ---- 2. Persist repo + issue + investigation row up front ----
    _, issue_row = _ensure_issue_row(
        session, repo_full_name, issue_number, gh_issue, gh_repo,
    )
    inv = _create_investigation_row(
        session, user.id, issue_row.id, investigation_id=investigation_id,
    )
    inv_id = inv.id
    session.commit()

    publish(inv_id, {
        "type": "investigation_started",
        "investigation_id": inv_id,
        "repo": repo_full_name,
        "issue_number": issue_number,
    })
    publish(inv_id, {"type": "data_fetched", "comments": len(comments), "tree_files": len(tree)})

    try:
        # ---- 3. Issue Analyst ----
        publish(inv_id, {"type": "agent_started", "agent": "issue_analyst"})
        issue_reqs = run_issue_analyst(
            router,
            title=gh_issue.title,
            body=gh_issue.body,
            labels=[lbl.name for lbl in gh_issue.labels],
            comments=comments,
            investigation_id=inv_id,
            session=session,
        )
        publish(inv_id, {"type": "agent_completed", "agent": "issue_analyst"})

        # ---- 4. Repo Mapper (needs Issue Analyst output) ----
        publish(inv_id, {"type": "agent_started", "agent": "repo_mapper"})
        repo_map = run_repo_mapper(
            router,
            repo_full_name=repo_full_name,
            issue_reqs=issue_reqs,
            tree=tree,
            investigation_id=inv_id,
            session=session,
        )
        publish(inv_id, {"type": "agent_completed", "agent": "repo_mapper",
                          "candidate_files": len(repo_map.candidate_files)})

        # ---- 5. History Detective ----
        publish(inv_id, {"type": "agent_started", "agent": "history_detective"})
        history = run_history_detective(
            router,
            commits=commits,
            area_hint=", ".join(issue_reqs.technical_keywords[:5]) or None,
            investigation_id=inv_id,
            session=session,
        )
        publish(inv_id, {"type": "agent_completed", "agent": "history_detective"})

        # ---- 6. Synthesizer ----
        publish(inv_id, {"type": "agent_started", "agent": "synthesizer"})
        report = run_synthesizer(
            router,
            issue_reqs=issue_reqs,
            repo_map=repo_map,
            history=history,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            investigation_id=inv_id,
            session=session,
        )
        publish(inv_id, {"type": "agent_completed", "agent": "synthesizer"})

        markdown = report_to_markdown(
            report=report,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_url=gh_issue.html_url,
        )
        _finalize_investigation(
            session, inv, status="completed", report_md=markdown, error=None,
        )
        publish(inv_id, {
            "type": "investigation_completed",
            "investigation_id": inv_id,
            "effort": report.estimated_effort,
        })
        completed = datetime.now(UTC).replace(tzinfo=None)

        log.info(
            "investigation_completed",
            id=inv_id, repo=repo_full_name, issue=issue_number,
            duration_s=(completed - started).total_seconds(),
        )

        return InvestigationResult(
            investigation_id=inv_id,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_url=gh_issue.html_url,
            status="completed",
            report=report,
            started_at=started,
            completed_at=completed,
            duration_seconds=(completed - started).total_seconds(),
            markdown_report=markdown,
        )

    except Exception as e:
        log.exception("investigation_failed", id=inv_id)
        _finalize_investigation(
            session, inv, status="failed", report_md=None, error=str(e)[:1000],
        )
        publish(inv_id, {
            "type": "investigation_failed",
            "investigation_id": inv_id,
            "error": str(e)[:500],
        })
        completed = datetime.now(UTC).replace(tzinfo=None)
        return InvestigationResult(
            investigation_id=inv_id,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_url=getattr(gh_issue, "html_url", ""),
            status="failed",
            error=str(e),
            started_at=started,
            completed_at=completed,
            duration_seconds=(completed - started).total_seconds(),
        )


def empty_report_for_fallback(issue_summary: str) -> InvestigationReport:
    """Convenience for tests / fallback paths."""
    return InvestigationReport(
        issue_summary=issue_summary,
        suggested_approach="(no analysis available)",
        estimated_effort="few-hours",
    )
