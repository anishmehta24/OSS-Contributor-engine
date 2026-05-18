"""Thin wrapper around `Router.completion` that:
    - Times the call
    - Extracts which provider/model actually served (after fallback chain)
    - Optionally parses a Pydantic model from the response (structured output)
    - Persists telemetry to the agent_runs table (if a session is provided)

Every agent's LLM call goes through here so we have one place to evolve
prompt-cache logic, cost accounting, retries, etc.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TypeVar

import structlog
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.db.models import AgentRun

log = structlog.get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    text: str
    provider: str       # gemini / groq / ollama
    model: str          # full model id, e.g. "gemini/gemini-2.5-flash"
    fallback_depth: int  # 0 if primary served, 1 for first fallback, etc.
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int


def _provider_from_model(model_id: str) -> str:
    return model_id.split("/", 1)[0] if "/" in model_id else model_id


def _depth_for_model(router, served_model: str) -> int:
    for i, entry in enumerate(router.model_list):
        if entry["litellm_params"]["model"] == served_model:
            return i
    return 0


def _record_telemetry(
    session: Session | None,
    *,
    agent_name: str,
    investigation_id: str | None,
    user_id: int | None,
    result: LLMResult,
    status: str,
    error: str | None,
) -> None:
    if session is None:
        return
    try:
        run = AgentRun(
            investigation_id=investigation_id,
            user_id=user_id,
            agent_name=agent_name,
            provider=result.provider,
            model=result.model,
            fallback_depth=result.fallback_depth,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
            status=status,
            error=error,
        )
        session.add(run)
        session.commit()
    except Exception as e:  # never let telemetry break the caller
        log.warning("agent_run_persist_failed", error=str(e))


def call_llm(
    router,
    messages: list[dict],
    *,
    agent_name: str,
    response_model: type[T] | None = None,
    investigation_id: str | None = None,
    user_id: int | None = None,
    session: Session | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = 2048,
) -> tuple[LLMResult, T | None]:
    """Call the router and return (result_metadata, parsed_model_or_none).

    If `response_model` is given, the wrapper requests JSON output from the
    provider and validates the response against the Pydantic schema. On
    parse failure, the raw text is still returned in result.text and the
    parsed value is None.
    """
    kwargs: dict = {
        "model": "agent-llm",
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if response_model is not None:
        kwargs["response_format"] = {"type": "json_object"}

    log.info(
        "llm_call_starting",
        agent=agent_name,
        has_response_model=response_model is not None,
    )

    start = time.monotonic()
    try:
        response = router.completion(**kwargs)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        empty = LLMResult(
            text="", provider="unknown", model="unknown", fallback_depth=-1,
            tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=latency_ms,
        )
        _record_telemetry(
            session, agent_name=agent_name,
            investigation_id=investigation_id, user_id=user_id,
            result=empty, status="error", error=str(e)[:500],
        )
        raise

    latency_ms = int((time.monotonic() - start) * 1000)

    served_model = response.model
    text = response.choices[0].message.content or ""
    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    cost = (
        getattr(response, "_hidden_params", {}).get("response_cost")
        if hasattr(response, "_hidden_params")
        else 0.0
    ) or 0.0

    result = LLMResult(
        text=text,
        provider=_provider_from_model(served_model),
        model=served_model,
        fallback_depth=_depth_for_model(router, served_model),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=float(cost),
        latency_ms=latency_ms,
    )

    parsed: T | None = None
    if response_model is not None:
        try:
            parsed = response_model.model_validate_json(text)
        except (ValidationError, json.JSONDecodeError) as e:
            log.warning("llm_parse_failed", agent=agent_name, error=str(e)[:200])

    _record_telemetry(
        session, agent_name=agent_name,
        investigation_id=investigation_id, user_id=user_id,
        result=result, status="success", error=None,
    )

    log.info(
        "llm_call_completed",
        agent=agent_name,
        provider=result.provider,
        model=result.model,
        fallback_depth=result.fallback_depth,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        latency_ms=result.latency_ms,
        parsed_ok=parsed is not None if response_model else None,
    )

    return result, parsed
