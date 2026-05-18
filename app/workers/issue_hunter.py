"""Issue Hunter worker.

Pipeline per run:
    1. Build search queries from HunterConfig (label × language × recency)
    2. For each query, fetch up to N issues via GitHub Search API
    3. Dedupe by issue id
    4. For each candidate:
         a) Skip if too old (issue_freshness gate)
         b) Fetch full issue + parent repo (cached) and compute health
         c) Skip if repo health < threshold
         d) Estimate difficulty (heuristic, LLM fallback)
         e) Generate embedding via Voyage (batched at end)
         f) Upsert repo, issue, and vector
    5. Return HuntStats

This is a stand-alone worker — no FastAPI dependency. It runs as a script
or a scheduled job in later batches.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.hunter.difficulty import estimate_difficulty
from app.agents.hunter.health import (
    is_recent_enough,
    repo_health_score,
)
from app.agents.hunter.queries import build_gsoc_queries, build_queries
from app.agents.hunter.schemas import HunterConfig, HuntStats, IssueCandidate
from app.db.models import Issue, Repo
from app.db.vector import insert_vector
from app.gsoc.queries import find_orgs_for_languages, list_active_orgs
from app.tools.github import GitHubClient
from app.tools.github.models import Issue as GHIssue
from app.tools.github.models import Repo as GHRepo

log = structlog.get_logger(__name__)

EMBED_BATCH_SIZE = 32
REPO_HEALTH_THRESHOLD = 0.30


# ---------------------------------------------------------------------------
# Embedding text construction
# ---------------------------------------------------------------------------

def issue_embed_text(title: str, body: str | None, labels: list[str]) -> str:
    """Compact text representation an embedding model can score."""
    parts = [f"TITLE: {title}"]
    if labels:
        parts.append(f"LABELS: {', '.join(labels)}")
    if body:
        # Cap body to ~2000 chars; embeddings care about semantics, not volume.
        snippet = body.strip()[:2000]
        parts.append(f"BODY: {snippet}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def upsert_repo(session: Session, gh_repo: GHRepo) -> Repo:
    """Insert or update a repo row from a GitHub API model."""
    existing = session.execute(
        select(Repo).where(Repo.id == gh_repo.id)
    ).scalar_one_or_none()

    fields: dict[str, Any] = {
        "id": gh_repo.id,
        "full_name": gh_repo.full_name,
        "name": gh_repo.name,
        "description": gh_repo.description,
        "language": gh_repo.language,
        "stargazers_count": gh_repo.stargazers_count,
        "forks_count": gh_repo.forks_count,
        "open_issues_count": gh_repo.open_issues_count,
        "archived": gh_repo.archived,
        "fork": gh_repo.fork,
        "pushed_at": gh_repo.pushed_at,
        "default_branch": gh_repo.default_branch,
        "html_url": gh_repo.html_url,
        "topics": gh_repo.topics,
        "health_score": repo_health_score(
            stars=gh_repo.stargazers_count,
            pushed_at=gh_repo.pushed_at,
            open_issues_count=gh_repo.open_issues_count,
            forks_count=gh_repo.forks_count,
            archived=gh_repo.archived,
        ),
    }

    if existing is None:
        existing = Repo(**fields)
        session.add(existing)
    else:
        for k, v in fields.items():
            if k != "id":
                setattr(existing, k, v)
    session.flush()
    return existing


def upsert_issue(
    session: Session,
    repo_id: int,
    gh_issue: GHIssue,
    *,
    difficulty: str | None,
) -> Issue:
    existing = session.execute(
        select(Issue).where(Issue.id == gh_issue.id)
    ).scalar_one_or_none()

    fields: dict[str, Any] = {
        "id": gh_issue.id,
        "repo_id": repo_id,
        "number": gh_issue.number,
        "title": gh_issue.title,
        "body": gh_issue.body,
        "state": gh_issue.state,
        "labels": [lbl.name for lbl in gh_issue.labels],
        "comments_count": gh_issue.comments,
        "html_url": gh_issue.html_url,
        "issue_created_at": gh_issue.created_at,
        "issue_updated_at": gh_issue.updated_at,
        "difficulty": difficulty,
    }

    if existing is None:
        existing = Issue(**fields)
        session.add(existing)
    else:
        for k, v in fields.items():
            if k != "id":
                setattr(existing, k, v)
    session.flush()
    return existing


def candidate_from_search_issue(gh_issue: GHIssue) -> IssueCandidate | None:
    """Convert a search-result Issue into our internal candidate type.

    Returns None if the issue doesn't have a repo_url we can parse.
    """
    repo = gh_issue.repo_full_name
    if not repo:
        return None
    return IssueCandidate(
        repo_full_name=repo,
        issue_number=gh_issue.number,
        issue_id=gh_issue.id,
        title=gh_issue.title,
        body=gh_issue.body,
        labels=[lbl.name for lbl in gh_issue.labels],
        html_url=gh_issue.html_url,
        issue_created_at=gh_issue.created_at,
        issue_updated_at=gh_issue.updated_at,
    )


# ---------------------------------------------------------------------------
# GSoC mode helpers
# ---------------------------------------------------------------------------

# Upper bound on orgs we'll query. With ~6 labels per org, this keeps the
# total query count under GitHub's 30 searches/minute comfortably.
GSOC_MAX_ORGS = 25


def _resolve_gsoc_org_logins(session: Session, cfg: HunterConfig) -> list[str]:
    """Pick GSoC org github_logins to scope the hunt against.

    If the config has user languages, narrow to orgs whose primary_languages
    overlap. Otherwise return all active orgs. Orgs without a github_login
    (e.g., R Project) can't be queried by GitHub Search, so they're dropped.
    """
    if cfg.languages:
        orgs = find_orgs_for_languages(
            session,
            cfg.languages,
            recent_years=cfg.gsoc_recent_years,
            limit=GSOC_MAX_ORGS,
        )
    else:
        orgs = list_active_orgs(
            session,
            recent_years=cfg.gsoc_recent_years,
            limit=GSOC_MAX_ORGS,
        )
    return [o.github_login for o in orgs if o.github_login]


# ---------------------------------------------------------------------------
# Search + dedup
# ---------------------------------------------------------------------------

async def collect_candidates(
    gh: GitHubClient,
    config: HunterConfig,
    *,
    gsoc_org_logins: list[str] | None = None,
) -> tuple[list[IssueCandidate], int]:
    """Run all search queries; return deduped candidates + total query count.

    In GSoC mode, `gsoc_org_logins` drives the search (caller resolves
    these from the gsoc_orgs table). In general mode it's ignored.
    """
    if config.mode == "gsoc":
        queries = build_gsoc_queries(
            org_logins=gsoc_org_logins or [],
            labels=config.labels,
            updated_since_days=config.updated_since_days,
            min_stars=config.min_stars,
        )
    else:
        queries = build_queries(
            languages=config.languages,
            labels=config.labels,
            updated_since_days=config.updated_since_days,
            min_stars=config.min_stars,
        )

    seen_ids: set[int] = set()
    candidates: list[IssueCandidate] = []

    for query in queries:
        if len(candidates) >= config.max_total_issues:
            break
        try:
            result = await gh.search_issues(
                query, per_page=min(100, config.max_issues_per_query)
            )
        except Exception as e:
            log.warning("search_failed", query=query, error=str(e))
            continue

        for issue in result.items:
            cand = candidate_from_search_issue(issue)
            if cand is None or cand.issue_id in seen_ids:
                continue
            if not is_recent_enough(issue_created_at=cand.issue_created_at):
                continue
            seen_ids.add(cand.issue_id)
            candidates.append(cand)
            if len(candidates) >= config.max_total_issues:
                break

    return candidates, len(queries)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

async def hunt(
    *,
    gh: GitHubClient,
    router,
    embedder,  # VoyageClient or any object exposing async embed([...])
    session: Session,
    config: HunterConfig | None = None,
) -> HuntStats:
    cfg = config or HunterConfig()
    stats = HuntStats(started_at=datetime.now(UTC).replace(tzinfo=None))

    log.info("hunt_starting", config=cfg.model_dump())

    gsoc_org_logins: list[str] = []
    if cfg.mode == "gsoc":
        gsoc_org_logins = _resolve_gsoc_org_logins(session, cfg)
        log.info("hunt_gsoc_mode", org_count=len(gsoc_org_logins))
        if not gsoc_org_logins:
            log.warning(
                "hunt_gsoc_no_orgs_resolved",
                hint="run `python -m app.db seed-gsoc` and/or `scrape-gsoc`",
            )

    candidates, query_count = await collect_candidates(
        gh, cfg, gsoc_org_logins=gsoc_org_logins
    )
    stats.queries_executed = query_count
    stats.issues_seen = len(candidates)
    log.info("hunt_candidates_collected", count=len(candidates))

    # Group candidates by repo so we fetch each repo's metadata only once.
    repos_by_name: dict[str, GHRepo] = {}
    kept: list[tuple[IssueCandidate, Repo]] = []

    for cand in candidates:
        if cand.repo_full_name not in repos_by_name:
            try:
                gh_repo = await gh.get_repo(cand.repo_full_name)
            except Exception as e:
                log.warning(
                    "repo_fetch_failed", repo=cand.repo_full_name, error=str(e)
                )
                stats.errors += 1
                continue
            repos_by_name[cand.repo_full_name] = gh_repo
        gh_repo = repos_by_name[cand.repo_full_name]

        repo_row = upsert_repo(session, gh_repo)
        if (repo_row.health_score or 0.0) < REPO_HEALTH_THRESHOLD:
            continue
        kept.append((cand, repo_row))

    stats.issues_kept = len(kept)

    # Difficulty + persist issue
    persisted_issues: list[tuple[Issue, IssueCandidate]] = []
    for cand, repo_row in kept:
        difficulty: str | None = None
        if cfg.enable_difficulty_llm:
            try:
                difficulty = estimate_difficulty(
                    router,
                    title=cand.title,
                    body=cand.body,
                    labels=cand.labels,
                    session=session,
                )
                stats.difficulty_calls += 1
            except Exception as e:
                log.warning("difficulty_failed", issue_id=cand.issue_id, error=str(e))
                stats.errors += 1
                difficulty = None

        # Build a synthetic GHIssue for upsert (search results don't return all fields)
        gh_issue_full = GHIssue(
            id=cand.issue_id,
            number=cand.issue_number,
            title=cand.title,
            body=cand.body,
            state="open",
            labels=[{"name": lbl} for lbl in cand.labels],
            comments=0,
            html_url=cand.html_url,
            created_at=cand.issue_created_at,
            updated_at=cand.issue_updated_at,
        )
        issue_row = upsert_issue(
            session, repo_row.id, gh_issue_full, difficulty=difficulty
        )
        persisted_issues.append((issue_row, cand))
        stats.issues_persisted += 1

    session.commit()

    # Embeddings (batched across all kept issues)
    if cfg.enable_embeddings and persisted_issues:
        texts = [
            issue_embed_text(c.title, c.body, c.labels)
            for _, c in persisted_issues
        ]
        try:
            result = await embedder.embed(texts, input_type="document")
            for (issue_row, _), vector in zip(
                persisted_issues, result.embeddings, strict=True
            ):
                insert_vector(session, "issues_vec", issue_row.id, vector)
                stats.embeddings_generated += 1
            session.commit()
        except Exception as e:
            log.warning("embedding_failed", count=len(texts), error=str(e))
            stats.errors += 1
            session.rollback()

    stats.finished_at = datetime.now(UTC).replace(tzinfo=None)
    log.info(
        "hunt_finished",
        queries=stats.queries_executed,
        kept=stats.issues_kept,
        persisted=stats.issues_persisted,
        embedded=stats.embeddings_generated,
        errors=stats.errors,
        duration_s=stats.duration_seconds,
    )
    return stats
