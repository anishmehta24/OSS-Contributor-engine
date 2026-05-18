"""Skill Profiler: builds a SkillProfile from a GitHub user's history.

Pipeline:
    1. Fetch user metadata
    2. Fetch top-N owned, non-fork repos sorted by recent activity
    3. Per repo: language stats, manifest contents, recent commit messages
    4. Aggregate languages (weighted by bytes) + frameworks (deduplicated)
    5. One LLM call to synthesize: domains, experience signal, summary
    6. Persist user + user_skill rows

Splitting deterministic extraction from LLM synthesis gives us:
    - Reliable language/framework counts (not LLM-vibed)
    - Cheap LLM call (only one per profile, on a small focused prompt)
"""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.profiles.manifest_parser import KNOWN_MANIFESTS, parse_manifest
from app.agents.profiles.schemas import LLMSynthesis, RepoSignal, SkillProfile
from app.db.models import User, UserSkill
from app.llm import LLMResult, call_llm
from app.tools.github import GitHubClient
from app.tools.github.exceptions import NotFoundError

log = structlog.get_logger(__name__)

MAX_REPOS_TO_ANALYZE = 15
RECENT_COMMITS_PER_REPO = 8
TOP_LANGUAGES = 10
TOP_FRAMEWORKS = 20


# ---------------------------------------------------------------------------
# Aggregation helpers (pure)
# ---------------------------------------------------------------------------

def aggregate_languages(signals: list[RepoSignal]) -> list[str]:
    """Sum bytes per language across all repos, return top N descending."""
    totals: Counter[str] = Counter()
    for sig in signals:
        for lang, byte_count in sig.languages.items():
            totals[lang] += byte_count
    return [lang for lang, _ in totals.most_common(TOP_LANGUAGES)]


def aggregate_frameworks(signals: list[RepoSignal]) -> list[str]:
    """Count framework occurrences across repos, return most common."""
    totals: Counter[str] = Counter()
    for sig in signals:
        for fw in sig.frameworks:
            totals[fw] += 1
    return [fw for fw, _ in totals.most_common(TOP_FRAMEWORKS)]


# ---------------------------------------------------------------------------
# GitHub fetching
# ---------------------------------------------------------------------------

async def collect_repo_signals(gh: GitHubClient, login: str) -> list[RepoSignal]:
    """Fetch up to MAX_REPOS_TO_ANALYZE most recently active owned repos."""
    repos = await gh.get_user_repos(login, max_repos=50, sort="pushed")
    repos = [r for r in repos if not r.fork and not r.archived]
    repos = repos[:MAX_REPOS_TO_ANALYZE]

    signals: list[RepoSignal] = []
    for repo in repos:
        # Languages
        try:
            languages = await gh.get_repo_languages(repo.full_name)
        except Exception as e:
            log.warning("languages_fetch_failed", repo=repo.full_name, error=str(e))
            languages = {}

        # Manifests
        frameworks: list[str] = []
        for filename in KNOWN_MANIFESTS:
            try:
                content = await gh.get_repo_file(repo.full_name, filename)
            except NotFoundError:
                content = None
            except Exception as e:
                log.warning(
                    "manifest_fetch_failed",
                    repo=repo.full_name, file=filename, error=str(e),
                )
                content = None
            if content:
                frameworks.extend(parse_manifest(filename, content))

        # Recent commits
        try:
            commits = await gh.get_recent_commits(
                repo.full_name, limit=RECENT_COMMITS_PER_REPO
            )
            commit_messages = [c.message.split("\n", 1)[0] for c in commits]
        except Exception as e:
            log.warning("commits_fetch_failed", repo=repo.full_name, error=str(e))
            commit_messages = []

        signals.append(RepoSignal(
            full_name=repo.full_name,
            description=repo.description,
            primary_language=repo.language,
            languages=languages,
            frameworks=sorted(set(frameworks)),
            stars=repo.stargazers_count,
            is_fork=repo.fork,
            is_archived=repo.archived,
            pushed_at=repo.pushed_at,
            recent_commit_messages=commit_messages,
            topics=repo.topics,
        ))

    return signals


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """You are an expert technical recruiter analyzing a developer's GitHub profile.

You will be given:
- The developer's bio + company (may be empty)
- Aggregated languages (most-used first)
- Aggregated frameworks/libraries (most-used first)
- A list of their recent repos with descriptions, languages, stars, and recent commit message subjects

Your job: return ONE JSON object with three fields:

  "domains":          A list of 3-6 functional domains where this developer
                      operates. Pick from broad categories: backend, frontend,
                      mobile, ML, data engineering, devops, security, gamedev,
                      embedded, infra, distributed systems, web3, robotics.
                      Use lowercase. Be specific to evidence; don't invent.

  "experience_signal": One of "junior", "mid", "senior". Base this on:
                      - Repo count and recency
                      - Complexity signals in commit messages
                      - Variety of languages and frameworks
                      - Whether projects look like tutorials or production work
                      Bias toward conservative; "senior" requires real evidence.

  "summary":          2-3 sentences, max 600 chars, that an interviewer
                      could glance at to understand who this person is and
                      what they'd be good at building. Avoid filler.
                      Don't start with "This developer".

Return ONLY the JSON object, no markdown fences, no commentary."""


