"""Search query strategies for the Issue Hunter.

We generate queries by crossing:
    - Beginner-friendly labels (good first issue, help wanted, etc.)
    - Target languages
    - Recency window (only recently-updated issues)

Each call to `build_queries()` returns a list of GitHub search query strings.
The hunter executes them sequentially (Search API limit is 30/min).
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

# Labels that signal "the maintainers want outside contributions on this issue."
BEGINNER_LABELS = (
    "good first issue",
    "help wanted",
    "beginner",
    "beginner friendly",
    "good-first-issue",
    "first-timers-only",
)

# Default languages we hunt for. Override via HunterConfig.
DEFAULT_LANGUAGES = (
    "python",
    "typescript",
    "javascript",
    "go",
    "rust",
)


def _iso_date(d: datetime) -> str:
    return d.date().isoformat()


def build_queries(
    languages: Iterable[str] = DEFAULT_LANGUAGES,
    labels: Iterable[str] = BEGINNER_LABELS,
    *,
    updated_since_days: int = 30,
    min_stars: int = 100,
) -> list[str]:
    """Return a list of GitHub search query strings.

    Example output for one (label, language) pair:
        'is:issue is:open label:"good first issue" language:python
         stars:>100 updated:>=2025-04-01'
    """
    cutoff = _iso_date(datetime.utcnow() - timedelta(days=updated_since_days))
    queries: list[str] = []
    for label in labels:
        for lang in languages:
            q = (
                f'is:issue is:open '
                f'label:"{label}" '
                f'language:{lang} '
                f'stars:>{min_stars} '
                f'updated:>={cutoff}'
            )
            queries.append(q)
    return queries


def build_gsoc_queries(
    org_logins: Iterable[str],
    labels: Iterable[str] = BEGINNER_LABELS,
    *,
    updated_since_days: int = 60,
    min_stars: int = 10,
) -> list[str]:
    """Build GitHub-search queries scoped to specific org owners (GSoC mode).

    One query per (org, label). No language qualifier — orgs are assumed
    pre-filtered against the user's languages by the caller. Defaults are
    looser than general mode because GSoC orgs include smaller research
    projects (lower stars) and issues often stay open longer waiting for
    student contributors (wider recency window).

    Example output:
        'is:issue is:open label:"good first issue" user:apache
         stars:>10 updated:>=2025-03-19'
    """
    cutoff = _iso_date(datetime.utcnow() - timedelta(days=updated_since_days))
    queries: list[str] = []
    for login in org_logins:
        if not login:
            continue
        for label in labels:
            q = (
                f'is:issue is:open '
                f'label:"{label}" '
                f'user:{login} '
                f'stars:>{min_stars} '
                f'updated:>={cutoff}'
            )
            queries.append(q)
    return queries
