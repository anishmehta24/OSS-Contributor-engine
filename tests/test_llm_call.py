"""Tests for the LLM router and the call_llm wrapper.

We don't actually hit Gemini/Groq here — we inject a fake Router that returns
canned responses, and assert that:
    - call_llm parses structured output
    - telemetry is persisted to agent_runs
    - parse failures are non-fatal
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.db.models import AgentRun
from app.llm.call import call_llm
from app.llm.router import build_router, reset_router

# ---------------------------------------------------------------------------
# Router build tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_router_raises_when_no_keys(monkeypatch):
    monkeypatch.setattr("app.llm.router.settings",
                        SimpleNamespace(gemini_api_key="", groq_api_key=""))
    reset_router()
    with pytest.raises(RuntimeError, match="No LLM provider"):
        build_router()


@pytest.mark.unit
def test_build_router_with_only_gemini(monkeypatch):
    monkeypatch.setattr("app.llm.router.settings",
                        SimpleNamespace(gemini_api_key="g_key", groq_api_key=""))
    reset_router()
    router = build_router()
    assert len(router.model_list) == 1
    assert router.model_list[0]["litellm_params"]["model"].startswith("gemini/")


@pytest.mark.unit
def test_build_router_with_both_providers(monkeypatch):
    """Three deployments: Gemini primary, Groq 70B fallback, Groq 8B backstop."""
    monkeypatch.setattr("app.llm.router.settings",
                        SimpleNamespace(gemini_api_key="g", groq_api_key="r"))
    reset_router()
    router = build_router()
    assert len(router.model_list) == 3
    assert router.model_list[0]["litellm_params"]["model"].startswith("gemini/")
    assert router.model_list[1]["litellm_params"]["model"] == "groq/llama-3.3-70b-versatile"
    assert router.model_list[2]["litellm_params"]["model"] == "groq/llama-3.1-8b-instant"


# ---------------------------------------------------------------------------
# call_llm tests with a fake Router
# ---------------------------------------------------------------------------

@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _FakeResponse:
    def __init__(self, content: str, model: str, tokens_in: int = 50, tokens_out: int = 100):
        self.choices = [_FakeChoice(message=_FakeMessage(content=content))]
        self.model = model
        self.usage = _FakeUsage(prompt_tokens=tokens_in, completion_tokens=tokens_out)
        self._hidden_params = {"response_cost": 0.0001}


class _FakeRouter:
    """Minimal stand-in for litellm.Router."""

    def __init__(self, response: _FakeResponse, served_model: str):
        self._response = response
        self.model_list = [
            {"litellm_params": {"model": "gemini/gemini-2.5-flash"}},
            {"litellm_params": {"model": "groq/llama-3.3-70b-versatile"}},
        ]
        self._served_model = served_model

    def completion(self, **_):
        return self._response


class _DemoOutput(BaseModel):
    answer: str
    confidence: float


@pytest.mark.unit
def test_call_llm_parses_structured_output(session):
    response = _FakeResponse(
        content='{"answer": "yes", "confidence": 0.9}',
        model="gemini/gemini-2.5-flash",
    )
    router = _FakeRouter(response, served_model="gemini/gemini-2.5-flash")
    result, parsed = call_llm(
        router,
        messages=[{"role": "user", "content": "hi"}],
        agent_name="demo",
        response_model=_DemoOutput,
        session=session,
    )
    assert result.provider == "gemini"
    assert result.model == "gemini/gemini-2.5-flash"
    assert result.fallback_depth == 0
    assert result.tokens_in == 50
    assert result.tokens_out == 100
    assert parsed is not None
    assert parsed.answer == "yes"
    assert parsed.confidence == 0.9


@pytest.mark.unit
def test_call_llm_persists_telemetry(session):
    response = _FakeResponse(content="ok", model="gemini/gemini-2.5-flash")
    router = _FakeRouter(response, served_model="gemini/gemini-2.5-flash")
    call_llm(
        router,
        messages=[{"role": "user", "content": "hi"}],
        agent_name="demo",
        session=session,
    )
    runs = session.execute(select(AgentRun)).scalars().all()
    assert len(runs) == 1
    run = runs[0]
    assert run.agent_name == "demo"
    assert run.provider == "gemini"
    assert run.tokens_in == 50
    assert run.tokens_out == 100
    assert run.status == "success"


@pytest.mark.unit
def test_call_llm_fallback_depth_when_groq_serves(session):
    response = _FakeResponse(content="ok", model="groq/llama-3.3-70b-versatile")
    router = _FakeRouter(response, served_model="groq/llama-3.3-70b-versatile")
    result, _ = call_llm(
        router,
        messages=[{"role": "user", "content": "hi"}],
        agent_name="demo",
        session=session,
    )
    assert result.provider == "groq"
    assert result.fallback_depth == 1


@pytest.mark.unit
def test_call_llm_parse_failure_is_non_fatal(session):
    response = _FakeResponse(
        content="not json at all",
        model="gemini/gemini-2.5-flash",
    )
    router = _FakeRouter(response, served_model="gemini/gemini-2.5-flash")
    result, parsed = call_llm(
        router,
        messages=[{"role": "user", "content": "hi"}],
        agent_name="demo",
        response_model=_DemoOutput,
        session=session,
    )
    assert parsed is None
    assert result.text == "not json at all"
    # telemetry still recorded as success (LLM call worked, parsing failed)
    runs = session.execute(select(AgentRun)).scalars().all()
    assert runs[0].status == "success"


@pytest.mark.unit
def test_call_llm_records_error_when_router_raises(session):
    class _BoomRouter(_FakeRouter):
        def completion(self, **_):
            raise RuntimeError("provider down")

    router = _BoomRouter(
        _FakeResponse("", "gemini/gemini-2.5-flash"),
        served_model="gemini/gemini-2.5-flash",
    )
    with pytest.raises(RuntimeError, match="provider down"):
        call_llm(
            router,
            messages=[{"role": "user", "content": "hi"}],
            agent_name="demo",
            session=session,
        )
    runs = session.execute(select(AgentRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "error"
    assert "provider down" in (runs[0].error or "")