def build_synthesis_prompt(
    *,
    login: str,
    bio: str | None,
    company: str | None,
    languages: list[str],
    frameworks: list[str],
    signals: list[RepoSignal],
) -> str:
    lines: list[str] = []
    lines.append(f"GitHub login: {login}")
    if bio:
        lines.append(f"Bio: {bio}")
    if company:
        lines.append(f"Company: {company}")
    lines.append("")
    lines.append(f"Top languages: {', '.join(languages) if languages else '(none)'}")
    lines.append(f"Top frameworks: {', '.join(frameworks) if frameworks else '(none)'}")
    lines.append("")
    lines.append(f"Recent repos ({len(signals)}):")
    for sig in signals:
        desc = sig.description or "(no description)"
        commits = "; ".join(sig.recent_commit_messages[:3])
        lines.append(
            f"- {sig.full_name} (★{sig.stars}, lang={sig.primary_language})\n"
            f"    desc: {desc}\n"
            f"    recent: {commits}"
        )
    return "\n".join(lines)


def synthesize(
    router,
    *,
    login: str,
    bio: str | None,
    company: str | None,
    languages: list[str],
    frameworks: list[str],
    signals: list[RepoSignal],
    user_id: int | None = None,
    session: Session | None = None,
) -> tuple[LLMResult, LLMSynthesis | None]:
    user_msg = build_synthesis_prompt(
        login=login, bio=bio, company=company,
        languages=languages, frameworks=frameworks, signals=signals,
    )
    return call_llm(
        router,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        agent_name="skill_profiler",
        response_model=LLMSynthesis,
        user_id=user_id,
        session=session,
        max_tokens=600,
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def upsert_user_and_skill(
    session: Session,
    *,
    github_login: str,
    github_id: int,
    name: str | None,
    languages: list[str],
    frameworks: list[str],
    domains: list[str],
    experience_signal: str | None,
    summary: str | None,
) -> User:
    """Create or update the User + UserSkill rows."""
    user = session.execute(
        select(User).where(User.github_login == github_login)
    ).scalar_one_or_none()
    if user is None:
        user = User(github_login=github_login, github_id=github_id, name=name)
        session.add(user)
    else:
        user.name = name
    session.flush()

    if user.skill is None:
        user.skill = UserSkill(user_id=user.id)
    user.skill.languages = languages
    user.skill.frameworks = frameworks
    user.skill.domains = domains
    user.skill.experience_signal = experience_signal
    user.skill.summary = summary

    session.commit()
    return user


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------

async def profile_user(
    login: str,
    *,
    gh: GitHubClient,
    router,
    session: Session | None = None,
) -> SkillProfile:
    """Build a SkillProfile end-to-end. Persists if `session` is provided."""
    log.info("profile_user_starting", login=login)

    user_data = await gh.get_user(login)
    signals = await collect_repo_signals(gh, login)

    languages = aggregate_languages(signals)
    frameworks = aggregate_frameworks(signals)

    # Persist user early so user_id is available for telemetry
    user_db_id: int | None = None
    if session is not None:
        user_row = upsert_user_and_skill(
            session,
            github_login=user_data.login,
            github_id=user_data.id,
            name=user_data.name,
            languages=languages, frameworks=frameworks,
            domains=[], experience_signal=None, summary=None,
        )
        user_db_id = user_row.id

    _result, parsed = synthesize(
        router,
        login=user_data.login,
        bio=user_data.bio,
        company=user_data.company,
        languages=languages,
        frameworks=frameworks,
        signals=signals,
        user_id=user_db_id,
        session=session,
    )

    domains = parsed.domains if parsed else []
    experience_signal = parsed.experience_signal if parsed else None
    summary = parsed.summary if parsed else None

    # Update with synthesized fields
    if session is not None:
        upsert_user_and_skill(
            session,
            github_login=user_data.login,
            github_id=user_data.id,
            name=user_data.name,
            languages=languages, frameworks=frameworks,
            domains=domains, experience_signal=experience_signal, summary=summary,
        )

    profile = SkillProfile(
        github_login=user_data.login,
        github_id=user_data.id,
        name=user_data.name,
        languages=languages,
        frameworks=frameworks,
        domains=domains,
        experience_signal=experience_signal,
        summary=summary,
        repos_analyzed=len(signals),
        profiled_at=datetime.now(UTC).replace(tzinfo=None),
    )
    log.info(
        "profile_user_completed",
        login=login,
        repos=len(signals),
        languages=len(languages),
        frameworks=len(frameworks),
        synthesis_ok=parsed is not None,
    )
    return profile


def profile_user_sync(login: str, *, gh: GitHubClient, router, session=None) -> SkillProfile:
    """Convenience wrapper for sync callers (CLI, scripts)."""
    return asyncio.run(profile_user(login, gh=gh, router=router, session=session))
