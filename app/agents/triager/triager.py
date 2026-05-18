"""Triager: given a user's skill profile, rank candidate issues.

Pipeline:
    1. Fetch user + user_skill (need an embedding for the user's skill text)
    2. Embed the user's skill summary if not already embedded
    3. Vector search in issues_vec for top-K nearest issues
    4. Hydrate each hit with full issue + repo metadata
    5. Compute scoring components (skill, health, freshness, difficulty, impact)
    6. Combine with weights
    7. (Optional) LLM batched call to produce 1-line "why it fits" lines
    8. Return RankedMatch list, sorted descending by final_score

The LLM call is optional — without keys, we still rank deterministically.
"""
from __future__ import annotations

from collections.abc import Sequence

import structlog
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.triager.schemas import RankedMatch, RankingWeights
from app.agents.triager.scoring import (
    DifficultyPref,
    combine,
    difficulty_match_score,
    distance_to_similarity,
    freshness_score,
    impact_score,
)
from app.db.models import Issue, Repo, User, UserSkill
from app.db.vector import insert_vector, search_similar
from app.llm import call_llm

log = structlog.get_logger(__name__)

CANDIDATE_POOL_SIZE = 50   # how many to pull from vec0 before ranking
TOP_N_DEFAULT = 10


# ---------------------------------------------------------------------------
# User skill embedding
# ---------------------------------------------------------------------------

def user_skill_text(skill: UserSkill) -> str:
    """Compact textual representation of a user's skill profile for embedding."""
    parts: list[str] = []
    if skill.summary:
        parts.append(skill.summary)
    if skill.languages:
        parts.append("Languages: " + ", ".join(skill.languages))
    if skill.frameworks:
        parts.append("Frameworks: " + ", ".join(skill.frameworks))
    if skill.domains:
        parts.append("Domains: " + ", ".join(skill.domains))
    return "\n".join(parts) or "(no profile)"


async def ensure_user_skill_embedding(
    session: Session,
    embedder,
    skill: UserSkill,
) -> list[float]:
    """Embed the user's skill text and persist into user_skills_vec.

    We re-embed on every rank call for simplicity in v1 (it's cheap and
    keeps things fresh). v2 can cache by hash.
    """
    text = user_skill_text(skill)
    result = await embedder.embed([text], input_type="query")
    embedding = result.embeddings[0]
    insert_vector(session, "user_skills_vec", skill.id, embedding)
    session.commit()
    return embedding


# ---------------------------------------------------------------------------
# Why-it-fits LLM step (optional, batched)
# ---------------------------------------------------------------------------

WHY_SYSTEM_PROMPT = """You are helping a developer browse open-source issues that match their skills.

You will be given:
- The developer's skill summary
- A short list of issues (title + labels + repo + difficulty)

For EACH issue, return a one-sentence "why it fits" — no more than 18 words.
Mention a specific connection between the developer's profile and the issue
(language, framework, domain, or difficulty). Be concrete; avoid filler.

Return a JSON object: {"reasons": [{"issue_id": <int>, "why": "<sentence>"}, ...]}
Order doesn't matter; just include one entry per input issue. No markdown fences."""


class _WhyReason(BaseModel):
    model_config = ConfigDict(extra="ignore")
    issue_id: int
    why: str


class _WhyOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reasons: list[_WhyReason]


