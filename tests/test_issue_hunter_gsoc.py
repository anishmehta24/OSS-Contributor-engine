"""Tests for GSoC mode in the Issue Hunter (Batch 19)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.hunter.queries import build_gsoc_queries
from app.agents.hunter.schemas import HunterConfig
from app.db.models import GsocOrg
from app.tools.github.models import Issue as GHIssue
from app.tools.github.models import IssueLabel, SearchResult
from app.tools.github.models import Repo as GHRepo
from app.workers.issue_hunter import (
    GSOC_MAX_ORGS,
    _resolve_gsoc_org_logins,
    collect_candidates,
    hunt,
)

NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# build_gsoc_queries
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_gsoc_queries_one_per_org_label_pair():
    queries = build_gsoc_queries(
        org_logins=["apache", "mozilla"],
        labels=["good first issue", "help wanted"],
    )
    assert len(queries) == 2 * 2


@pytest.mark.unit
def test_build_gsoc_queries_includes_user_qualifier():
    queries = build_gsoc_queries(["apache"], labels=["good first issue"])
    assert len(queries) == 1
    q = queries[0]
    assert "user:apache" in q
    assert 'label:"good first issue"' in q
    assert "language:" not in q  # GSoC mode drops language qualifier


@pytest.mark.unit
def test_build_gsoc_queries_skips_falsy_logins():
    queries = build_gsoc_queries(
        ["apache", "", None, "mozilla"], labels=["help wanted"]
    )
    user_clauses = [q for q in queries if "user:" in q]
    assert len(user_clauses) == 2
    assert any("user:apache" in q for q in queries)
    assert any("user:mozilla" in q for q in queries)


@pytest.mark.unit
def test_build_gsoc_queries_honors_min_stars_and_recency():
    queries = build_gsoc_queries(
        ["apache"],
        labels=["x"],
        min_stars=5,
        updated_since_days=90,
    )
    expected_cutoff = (datetime.utcnow() - timedelta(days=90)).date().isoformat()
    assert "stars:>5" in queries[0]
    assert f"updated:>={expected_cutoff}" in queries[0]


@pytest.mark.unit
def test_build_gsoc_queries_empty_input():
    assert build_gsoc_queries([], labels=["x"]) == []


# ---------------------------------------------------------------------------
# _resolve_gsoc_org_logins (DB integration)
# ---------------------------------------------------------------------------

def _seed_orgs(session, rows):
    for r in rows:
        session.add(GsocOrg(
            slug=r["slug"],
            name=r["slug"].title(),
            github_login=r.get("login"),
            primary_languages=r.get("languages", []),
            topics=r.get("topics", []),
            years_participated=r.get("years", [2025]),
            last_seen_year=max(r.get("years", [2025])),
        ))
    session.commit()


@pytest.mark.unit
def test_resolve_returns_active_orgs_when_no_languages(session):
    _seed_orgs(session, [
        {"slug": "apache", "login": "apache", "years": [2025]},
        {"slug": "old", "login": "old", "years": [2018]},
        {"slug": "mozilla", "login": "mozilla", "years": [2024]},
    ])
    cfg = HunterConfig(mode="gsoc", languages=[])
    logins = _resolve_gsoc_org_logins(session, cfg)
    assert "apache" in logins
    assert "mozilla" in logins
    assert "old" not in logins


@pytest.mark.unit
def test_resolve_filters_by_user_languages(session):
    _seed_orgs(session, [
        {"slug": "py", "login": "py", "languages": ["Python"], "years": [2025]},
        {"slug": "rs", "login": "rs", "languages": ["Rust"], "years": [2025]},
        {"slug": "go", "login": "go", "languages": ["Go"], "years": [2025]},
    ])
    cfg = HunterConfig(mode="gsoc", languages=["Python", "Rust"])
    logins = _resolve_gsoc_org_logins(session, cfg)
    assert set(logins) == {"py", "rs"}


@pytest.mark.unit
def test_resolve_drops_orgs_without_github_login(session):
    _seed_orgs(session, [
        {"slug": "apache", "login": "apache", "years": [2025]},
        {"slug": "r-project", "login": None, "years": [2025]},
    ])
    cfg = HunterConfig(mode="gsoc", languages=[])
    logins = _resolve_gsoc_org_logins(session, cfg)
    assert logins == ["apache"]


@pytest.mark.unit
def test_resolve_caps_at_gsoc_max_orgs(session):
    _seed_orgs(session, [
        {"slug": f"o{i}", "login": f"o{i}", "years": [2025]}
        for i in range(GSOC_MAX_ORGS + 5)
    ])
    cfg = HunterConfig(mode="gsoc", languages=[])
    logins = _resolve_gsoc_org_logins(session, cfg)
    assert len(logins) == GSOC_MAX_ORGS


# ---------------------------------------------------------------------------
# collect_candidates: routing on mode
# ---------------------------------------------------------------------------

class _CountingGH:
    """Records every query string that hits search_issues."""
    def __init__(self, items: list[GHIssue]):
        self.queries: list[str] = []

        async def _search(query, *, sort="updated", order="desc", per_page=30, page=1):
            self.queries.append(query)
            return SearchResult[GHIssue](
                total_count=len(items), incomplete_results=False, items=items
            )

        self.search_issues = AsyncMock(side_effect=_search)


@pytest.mark.unit
async def test_collect_candidates_uses_org_queries_in_gsoc_mode():
    gh = _CountingGH(items=[])
    cfg = HunterConfig(mode="gsoc", labels=["help wanted"])
    _, query_count = await collect_candidates(
        gh, cfg, gsoc_org_logins=["apache", "mozilla"]
    )
    assert query_count == 2
    assert all("user:apache" in q or "user:mozilla" in q for q in gh.queries)
    assert all("language:" not in q for q in gh.queries)


@pytest.mark.unit
async def test_collect_candidates_gsoc_with_no_orgs_runs_zero_queries():
    gh = _CountingGH(items=[])
    cfg = HunterConfig(mode="gsoc")
    _, query_count = await collect_candidates(gh, cfg, gsoc_org_logins=[])
    assert query_count == 0
    gh.search_issues.assert_not_called()


@pytest.mark.unit
async def test_collect_candidates_general_mode_unchanged():
    """Regression — general-mode behavior must not depend on gsoc_org_logins."""
    gh = _CountingGH(items=[])
    cfg = HunterConfig(mode="general", languages=["python"], labels=["bug"])
    _, query_count = await collect_candidates(gh, cfg, gsoc_org_logins=["apache"])
    assert query_count == 1
    assert "language:python" in gh.queries[0]
    assert "user:apache" not in gh.queries[0]


# ---------------------------------------------------------------------------
# End-to-end hunt(mode="gsoc")
# ---------------------------------------------------------------------------

def _gh_issue(id_, repo_full):
    return GHIssue(
        id=id_, number=id_, title=f"issue {id_}", state="open",
        labels=[IssueLabel(name="good first issue")],
        html_url=f"https://github.com/{repo_full}/issues/{id_}",
        created_at=NOW - timedelta(days=1),
        updated_at=NOW,
        repository_url=f"https://api.github.com/repos/{repo_full}",
    )


def _gh_repo(id_, full):
    return GHRepo(
        id=id_, full_name=full, name=full.split("/", 1)[1],
        description="x", language="Python",
        stargazers_count=500, forks_count=10,
        open_issues_count=5, archived=False, fork=False,
        pushed_at=NOW - timedelta(days=2),
        default_branch="main", html_url=f"https://github.com/{full}",
        topics=[],
    )


class _GsocFakeGH:
    def __init__(self, by_query: dict[str, list[GHIssue]], repos: dict[str, GHRepo]):
        self.queries_seen: list[str] = []

        async def _search(query, *, sort="updated", order="desc", per_page=30, page=1):
            self.queries_seen.append(query)
            # Return issues only if the query mentions a known org.
            items: list[GHIssue] = []
            for login, issues in by_query.items():
                if f"user:{login}" in query:
                    items.extend(issues)
                    break
            return SearchResult[GHIssue](
                total_count=len(items), incomplete_results=False, items=items
            )

        async def _get_repo(full_name):
            return repos[full_name]

        self.search_issues = AsyncMock(side_effect=_search)
        self.get_repo = AsyncMock(side_effect=_get_repo)


class _StubRouter:
    model_list = [{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}]

    def completion(self, **_):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"difficulty":"easy"}'))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            _hidden_params={"response_cost": 0.0001},
        )


@pytest.mark.unit
async def test_hunt_gsoc_mode_with_seeded_orgs(session):
    _seed_orgs(session, [
        {"slug": "apache", "login": "apache", "languages": ["Python"], "years": [2025]},
        {"slug": "mozilla", "login": "mozilla", "languages": ["Rust"], "years": [2025]},
    ])
    gh = _GsocFakeGH(
        by_query={
            "apache": [_gh_issue(1, "apache/airflow")],
            "mozilla": [_gh_issue(2, "mozilla/servo")],
        },
        repos={
            "apache/airflow": _gh_repo(101, "apache/airflow"),
            "mozilla/servo": _gh_repo(102, "mozilla/servo"),
        },
    )
    cfg = HunterConfig(
        mode="gsoc",
        labels=["good first issue"],
        languages=[],  # no language filter → both orgs
        enable_embeddings=False,
        enable_difficulty_llm=False,
    )
    stats = await hunt(
        gh=gh, router=_StubRouter(), embedder=None,
        session=session, config=cfg,
    )
    # 2 orgs × 1 label = 2 queries
    assert stats.queries_executed == 2
    assert stats.issues_persisted == 2
    # All queries used the user: qualifier, none used language:
    assert all("user:" in q for q in gh.queries_seen)
    assert all("language:" not in q for q in gh.queries_seen)


@pytest.mark.unit
async def test_hunt_gsoc_mode_with_language_filter(session):
    _seed_orgs(session, [
        {"slug": "apache", "login": "apache", "languages": ["Python"], "years": [2025]},
        {"slug": "mozilla", "login": "mozilla", "languages": ["Rust"], "years": [2025]},
        {"slug": "go-org", "login": "go-org", "languages": ["Go"], "years": [2025]},
    ])
    gh = _GsocFakeGH(by_query={"apache": [_gh_issue(1, "apache/airflow")]},
                     repos={"apache/airflow": _gh_repo(101, "apache/airflow")})
    cfg = HunterConfig(
        mode="gsoc", languages=["Python"], labels=["good first issue"],
        enable_embeddings=False, enable_difficulty_llm=False,
    )
    stats = await hunt(
        gh=gh, router=_StubRouter(), embedder=None,
        session=session, config=cfg,
    )
    # Only the Python-matching org → 1 query
    assert stats.queries_executed == 1
    assert "user:apache" in gh.queries_seen[0]
    assert stats.issues_persisted == 1


@pytest.mark.unit
async def test_hunt_gsoc_mode_with_empty_db_runs_zero_queries(session):
    # No orgs seeded → resolver returns []
    gh = _GsocFakeGH(by_query={}, repos={})
    cfg = HunterConfig(
        mode="gsoc", languages=["Python"], labels=["good first issue"],
        enable_embeddings=False, enable_difficulty_llm=False,
    )
    stats = await hunt(
        gh=gh, router=_StubRouter(), embedder=None,
        session=session, config=cfg,
    )
    assert stats.queries_executed == 0
    assert stats.issues_persisted == 0
    gh.search_issues.assert_not_called()
