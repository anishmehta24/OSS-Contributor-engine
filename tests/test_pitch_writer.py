"""Tests for the Pitch Writer agent."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.pitch.pitch_writer import build_user_message, run_pitch_writer
from app.agents.pitch.schemas import PitchDraft


def _fake_router(json_str: str):
    return SimpleNamespace(
        model_list=[{"litellm_params": {"model": "gemini/gemini-2.5-flash"}}],
        completion=lambda **_: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json_str))],
            model="gemini/gemini-2.5-flash",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=80),
            _hidden_params={"response_cost": 0.0002},
        ),
    )


@pytest.mark.unit
def test_build_user_message_includes_repo_and_report():
    msg = build_user_message(
        repo_full_name="acme/web",
        issue_number=42,
        issue_url="https://x/y/issues/42",
        markdown_report="# Report\nSome content",
    )
    assert "acme/web" in msg
    assert "#42" in msg
    assert "https://x/y/issues/42" in msg
    assert "Some content" in msg


@pytest.mark.unit
def test_build_user_message_truncates_huge_reports():
    huge = "x" * 50_000
    msg = build_user_message(
        repo_full_name="a/b", issue_number=1,
        issue_url="x", markdown_report=huge,
    )
    # Report is truncated to 6000 chars, but the header is still appended
    assert len(msg) < 6500


@pytest.mark.unit
def test_pitch_writer_parses_structured_output(session):
    router = _fake_router(
        '{"comment_md": "I would like to take this on. Based on src/api.py I think a '
        'new route should be added — does this need auth?",'
        ' "asks_questions": true,'
        ' "estimated_timeline": "this weekend",'
        ' "tone": "respectful"}'
    )
    result = run_pitch_writer(
        router,
        repo_full_name="acme/web",
        issue_number=42,
        issue_url="https://x/y/issues/42",
        markdown_report="# Report",
        session=session,
    )
    assert isinstance(result, PitchDraft)
    assert "take this on" in result.comment_md
    assert result.asks_questions is True
    assert result.estimated_timeline == "this weekend"
    assert result.tone == "respectful"


@pytest.mark.unit
def test_pitch_writer_returns_fallback_on_parse_failure(session):
    router = _fake_router("not valid json")
    result = run_pitch_writer(
        router,
        repo_full_name="acme/web",
        issue_number=42,
        issue_url="https://x/y/issues/42",
        markdown_report="# Report",
        session=session,
    )
    # Fallback comment is plain English
    assert "take a look" in result.comment_md.lower()
    assert result.asks_questions is False


@pytest.mark.unit
def test_pitch_writer_records_telemetry(session):
    from sqlalchemy import select

    from app.db.models import AgentRun

    router = _fake_router(
        '{"comment_md": "ok", "asks_questions": false, '
        '"estimated_timeline": null, "tone": "respectful"}'
    )
    run_pitch_writer(
        router,
        repo_full_name="a/b", issue_number=1,
        issue_url="x", markdown_report="x", session=session,
    )
    runs = session.execute(select(AgentRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].agent_name == "pitch_writer"
