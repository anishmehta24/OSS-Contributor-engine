"""Unit tests for each Investigator sub-agent with a mocked LLM."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.investigator.history_detective import run_history_detective
from app.agents.investigator.issue_analyst import run_issue_analyst
from app.agents.investigator.repo_mapper import (
    filter_tree,
    is_interesting_path,
    run_repo_mapper,
)
from app.agents.investigator.schemas import (
    HistoricalContext,
    InvestigationReport,
    IssueRequirements,
    RepoMap,
)
from app.agents.investigator.synthesizer import report_to_markdown, run_synthesizer
from app.tools.github.models import Commit


def _fake_router(json_str: str):
    return SimpleNamespace(
        model_list=[{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
        completion=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json_str))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
            _hidden_params={"response_cost": 0.0001},
        ),
    )


# ---------------------------------------------------------------------------
# Issue Analyst
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_issue_analyst_parses_structured_output(session):
    router = _fake_router(
        '{"summary": "Fix the off-by-one in the cursor","requirements": ["adjust loop bound"],'
        '"acceptance_criteria": ["cursor advances by 1 step"],"open_questions": [],'
        '"technical_keywords": ["cursor", "pagination"]}'
    )
    result = run_issue_analyst(
        router, title="Cursor off by one", body="...",
        labels=["bug"], comments=[], session=session,
    )
    assert isinstance(result, IssueRequirements)
    assert result.summary.startswith("Fix the off-by-one")
    assert "cursor" in result.technical_keywords


@pytest.mark.unit
def test_issue_analyst_falls_back_to_title_on_parse_failure(session):
    router = _fake_router("not json")
    result = run_issue_analyst(
        router, title="something", body=None,
        labels=[], comments=[], session=session,
    )
    assert result.summary == "something"


# ---------------------------------------------------------------------------
# Repo Mapper — pure filters
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_is_interesting_path_accepts_source():
    assert is_interesting_path("src/app/main.py")
    assert is_interesting_path("internal/auth.go")
    assert is_interesting_path("README.md")
    assert is_interesting_path("Dockerfile")


@pytest.mark.unit
def test_is_interesting_path_rejects_noise():
    assert not is_interesting_path("node_modules/foo/bar.js")
    assert not is_interesting_path("dist/bundle.js")
    assert not is_interesting_path("package-lock.json")
    assert not is_interesting_path("Cargo.lock")
    assert not is_interesting_path("vendor/x/y.go")


@pytest.mark.unit
def test_filter_tree_skips_dirs_and_giants():
    tree = [
        {"path": "src/main.py", "type": "blob", "size": 1000},
        {"path": "huge.bin", "type": "blob", "size": 999_999_999},
        {"path": "src", "type": "tree", "size": 0},
        {"path": "node_modules/x.js", "type": "blob", "size": 100},
    ]
    out = filter_tree(tree)
    paths = [e["path"] for e in out]
    assert "src/main.py" in paths
    assert "huge.bin" not in paths
    assert "src" not in paths
    assert "node_modules/x.js" not in paths


@pytest.mark.unit
def test_filter_tree_caps_total_files():
    tree = [
        {"path": f"src/f{i}.py", "type": "blob", "size": 100}
        for i in range(500)
    ]
    assert len(filter_tree(tree)) == 200  # MAX_FILES_FOR_LLM


# ---------------------------------------------------------------------------
# Repo Mapper — LLM step
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_repo_mapper_skips_llm_when_no_files(session):
    router = _fake_router('{"repo_summary": "x", "candidate_files": []}')
    result = run_repo_mapper(
        router, repo_full_name="x/y",
        issue_reqs=IssueRequirements(summary="x"),
        tree=[], session=session,
    )
    assert result.candidate_files == []


@pytest.mark.unit
def test_repo_mapper_returns_llm_picks(session):
    router = _fake_router(
        '{"repo_summary": "A test repo",'
        '"candidate_files": [{"path": "src/a.py", "reason": "matches keyword"}]}'
    )
    tree = [{"path": "src/a.py", "type": "blob", "size": 100}]
    result = run_repo_mapper(
        router, repo_full_name="x/y",
        issue_reqs=IssueRequirements(summary="x", technical_keywords=["a"]),
        tree=tree, session=session,
    )
    assert len(result.candidate_files) == 1
    assert result.candidate_files[0].path == "src/a.py"


# ---------------------------------------------------------------------------
# History Detective
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_history_detective_with_empty_commits():
    router = _fake_router("{}")
    result = run_history_detective(router, commits=[])
    assert "No recent commit" in result.summary


@pytest.mark.unit
def test_history_detective_calls_llm_with_commits(session):
    router = _fake_router(
        '{"recent_themes": ["auth refactor"],'
        '"notable_commits": ["Drop legacy session middleware"],'
        '"summary": "Active project; auth area in flux."}'
    )
    commits = [
        Commit(sha="abc", message="Drop legacy session middleware", html_url="x"),
        Commit(sha="def", message="Add SSO support", html_url="x"),
    ]
    result = run_history_detective(router, commits=commits, session=session)
    assert isinstance(result, HistoricalContext)
    assert "auth" in result.summary


# ---------------------------------------------------------------------------
# Synthesizer
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_synthesizer_combines_inputs(session):
    router = _fake_router(
        '{"issue_summary": "Add metrics endpoint",'
        '"candidate_files": [{"path": "src/api.py", "reason": "where routes live"}],'
        '"suggested_approach": "Add /metrics route in src/api.py and a unit test.",'
        '"open_questions": ["Should it be Prometheus format?"],'
        '"risks": ["Endpoint may need auth"],'
        '"estimated_effort": "few-hours"}'
    )
    report = run_synthesizer(
        router,
        issue_reqs=IssueRequirements(summary="Add metrics endpoint"),
        repo_map=RepoMap(candidate_files=[]),
        history=HistoricalContext(summary=""),
        repo_full_name="x/y", issue_number=1, session=session,
    )
    assert report.estimated_effort == "few-hours"
    assert report.candidate_files[0].path == "src/api.py"
    assert "Prometheus" in report.open_questions[0]


@pytest.mark.unit
def test_synthesizer_fallback_on_parse_failure(session):
    router = _fake_router("not json")
    report = run_synthesizer(
        router,
        issue_reqs=IssueRequirements(summary="original summary"),
        repo_map=RepoMap(candidate_files=[]),
        history=HistoricalContext(summary=""),
        repo_full_name="x/y", issue_number=1, session=session,
    )
    assert report.issue_summary == "original summary"
    assert "synthesis failed" in report.suggested_approach


@pytest.mark.unit
def test_report_to_markdown_renders_all_sections():
    report = InvestigationReport(
        issue_summary="Summary line.",
        candidate_files=[],
        suggested_approach="Do the thing.",
        open_questions=["Q1"],
        risks=["R1"],
        estimated_effort="weekend",
    )
    md = report_to_markdown(
        report=report, repo_full_name="x/y", issue_number=42,
        issue_url="https://github.com/x/y/issues/42",
    )
    assert "x/y#42" in md
    assert "weekend" in md
    assert "Summary line." in md
    assert "Do the thing." in md
    assert "Q1" in md
    assert "R1" in md