def attach_why_fits(
    router,
    *,
    user_skill_summary: str,
    matches: list[RankedMatch],
    session: Session | None = None,
    user_id: int | None = None,
) -> None:
    """Mutate `matches` in place to add the `why_it_fits` field."""
    if not matches:
        return

    issue_lines = []
    for m in matches:
        labels = ", ".join(m.labels[:4]) if m.labels else "(none)"
        diff = m.difficulty or "?"
        issue_lines.append(
            f"- id={m.issue_id}  repo={m.repo_full_name}  "
            f"title=\"{m.title}\"  labels=[{labels}]  difficulty={diff}"
        )
    user_msg = (
        f"Developer profile:\n{user_skill_summary}\n\n"
        f"Issues to explain:\n" + "\n".join(issue_lines)
    )

    _result, parsed = call_llm(
        router,
        messages=[
            {"role": "system", "content": WHY_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="triager_why",
        response_model=_WhyOutput,
        session=session,
        user_id=user_id,
        max_tokens=600,
    )
    if parsed is None:
        return  # leave why_it_fits as None on parse failure

    by_id: dict[int, str] = {r.issue_id: r.why for r in parsed.reasons}
    for m in matches:
        m.why_it_fits = by_id.get(m.issue_id)


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

async def rank_for_user(
    *,
    github_login: str,
    session: Session,
    embedder,
    router=None,
    weights: RankingWeights | None = None,
    difficulty_pref: DifficultyPref = "any",
    top_n: int = TOP_N_DEFAULT,
    candidate_pool: int = CANDIDATE_POOL_SIZE,
    explain: bool = True,
) -> list[RankedMatch]:
    """Return top-N ranked matches for `github_login`. Requires the user to
    have been profiled first."""
    weights = weights or RankingWeights()

    user = session.execute(
        select(User).where(User.github_login == github_login)
    ).scalar_one_or_none()
    if user is None or user.skill is None:
        raise ValueError(
            f"No skill profile for {github_login!r}. Run the Skill Profiler first."
        )

    user_embedding = await ensure_user_skill_embedding(session, embedder, user.skill)

    hits = search_similar(session, "issues_vec", user_embedding, k=candidate_pool)
    if not hits:
        log.info("rank_no_hits", login=github_login)
        return []

    # Hydrate with full issue + repo data
    issue_ids = [h.rowid for h in hits]
    issues = session.execute(
        select(Issue).where(Issue.id.in_(issue_ids))
    ).scalars().all()
    issues_by_id = {i.id: i for i in issues}

    repo_ids = {i.repo_id for i in issues}
    repos = session.execute(select(Repo).where(Repo.id.in_(repo_ids))).scalars().all()
    repos_by_id = {r.id: r for r in repos}

    matches: list[RankedMatch] = []
    for hit in hits:
        issue = issues_by_id.get(hit.rowid)
        if issue is None:
            continue
        repo = repos_by_id.get(issue.repo_id)
        if repo is None:
            continue

        skill = distance_to_similarity(hit.distance)
        repo_h = repo.health_score or 0.0
        fresh = freshness_score(issue.issue_updated_at)
        diff = difficulty_match_score(issue.difficulty, difficulty_pref)
        impact = impact_score(repo.stargazers_count)
        final = combine(
            skill=skill, repo_health=repo_h, freshness=fresh,
            difficulty=diff, impact=impact, weights=weights,
        )

        matches.append(RankedMatch(
            issue_id=issue.id,
            issue_number=issue.number,
            repo_full_name=repo.full_name,
            title=issue.title,
            html_url=issue.html_url,
            labels=list(issue.labels or []),
            difficulty=issue.difficulty,
            skill_match=round(skill, 4),
            repo_health=round(repo_h, 4),
            freshness=round(fresh, 4),
            difficulty_match=round(diff, 4),
            impact=round(impact, 4),
            final_score=final,
            why_it_fits=None,
            issue_updated_at=issue.issue_updated_at,
            stargazers_count=repo.stargazers_count,
        ))

    matches.sort(key=lambda m: m.final_score, reverse=True)
    top = matches[:top_n]

    if explain and router is not None and top:
        try:
            attach_why_fits(
                router,
                user_skill_summary=user.skill.summary or user_skill_text(user.skill),
                matches=top,
                session=session,
                user_id=user.id,
            )
        except Exception as e:
            log.warning("why_fits_failed", error=str(e))

    log.info(
        "rank_completed",
        login=github_login,
        candidates=len(hits),
        ranked=len(top),
    )
    return top


def matches_to_dicts(matches: Sequence[RankedMatch]) -> list[dict]:
    return [m.model_dump(mode="json") for m in matches]
