"""Tests for the GSoC scraper.

Live GSoC HTML is not fetched in tests — we use a representative fixture
that mimics the Next.js `__NEXT_DATA__` shape. If the real site changes
schema, update `_to_scraped_org` in scraper.py and add a new fixture.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.gsoc.scraper import (
    GSOC_ORG_LIST_URL,
    ScrapedOrg,
    fetch_org_list_page,
    parse_orgs,
    scrape_year,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gsoc_sample.html"


@pytest.fixture
def sample_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# parse_orgs
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_parse_orgs_extracts_all_unique_orgs(sample_html):
    orgs = parse_orgs(sample_html, year=2025)
    slugs = {o.slug for o in orgs}
    assert slugs == {"apache-software-foundation", "mozilla", "a-brand-new-org"}


@pytest.mark.unit
def test_parse_orgs_dedupes_by_slug(sample_html):
    # The fixture intentionally has a duplicate Mozilla stub — must collapse.
    orgs = parse_orgs(sample_html, year=2025)
    mozillas = [o for o in orgs if o.slug == "mozilla"]
    assert len(mozillas) == 1
    # Keep the first (richer) record, not the stub.
    assert mozillas[0].technologies == ["Rust", "JavaScript", "C++"]


@pytest.mark.unit
def test_parse_orgs_populates_optional_fields(sample_html):
    by_slug = {o.slug: o for o in parse_orgs(sample_html, year=2025)}
    apache = by_slug["apache-software-foundation"]
    assert apache.name == "Apache Software Foundation"
    assert apache.year == 2025
    assert apache.homepage_url == "https://www.apache.org/"
    assert apache.project_ideas_url == "https://community.apache.org/gsoc.html"
    assert apache.technologies == ["Java", "Python", "Scala"]
    assert apache.topics == ["infrastructure", "big-data"]
    # description preferred over shortDescription when both present
    assert apache.description.startswith("The ASF develops")


@pytest.mark.unit
def test_parse_orgs_falls_back_to_short_description(sample_html):
    by_slug = {o.slug: o for o in parse_orgs(sample_html, year=2025)}
    mozilla = by_slug["mozilla"]
    assert mozilla.description == "Mozilla and Firefox open-source projects"


@pytest.mark.unit
def test_parse_orgs_returns_empty_without_next_data():
    assert parse_orgs("<html><body>no script here</body></html>", year=2025) == []


@pytest.mark.unit
def test_parse_orgs_returns_empty_on_invalid_json():
    html = '<script id="__NEXT_DATA__" type="application/json">{not json</script>'
    assert parse_orgs(html, year=2025) == []


@pytest.mark.unit
def test_parse_orgs_skips_entries_without_slug_or_name():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props":{"pageProps":{"orgs":['
        '{"name":"no slug","description":"x"},'
        '{"slug":"no-name","description":"x"},'
        '{"slug":"ok","name":"OK","description":"x"}'
        ']}}}'
        '</script>'
    )
    orgs = parse_orgs(html, year=2025)
    assert [o.slug for o in orgs] == ["ok"]


@pytest.mark.unit
def test_parse_orgs_uses_organization_code_as_slug_fallback():
    html = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"data":[{"organizationCode":"alt-slug","name":"Alt","description":"x"}]}'
        '</script>'
    )
    orgs = parse_orgs(html, year=2024)
    assert len(orgs) == 1
    assert orgs[0].slug == "alt-slug"


# ---------------------------------------------------------------------------
# fetch_org_list_page
# ---------------------------------------------------------------------------

@pytest.mark.unit
@respx.mock
def test_fetch_org_list_page_hits_correct_url(sample_html):
    url = GSOC_ORG_LIST_URL.format(year=2025)
    route = respx.get(url).mock(
        return_value=httpx.Response(200, text=sample_html)
    )
    text = fetch_org_list_page(2025)
    assert route.called
    assert "__NEXT_DATA__" in text


@pytest.mark.unit
@respx.mock
def test_fetch_org_list_page_raises_on_5xx():
    respx.get(GSOC_ORG_LIST_URL.format(year=2025)).mock(
        return_value=httpx.Response(503)
    )
    with pytest.raises(httpx.HTTPStatusError):
        fetch_org_list_page(2025)


@pytest.mark.unit
@respx.mock
def test_fetch_org_list_page_uses_provided_client(sample_html):
    respx.get(GSOC_ORG_LIST_URL.format(year=2024)).mock(
        return_value=httpx.Response(200, text=sample_html)
    )
    with httpx.Client() as c:
        text = fetch_org_list_page(2024, http_client=c)
    assert "__NEXT_DATA__" in text


# ---------------------------------------------------------------------------
# scrape_year (orchestration + cache)
# ---------------------------------------------------------------------------

@pytest.mark.unit
@respx.mock
def test_scrape_year_fetches_and_parses(sample_html):
    respx.get(GSOC_ORG_LIST_URL.format(year=2025)).mock(
        return_value=httpx.Response(200, text=sample_html)
    )
    orgs = scrape_year(2025)
    assert all(isinstance(o, ScrapedOrg) for o in orgs)
    assert len(orgs) == 3


@pytest.mark.unit
@respx.mock
def test_scrape_year_writes_cache_on_first_call(tmp_path, sample_html):
    respx.get(GSOC_ORG_LIST_URL.format(year=2025)).mock(
        return_value=httpx.Response(200, text=sample_html)
    )
    cache_dir = tmp_path / "cache"
    scrape_year(2025, cache_dir=cache_dir)
    cached = cache_dir / "gsoc_2025.html"
    assert cached.exists()
    assert "Apache Software Foundation" in cached.read_text(encoding="utf-8")


@pytest.mark.unit
@respx.mock
def test_scrape_year_uses_cache_skipping_network(tmp_path, sample_html):
    # Pre-seed the cache with our fixture, then mock the network to fail —
    # if scrape_year hits the network at all, the test fails.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "gsoc_2025.html").write_text(sample_html, encoding="utf-8")

    route = respx.get(GSOC_ORG_LIST_URL.format(year=2025)).mock(
        return_value=httpx.Response(500)
    )
    orgs = scrape_year(2025, cache_dir=cache_dir)
    assert len(orgs) == 3
    assert not route.called
