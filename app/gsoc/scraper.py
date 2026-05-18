"""Scrape GSoC organizations from summerofcode.withgoogle.com.

The site is a Next.js app. The full page payload is embedded in a
`<script id="__NEXT_DATA__">` tag as JSON — far more stable than the
rendered HTML, which uses hashed class names that change on every
deploy. We extract that JSON blob and walk the tree heuristically for
org-shaped dicts.

Design split:
    fetch_org_list_page  — pure HTTP (mockable, cacheable)
    parse_orgs           — pure parsing (HTML in, ScrapedOrg out)
    scrape_year          — orchestrates fetch + parse + disk cache

If GSoC changes the embedded schema, only `_walk_for_orgs` and
`_to_scraped_org` need updating — keep the rest stable.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

GSOC_ORG_LIST_URL = "https://summerofcode.withgoogle.com/programs/{year}/organizations"

# Matches the standard Next.js bootstrap tag. Tolerates extra attributes
# and whitespace between tag name and id.
_NEXT_DATA_RE = re.compile(
    r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.+?)</script>',
    re.DOTALL,
)

DEFAULT_USER_AGENT = "oss-engine/0.1 (+https://github.com/oss-engine)"
_REQUEST_TIMEOUT = 30.0


@dataclass
class ScrapedOrg:
    """Single org as returned by the scraper. Internal type, not API-exposed."""
    slug: str
    name: str
    year: int
    description: str | None = None
    homepage_url: str | None = None
    project_ideas_url: str | None = None
    technologies: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_org_list_page(year: int, http_client: httpx.Client | None = None) -> str:
    """Fetch the raw HTML for a year's org-list page."""
    url = GSOC_ORG_LIST_URL.format(year=year)
    own_client = http_client is None
    client = http_client or httpx.Client(
        headers={"User-Agent": DEFAULT_USER_AGENT},
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text
    finally:
        if own_client:
            client.close()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _extract_next_data(html: str) -> Any | None:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        log.warning("gsoc_scrape_bad_next_data_json", error=str(exc))
        return None


# Keys we consider "org-shaped" — a dict with `name` plus at least one of these
# is treated as an organization record.
_ORG_FINGERPRINT_KEYS = frozenset({
    "shortDescription", "description", "organizationCode",
    "slug", "websiteUrl", "ideasListUrl",
})


def _walk_for_orgs(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "name" in node and any(k in node for k in _ORG_FINGERPRINT_KEYS):
            out.append(node)
        for v in node.values():
            _walk_for_orgs(v, out)
    elif isinstance(node, list):
        for item in node:
            _walk_for_orgs(item, out)


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            return v
    return None


def _to_scraped_org(raw: dict[str, Any], year: int) -> ScrapedOrg | None:
    slug = _first(raw, "slug", "organizationCode")
    name = _first(raw, "name")
    if not slug or not name:
        return None
    return ScrapedOrg(
        slug=str(slug),
        name=str(name),
        year=year,
        description=_first(raw, "description", "shortDescription", "blurb"),
        homepage_url=_first(raw, "websiteUrl", "website", "homepageUrl"),
        project_ideas_url=_first(raw, "ideasListUrl", "ideasList", "projectIdeasUrl"),
        technologies=_as_str_list(raw.get("technologies")),
        topics=_as_str_list(raw.get("topics") or raw.get("categories")),
    )


def _as_str_list(v: Any) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x) for x in v if isinstance(x, (str, int))]


def parse_orgs(html: str, year: int) -> list[ScrapedOrg]:
    """Extract a list of ScrapedOrg from a page's HTML. Empty on failure."""
    next_data = _extract_next_data(html)
    if next_data is None:
        log.warning("gsoc_scrape_no_next_data", year=year)
        return []

    raw: list[dict[str, Any]] = []
    _walk_for_orgs(next_data, raw)

    # Dedupe by slug — Next.js often embeds the same record in multiple
    # nested page-prop sections (initialProps, query, etc.).
    seen: dict[str, ScrapedOrg] = {}
    for r in raw:
        org = _to_scraped_org(r, year)
        if org is None:
            continue
        # Keep the first occurrence; later ones tend to be summary stubs
        # with fewer fields filled in.
        seen.setdefault(org.slug, org)

    return list(seen.values())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def scrape_year(
    year: int,
    *,
    http_client: httpx.Client | None = None,
    cache_dir: Path | None = None,
) -> list[ScrapedOrg]:
    """Fetch + parse the org list for `year`. Caches raw HTML on disk.

    `cache_dir` is recommended — re-runs skip the network entirely, and
    if parsing breaks you have the raw page locally to debug against.
    """
    cache_file: Path | None = None
    html: str | None = None

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"gsoc_{year}.html"
        if cache_file.exists():
            html = cache_file.read_text(encoding="utf-8")
            log.info("gsoc_scrape_cache_hit", year=year, path=str(cache_file))

    if html is None:
        log.info("gsoc_scrape_fetch", year=year)
        html = fetch_org_list_page(year, http_client)
        if cache_file is not None:
            cache_file.write_text(html, encoding="utf-8")

    orgs = parse_orgs(html, year)
    log.info("gsoc_scrape_parsed", year=year, count=len(orgs))
    return orgs
