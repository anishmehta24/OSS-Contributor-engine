"""Tests for the Reviewer loop.

Focus on the state machine: given a sequence of patch + test outcomes,
does the Reviewer make the right decisions? We mock both `write_patch`
and `run_tests` so no LLM or Docker is needed.
"""
from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

from app.agents.explorer.schemas import FileCandidate
from app.agents.patcher import AppliedEdit, PatchResult
from app.agents.reviewer import review_and_iterate
from app.agents.reviewer.reviewer import _decide
from app.agents.test_runner.schemas import PhaseResult

# Aliased so pytest doesn't auto-collect this pydantic model as a test
# class (its name starts with `Test`).
from app.agents.test_runner.schemas import TestRunResult as _TestRunResult
from app.sandbox import Workspace

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git_repo(tmp_path: Path) -> tuple[Workspace, Path]:
    """Materialize a real git repo so the workspace-reset commands have
    something to act on."""
    ws = Workspace(investigation_id="inv-rev", host_path=tmp_path)
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    for argv in (
        ["git", "init", "-q"],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
        ["git", "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
    ):
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
    return ws, repo


def _patch_ok(diff: str = "diff --git a/x b/x\n", *, summary: str = "ok") -> PatchResult:
    return PatchResult(
        success=True,
        summary=summary,
        confidence=0.8,
        edits_attempted=1,
        edits_applied=[AppliedEdit(path="src.py", explanation="ok",
                                   bytes_added=10, bytes_removed=2)],
        unified_diff=diff,
    )


def _patch_failed(error: str = "no edits") -> PatchResult:
    return PatchResult(
        success=False, summary="", confidence=0.1, edits_attempted=0, error=error,
    )


def _test_pass() -> _TestRunResult:
    return _TestRunResult(
        language="python",
        classification="pass",
        summary="all good",
        phases=[PhaseResult(name="syntax_check", argv=["python", "-m", "py_compile"],
                            exit_code=0, duration_s=0.1)],
        duration_s=0.1,
    )


def _test_fail(excerpt: str = "SyntaxError: bad") -> _TestRunResult:
    return _TestRunResult(
        language="python",
        classification="fail",
        summary="syntax broken",
        phases=[PhaseResult(name="syntax_check", argv=["python", "-m", "py_compile"],
                            exit_code=1, duration_s=0.1, stderr=excerpt)],
        duration_s=0.1,
        failure_excerpt=excerpt,
    )


def _test_needs_env() -> _TestRunResult:
    return _TestRunResult(
        language="python",
        classification="needs_env",
        summary="deps missing",
        phases=[],
        duration_s=0.1,
        failure_excerpt="ModuleNotFoundError",
    )


def _test_error() -> _TestRunResult:
    return _TestRunResult(
        language="python", classification="error", summary="infra broke",
        phases=[], duration_s=0.05,
    )


class _FakePatcher:
    """Returns canned PatchResults in order. Records prior_attempts so we
    can assert the Reviewer fed them in correctly."""
    def __init__(self, results: Iterable[PatchResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append({
            "candidates": kwargs.get("candidates"),
            "prior_attempts": list(kwargs.get("prior_attempts") or []),
        })
        if not self._results:
            raise RuntimeError("FakePatcher: out of canned results")
        return self._results.pop(0)


class _FakeTester:
    def __init__(self, results: Iterable[_TestRunResult]):
        self._results = list(results)
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if not self._results:
            raise RuntimeError("FakeTester: out of canned results")
        return self._results.pop(0)


def _candidates() -> list[FileCandidate]:
    return [FileCandidate(path="src.py", confidence=0.9)]


# ---------------------------------------------------------------------------
# Pure decision-table tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_decide_pass_is_accept():
    assert _decide(_test_pass())[0] == "accept"


@pytest.mark.unit
def test_decide_fail_is_retry():
    assert _decide(_test_fail())[0] == "retry"


@pytest.mark.unit
def test_decide_needs_env_is_accept_with_caveat():
    decision, reason = _decide(_test_needs_env())
    assert decision == "accept"
    assert "couldn't run" in reason


@pytest.mark.unit
def test_decide_error_is_give_up():
    assert _decide(_test_error())[0] == "give_up"


@pytest.mark.unit
def test_decide_no_project_is_give_up():
    nopp = _TestRunResult(
        language="unknown", classification="no_project", summary="x",
        phases=[], duration_s=0.0,
    )
    assert _decide(nopp)[0] == "give_up"


# ---------------------------------------------------------------------------
# Loop integration (state machine, with mocks)
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_loop_accepts_on_first_pass(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    patcher = _FakePatcher([_patch_ok("diff #1")])
    tester = _FakeTester([_test_pass()])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
    )
    assert result.success is True
    assert len(result.attempts) == 1
    assert result.accepted_attempt_number == 1
    assert result.final_diff == "diff #1"
    # Patcher called once with no prior attempts.
    assert len(patcher.calls) == 1
    assert patcher.calls[0]["prior_attempts"] == []


@pytest.mark.integration
async def test_loop_retries_on_fail_then_accepts(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    patcher = _FakePatcher([_patch_ok("diff #1"), _patch_ok("diff #2")])
    tester = _FakeTester([_test_fail("BOOM"), _test_pass()])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
        max_attempts=3,
    )
    assert result.success is True
    assert len(result.attempts) == 2
    assert result.attempts[0].decision == "retry"
    assert result.attempts[1].decision == "accept"
    assert result.accepted_attempt_number == 2
    assert result.final_diff == "diff #2"
    # Second patcher call must have received the prior attempt's failure.
    assert len(patcher.calls[1]["prior_attempts"]) == 1
    prior = patcher.calls[1]["prior_attempts"][0]
    assert prior.attempt_number == 1
    assert prior.failure_excerpt == "BOOM"
    assert prior.edits_applied_paths == ["src.py"]


@pytest.mark.integration
async def test_loop_gives_up_when_patch_generation_fails(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    patcher = _FakePatcher([_patch_failed("LLM returned 0 edits")])
    tester = _FakeTester([])  # never reached
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
    )
    assert result.success is False
    assert tester.calls == 0
    assert result.attempts[0].decision == "give_up"
    assert result.attempts[0].test_result is None
    assert "LLM returned 0 edits" in result.summary


@pytest.mark.integration
async def test_loop_stops_when_diff_repeats(tmp_path, monkeypatch):
    """LLM stuck on the same approach — don't burn 3 attempts on identical
    diffs."""
    ws, repo = _git_repo(tmp_path)
    same_diff = "diff --git a/x b/x\n@@ identical @@\n"
    patcher = _FakePatcher([_patch_ok(same_diff), _patch_ok(same_diff)])
    tester = _FakeTester([_test_fail("same broken thing")])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
        max_attempts=3,
    )
    assert result.success is False
    # Two attempts: first ran tests, second short-circuited on diff equality.
    assert len(result.attempts) == 2
    assert result.attempts[1].decision == "give_up"
    assert "same diff" in result.attempts[1].decision_reason
    # Tests only ran on attempt 1.
    assert tester.calls == 1


@pytest.mark.integration
async def test_loop_gives_up_on_infra_error(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    patcher = _FakePatcher([_patch_ok()])
    tester = _FakeTester([_test_error()])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
    )
    assert result.success is False
    assert result.attempts[-1].decision == "give_up"
    assert "infra error" in result.attempts[-1].decision_reason


@pytest.mark.integration
async def test_needs_env_counts_as_success(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    patcher = _FakePatcher([_patch_ok("diff w/ env issue")])
    tester = _FakeTester([_test_needs_env()])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
    )
    # Tests couldn't run, but the patch itself didn't break anything —
    # caller can still consider this success with caveat surfaced in summary.
    assert result.success is True
    assert result.accepted_attempt_number == 1
    assert "missing env deps" in result.attempts[0].decision_reason


@pytest.mark.integration
async def test_loop_exhausts_attempts(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    # 2 distinct failing patches, max_attempts=2 — should run both and give up.
    patcher = _FakePatcher([_patch_ok("diff A"), _patch_ok("diff B")])
    tester = _FakeTester([_test_fail("err1"), _test_fail("err2")])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    result = await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
        max_attempts=2,
    )
    assert result.success is False
    assert len(result.attempts) == 2
    assert "Out of attempts" in result.summary
    # Both attempts were 'retry' decisions; loop ran out.
    assert all(a.decision == "retry" for a in result.attempts)


# ---------------------------------------------------------------------------
# Workspace reset is invoked between retries
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_workspace_is_reset_between_attempts(tmp_path, monkeypatch):
    ws, repo = _git_repo(tmp_path)
    # Simulate the patch by actually writing a stray file each turn —
    # if the reset works, it'll be gone before the next attempt's test.
    (repo / "extra.py").write_text("garbage\n", encoding="utf-8")
    assert (repo / "extra.py").exists()

    patcher = _FakePatcher([_patch_ok("d1"), _patch_ok("d2")])
    tester = _FakeTester([_test_fail("x"), _test_pass()])
    monkeypatch.setattr("app.agents.reviewer.reviewer.write_patch", patcher)
    monkeypatch.setattr("app.agents.reviewer.reviewer.run_tests", tester)

    await review_and_iterate(
        repo="acme/x", repo_path=repo, workspace=ws,
        issue_title="x", issue_body=None, issue_labels=[],
        candidates=_candidates(), router=object(),
    )
    # After attempt 1 (decision=retry), git clean -fd should have removed
    # the untracked extra.py.
    assert not (repo / "extra.py").exists()
