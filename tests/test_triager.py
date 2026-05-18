"""End-to-end Triager tests with mocked embeddings + LLM."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.agents.triager.schemas import RankedMatch, RankingWeights
from app.agents.triager.triager import (
    attach_why_fits,
    rank_for_user,
    user_skill_text,
)
from app.db.models import Issue, Repo, User, UserSkill
from app.db.session import VEC_DIM
from app.db.vector import insert_vector

NOW = datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

class _FakeVoyage:
    """Returns a deterministic embedding based on the input text length."""

    def __init__(self, embedding: list[float] | None = None):
        self._embedding = embedding or ([0.1] * VEC_DIM)
        self.embed = AsyncMock(side_effect=self._embed)

    async def _embed(self, texts, *, input_type="document"):
        return SimpleNamespace(
            embeddings=[self._embedding for _ in texts],
            model="voyage-3-large",
            total_tokens=len(texts) * 10,
        )


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
            usage=SimpleNamespace(prompt_tokens=80, completion_tokens=40),
            _hidden_params={"response_cost": 0.0002},
        )


def _seed_user_with_skill(session) -> User:
    user = User(github_login="testuser", github_id=42, name="Test User")
    session.add(user)
    session.flush()
    skill = UserSkill(
        user_id=user.id,
        languages=["Python", "Go"],
        frameworks=["FastAPI", "Gin"],
        domains=["backend"],
        experience_signal="mid",
        summary="Backend developer with Python + Go.",
    )
    session.add(skill)
    session.commit()
    return user


def _seed_issues_and_vecs(session, *, n: int = 3, base_distance: float = 0.5) -> list[int]:
    """Create n issues with embeddings progressively further from the query vector."""
    ids: list[int] = []
    for i in range(n):
        repo = Repo(
            id=100 + i, full_name=f"acme/repo{i}", name=f"repo{i}",
            html_url=f"https://github.com/acme/repo{i}",
            language="Python",
            stargazers_count=1000 + i * 500,
            forks_count=50, open_issues_count=10,
            pushed_at=NOW - timedelta(days=1),
            health_score=0.8,
        )
        session.add(repo)
        session.flush()
        issue = Issue(
            id=1000 + i, repo_id=repo.id, number=i + 1,
            title=f"Issue {i}", body=f"Body {i}",
            state="open", labels=["bug"], comments_count=0,
            html_url=f"https://github.com/acme/repo{i}/issues/{i + 1}",
            issue_created_at=NOW - timedelta(days=i + 1),
            issue_updated_at=NOW - timedelta(days=i),
            difficulty=("easy", "medium", "hard")[i % 3],
        )
        session.add(issue)
        session.flush()
        # Embeddings: vary one dimension so distance increases with i
        emb = [0.1] * VEC_DIM
        emb[0] = 0.1 + i * 0.05  # tiny offsets
        insert_vector(session, "issues_vec", issue.id, emb)
        ids.append(issue.id)
    session.commit()
    return ids


# ---------------------------------------------------------------------------
# user_skill_text
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_user_skill_text_combines_fields():
    skill = SimpleNamespace(
        summary="Backend dev",
        languages=["Python"],
        frameworks=["FastAPI"],
        domains=["web"],
    )
    text_blob = user_skill_text(skill)
    assert "Backend dev" in text_blob
    assert "Python" in text_blob
    assert "FastAPI" in text_blob
    assert "web" in text_blob


@pytest.mark.unit
def test_user_skill_text_empty_falls_back_to_placeholder():
    skill = SimpleNamespace(summary=None, languages=[], frameworks=[], domains=[])
    assert user_skill_text(skill) == "(no profile)"


# ---------------------------------------------------------------------------
# rank_for_user — main flow
# ---------------------------------------------------------------------------

@pytest.mark.unit
async def test_rank_for_unknown_user_raises(session):
    voyage = _FakeVoyage()
    with pytest.raises(ValueError, match="No skill profile"):
        await rank_for_user(
            github_login="ghost", session=session, embedder=voyage,
        )


@pytest.mark.unit
async def test_rank_for_user_returns_top_n(session):
    _seed_user_with_skill(session)
    _seed_issues_and_vecs(session, n=5)
    voyage = _FakeVoyage()

    matches = await rank_for_user(
        github_login="testuser", session=session, embedder=voyage,
        top_n=3, explain=False,
    )
    assert len(matches) == 3
    # Sorted descending by final_score
    assert matches[0].final_score >= matches[1].final_score >= matches[2].final_score


@pytest.mark.unit
async def test_rank_for_user_with_no_candidates(session):
    _seed_user_with_skill(session)  # no issues seeded
    voyage = _FakeVoyage()
    matches = await rank_for_user(
        github_login="testuser", session=session, embedder=voyage, explain=False,
    )
    assert matches == []


@pytest.mark.unit
async def test_rank_for_user_persists_user_skill_embedding(session):
    user = _seed_user_with_skill(session)
    _seed_issues_and_vecs(session, n=1)
    voyage = _FakeVoyage()
    await rank_for_user(
        github_login="testuser", session=session, embedder=voyage, explain=False,
    )
    count = session.execute(
        text("SELECT COUNT(*) FROM user_skills_vec WHERE rowid = :r"),
        {"r": user.skill.id},
    ).scalar()
    assert count == 1


@pytest.mark.unit
async def test_rank_score_components_in_range(session):
    _seed_user_with_skill(session)
    _seed_issues_and_vecs(session, n=3)
    voyage = _FakeVoyage()
    matches = await rank_for_user(
        github_login="testuser", session=session, embedder=voyage, explain=False,
    )
    for m in matches:
        assert 0.0 <= m.skill_match <= 1.0
        assert 0.0 <= m.repo_health <= 1.0
        assert 0.0 <= m.freshness <= 1.0
        assert 0.0 <= m.difficulty_match <= 1.0
        assert 0.0 <= m.impact <= 1.0
        assert 0.0 <= m.final_score <= 1.0


@pytest.mark.unit
async def test_rank_for_user_difficulty_preference_affects_ranking(session):
    _seed_user_with_skill(session)
    _seed_issues_and_vecs(session, n=3)  # difficulties: easy, medium, hard
    voyage = _FakeVoyage()
    # Custom weights: difficulty dominates
    weights = RankingWeights(
        skill_match=0, repo_health=0, freshness=0,
        difficulty_match=1.0, impact=0,
    )
    easy_matches = await rank_for_user(
        github_login="testuser", session=session, embedder=voyage,
        weights=weights, difficulty_pref="easy", top_n=3, explain=False,
    )
    # With diff weight=100%, easy issue should rank first
    assert easy_matches[0].difficulty == "easy"


# ---------------------------------------------------------------------------
# attach_why_fits
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_attach_why_fits_populates_explanations(session):
    matches = [
        RankedMatch(
            issue_id=1, issue_number=1, repo_full_name="x/y", title="A",
            html_url="x", labels=["bug"], difficulty="easy",
            skill_match=0.9, repo_health=0.8, freshness=0.7,
            difficulty_match=1.0, impact=0.5, final_score=0.8,
            issue_updated_at=NOW, stargazers_count=100,
        ),
        RankedMatch(
            issue_id=2, issue_number=2, repo_full_name="x/z", title="B",
            html_url="x", labels=[], difficulty=None,
            skill_match=0.5, repo_health=0.6, freshness=0.4,
            difficulty_match=0.5, impact=0.3, final_score=0.5,
            issue_updated_at=NOW, stargazers_count=10,
        ),
    ]
    router = _FakeRouter(
        '{"reasons": ['
        '{"issue_id": 1, "why": "Your Python work matches this FastAPI bug"},'
        '{"issue_id": 2, "why": "Good warm-up given your backend domain"}'
        ']}'
    )
    attach_why_fits(
        router, user_skill_summary="A backend dev", matches=matches, session=session,
    )
    assert matches[0].why_it_fits.startswith("Your Python")
    assert matches[1].why_it_fits.startswith("Good warm-up")


@pytest.mark.unit
def test_attach_why_fits_empty_list_is_noop():
    router = _FakeRouter('{"reasons": []}')
    attach_why_fits(router, user_skill_summary="x", matches=[])
    assert router.call_count == 0


@pytest.mark.unit
def test_attach_why_fits_handles_parse_failure_gracefully(session):
    matches = [
        RankedMatch(
            issue_id=1, issue_number=1, repo_full_name="x/y", title="A",
            html_url="x", labels=[], difficulty=None,
            skill_match=0.5, repo_health=0.5, freshness=0.5,
            difficulty_match=0.5, impact=0.5, final_score=0.5,
            issue_updated_at=NOW, stargazers_count=10,
        ),
    ]
    router = _FakeRouter("not valid json")
    attach_why_fits(router, user_skill_summary="x", matches=matches, session=session)
    assert matches[0].why_it_fits is None  # left unset on failure
