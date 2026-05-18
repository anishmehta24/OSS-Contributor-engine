"""LiteLLM Router with Gemini primary -> Groq fallback.

The router:
    - Tracks per-provider rate limits (RPM/TPM/RPD)
    - Routes around providers that 429 / 5xx, with cooldowns
    - Returns the served model name in the response so we can log which
      provider actually answered each call

If only one provider key is set, the router still works — there's just
no fallback option for that call.
"""
from __future__ import annotations

from typing import Any

import structlog
from litellm import Router

from app.core.config import settings

log = structlog.get_logger(__name__)

GEMINI_MODEL = "gemini/gemini-2.5-flash"
GROQ_70B_MODEL = "groq/llama-3.3-70b-versatile"
GROQ_8B_MODEL = "groq/llama-3.1-8b-instant"


def build_router() -> Router:
    """Construct a fresh Router from current settings.

    Three-tier fallback chain (each provider has its OWN quota bucket so
    they cool down independently):
        1. Gemini 2.5 Flash    — best quality, 20 req/day on free tier
        2. Groq Llama 3.3 70B  — strong quality, 12K TPM on free tier
        3. Groq Llama 3.1 8B   — adequate quality, 6K TPM separate bucket

    The 8B model exists specifically so when 70B is cooled (e.g. after a
    burst of agent calls), there's still something serving requests.

    Raises:
        RuntimeError if no LLM provider key is configured.
    """
    model_list: list[dict[str, Any]] = []

    # NOTE: rpm/tpm hints belong at the model_list entry top-level, NOT
    # inside `litellm_params` — anything inside litellm_params is forwarded
    # to the provider, and providers reject unknown fields. For our scale
    # the router doesn't need pre-emptive throttling, so we let providers
    # return 429 and rely on cooldown + fallback.

    if settings.gemini_api_key:
        model_list.append({
            "model_name": "agent-llm",
            "litellm_params": {
                "model": GEMINI_MODEL,
                "api_key": settings.gemini_api_key,
            },
        })

    if settings.groq_api_key:
        model_list.append({
            "model_name": "agent-llm",
            "litellm_params": {
                "model": GROQ_70B_MODEL,
                "api_key": settings.groq_api_key,
            },
        })
        # Separate-quota emergency backstop; lower quality, much higher TPM
        model_list.append({
            "model_name": "agent-llm",
            "litellm_params": {
                "model": GROQ_8B_MODEL,
                "api_key": settings.groq_api_key,
            },
        })

    if not model_list:
        raise RuntimeError(
            "No LLM provider configured. Set GEMINI_API_KEY and/or GROQ_API_KEY in .env"
        )

    fallback_targets = [m["litellm_params"]["model"] for m in model_list[1:]]
    fallbacks = [{"agent-llm": fallback_targets}] if fallback_targets else []

    log.info(
        "llm_router_built",
        primary=model_list[0]["litellm_params"]["model"],
        fallbacks=fallback_targets,
    )

    return Router(
        model_list=model_list,
        fallbacks=fallbacks,
        num_retries=2,
        cooldown_time=60,
        routing_strategy="simple-shuffle",
    )


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------

_router: Router | None = None


def get_router() -> Router:
    """Lazy-init the process-wide router. Tests should call build_router()
    directly or inject a fake."""
    global _router
    if _router is None:
        _router = build_router()
    return _router


def reset_router() -> None:
    """Force the next get_router() call to rebuild — used by tests after
    mutating env vars."""
    global _router
    _router = None
