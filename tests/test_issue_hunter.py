"""End-to-end Issue Hunter tests with mocked GitHub, LLM, and Voyage."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.agents.hunter.schemas import HunterConfig
from app.db.session import VEC_DIM
from app.tools.github.models import (
    Issue as GHIssue,
)
from app.tools.github.models import (
    IssueLabel,
    SearchResult,
)
from app.tools.github.models import (
    Repo as GHRepo,
)
from app.workers.issue_hunter import (
    candidate_from_search_issue,
    hunt,
    issue_embed_text,
    upsert_issue,
    upsert_repo,
)

NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_issue_embed_text_includes_title_labels_body():
    text_blob = issue_embed_text("Fix bug", "Long body here", ["bug", "good first issue"])
    assert "TITLE: Fix bug" in text_blob
    assert "LABELS: bug, good first issue" in text_blob
    assert "BODY: Long body here" in text_blob


@pytest.mark.unit
def test_issue_embed_text_handles_missing_body():
    assert "BODY:" not in issue_embed_text("Fix bug", None, [])


@pytest.mark.unit
def test_candidate_from_search_issue_extracts_repo():
    gh_issue = GHIssue(
        id=1, number=10, title="x", state="open",
        html_url="https://...",
        created_at=NOW, updated_at=NOW,
        repository_url="https://api.github.com/repos/foo/bar",
        labels=[IssueLabel(name="bug")],
    )
    cand = candidate_from_search_issue(gh_issue)
    assert cand is not None
    assert cand.repo_full_name == "foo/bar"
    assert cand.labels == ["bug"]


@pytest.mark.unit
def test_candidate_from_search_issue_returns_none_without_repo_url():
    gh_issue = GHIssue(
        id=1, number=1, title="x", state="open",
        html_url="https://...", created_at=NOW, updated_at=NOW,
    )
    assert candidate_from_search_issue(gh_issue) is None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _make_gh_repo(*, id_: int = 1, full: str = "foo/bar", stars: int = 500,
                  pushed_days_ago: int = 5, archived: bool = False) -> GHRepo:
    return GHRepo(
        id=id_, full_name=full, name=full.split("/", 1)[1],
        description="x", language="Python",
        stargazers_count=stars,
        forks_count=50,
        open_issues_count=20,
        archived=archived, fork=False,
        pushed_at=NOW - timedelta(days=pushed_days_ago),
        default_branch="main",
        html_url=f"https://github.com/{full}",
        topics=[],
    )


@pytest.mark.unit
def test_upsert_repo_creates_then_updates(session):
    repo_a = _make_gh_repo(stars=100, pushed_days_ago=10)
    row_a = upsert_repo(session, repo_a)
    session.commit()
    assert row_a.stargazers_count == 100
    initial_score = row_a.health_score

    # Same id, new stats → update
    repo_b = _make_gh_repo(stars=500, pushed_days_ago=1)
    row_b = upsert_repo(session, repo_b)
    session.commit()
    assert row_b.id == row_a.id  # same row
    assert row_b.stargazers_count == 500
    assert row_b.health_score >= initial_score  # better stars+recency → higher score


@pytest.mark.unit
def test_upsert_issue_creates_with_difficulty(session):
    repo = _make_gh_repo()
    repo_row = upsert_repo(session, repo)
    session.commit()
    gh_issue = GHIssue(
        id=42, number=7, title="t", state="open",
        labels=[IssueLabel(name="bug")],
        html_url="https://...",
        created_at=NOW, updated_at=NOW,
    )
    row = upsert_issue(session, repo_row.id, gh_issue, difficulty="easy")
    session.commit()
    assert row.difficulty == "easy"
    assert row.labels == ["bug"]


# ---------------------------------------------------------------------------
# End-to-end hunt() with mocks
# ---------------------------------------------------------------------------

class _FakeGH:
    def __init__(self, *, issues: list[GHIssue], repos: dict[str, GHRepo]):
        async def _search(query, *, sort="updated", order="desc", per_page=30, page=1):
            return SearchResult[GHIssue](
                total_count=len(issues),
                incomplete_results=False,
                items=issues,
            )

        async def _get_repo(full_name):
            return repos[full_name]

        self.search_issues = AsyncMock(side_effect=_search)
        self.get_repo = AsyncMock(side_effect=_get_repo)


class _FakeRouter:
    def __init__(self, response_json: str):
        self._json = response_json
        self.call_count = 0
        self.model_list = [{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}]

    def completion(self, **_):
        self.call_count += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._json))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=30, completion_tokens=10),
            _hidden_params={"response_cost": 0.0001},
        )


class _FakeVoyage:
    def __init__(self):
        self.embed = AsyncMock(side_effect=self._embed)
        self.embed_called_with: list[list[str]] = []

    async def _embed(self, texts, *, input_type="document"):
        self.embed_called_with.append(list(texts))
        return SimpleNamespace(
            embeddings=[[float(i % 10) / 10.0] * VEC_DIM for i in range(len(texts))],
            model="voyage-3-large",
            total_tokens=len(texts) * 10,
        )


@pytest.mark.unit
async def test_hunt_end_to_end_persists_issues_and_vectors(session):
    # Two repos, one issue each — both healthy.
    issues = [
        GHIssue(
            id=1001, number=1, title="Fix typo in README", state="open",
            labels=[IssueLabel(name="good first issue")],
            html_url="https://github.com/acme/web/issues/1",
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=1),
            repository_url="https://api.github.com/repos/acme/web",
        ),
        GHIssue(
            id=2002, number=5, title="Add metrics endpoint", state="open",
            labels=[IssueLabel(name="help wanted")],
            html_url="https://github.com/acme/api/issues/5",
            created_at=NOW - timedelta(days=10),
            updated_at=NOW - timedelta(days=2),
            repository_url="https://api.github.com/repos/acme/api",
        ),
    ]
    repos = {
        "acme/web": _make_gh_repo(id_=10, full="acme/web", stars=500, pushed_days_ago=1),
        "acme/api": _make_gh_repo(id_=11, full="acme/api", stars=1200, pushed_days_ago=3),
    }

    gh = _FakeGH(issues=issues, repos=repos)
    router = _FakeRouter('{"difficulty": "medium", "reason": "x"}')
    voyage = _FakeVoyage()

    # Tight config so we only run 1 query
    config = HunterConfig(
        languages=["python"], labels=["good first issue"],
        updated_since_days=30, max_total_issues=10,
    )

    stats = await hunt(
        gh=gh, router=router, embedder=voyage,
        session=session, config=config,
    )

    assert stats.queries_executed == 1
    assert stats.issues_seen == 2
    assert stats.issues_kept == 2
    assert stats.issues_persisted == 2
    assert stats.embeddings_generated == 2
    # Only the second issue needs the LLM (first one's "good first issue" label is decisive)
    assert stats.difficulty_calls == 2  # we call estimate_difficulty for both; heuristic short-circuits inside

    # Verify rows in DB
    count_issues = session.execute(text("SELECT COUNT(*) FROM issues")).scalar()
    count_repos = session.execute(text("SELECT COUNT(*) FROM repos")).scalar()
    count_vecs = session.execute(text("SELECT COUNT(*) FROM issues_vec")).scalar()
    assert count_issues == 2
    assert count_repos == 2
    assert count_vecs == 2


@pytest.mark.unit
async def test_hunt_skips_unhealthy_repos(session):
    issues = [
        GHIssue(
            id=3003, number=1, title="x", state="open",
            html_url="https://...", labels=[IssueLabel(name="bug")],
            created_at=NOW - timedelta(days=1),
            updated_at=NOW,
            repository_url="https://api.github.com/repos/dead/repo",
        ),
    ]
    repos = {
        # Archived → health = 0 → below threshold
        "dead/repo": _make_gh_repo(id_=99, full="dead/repo", archived=True),
    }
    gh = _FakeGH(issues=issues, repos=repos)
    router = _FakeRouter('{"difficulty": "easy", "reason": "x"}')
    voyage = _FakeVoyage()
    stats = await hunt(
        gh=gh, router=router, embedder=voyage,
        session=session,
        config=HunterConfig(languages=["python"], labels=["bug"]),
    )
    assert stats.issues_seen == 1
    assert stats.issues_kept == 0
    assert stats.issues_persisted == 0
    assert stats.embeddings_generated == 0


@pytest.mark.unit
async def test_hunt_dedupes_issues_across_queries(session):
    same_issue = GHIssue(
        id=4004, number=1, title="x", state="open",
        html_url="https://...", labels=[IssueLabel(name="good first issue")],
        created_at=NOW, updated_at=NOW,
        repository_url="https://api.github.com/repos/foo/bar",
    )
    gh = _FakeGH(
        issues=[same_issue],
        repos={"foo/bar": _make_gh_repo(id_=20, full="foo/bar")},
    )
    router = _FakeRouter('{"difficulty": "easy"}')
    voyage = _FakeVoyage()

    # Multiple queries (cross of 2 langs × 2 labels = 4) — same issue returned each time
    config = HunterConfig(
        languages=["python", "go"], labels=["good first issue", "help wanted"],
        max_total_issues=50,
    )
    stats = await hunt(
        gh=gh, router=router, embedder=voyage,
        session=session, config=config,
    )
    assert stats.queries_executed == 4
    # Only one unique issue
    assert stats.issues_persisted == 1


@pytest.mark.unit
async def test_hunt_works_with_embeddings_disabled(session):
    issues = [
        GHIssue(
            id=5005, number=1, title="x", state="open",
            html_url="https://...", labels=[IssueLabel(name="good first issue")],
            created_at=NOW, updated_at=NOW,
            repository_url="https://api.github.com/repos/a/b",
        ),
    ]
    repos = {"a/b": _make_gh_repo(id_=30, full="a/b")}
    gh = _FakeGH(issues=issues, repos=repos)
    router = _FakeRouter('{"difficulty": "easy"}')
    voyage = _FakeVoyage()
    config = HunterConfig(
        languages=["python"], labels=["good first issue"],
        enable_embeddings=False,
    )
    stats = await hunt(
        gh=gh, router=router, embedder=voyage,
        session=session, config=config,
    )
    assert stats.issues_persisted == 1
    assert stats.embeddings_generated == 0
    voyage.embed.assert_not_called()
