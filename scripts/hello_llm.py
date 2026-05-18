"""Smoke test: LiteLLM Router with Gemini primary, Groq fallback.

Verifies:
    - LiteLLM is installed and importable
    - Gemini (or Groq, on fallback) responds to a trivial prompt
    - Reports which provider actually served the response

Usage:  uv run python scripts/hello_llm.py

Skips gracefully if neither GEMINI_API_KEY nor GROQ_API_KEY is set yet.
"""
import sys

from app.core.config import settings
from app.core.logging import configure_logging, get_logger


def main() -> int:
    configure_logging()
    log = get_logger("hello_llm")

    if not settings.has_any_llm:
        print("No LLM API keys set. Add GEMINI_API_KEY and/or GROQ_API_KEY to .env, then re-run.")
        return 0

    from litellm import Router

    model_list = []
    if settings.gemini_api_key:
        model_list.append({
            "model_name": "agent-llm",
            "litellm_params": {
                "model": "gemini/gemini-2.5-flash",
                "api_key": settings.gemini_api_key,
            },
        })
    if settings.groq_api_key:
        model_list.append({
            "model_name": "agent-llm",
            "litellm_params": {
                "model": "groq/llama-3.3-70b-versatile",
                "api_key": settings.groq_api_key,
            },
        })

    router = Router(
        model_list=model_list,
        num_retries=2,
        cooldown_time=30,
    )

    log.info("llm_call_starting", providers=[m["litellm_params"]["model"] for m in model_list])
    response = router.completion(
        model="agent-llm",
        messages=[{"role": "user", "content": "Reply with exactly: HELLO"}],
        max_tokens=20,
    )

    served_by = response.model
    text = response.choices[0].message.content.strip()
    usage = response.usage

    print(f"Provider served: {served_by}")
    print(f"Response:        {text!r}")
    print(f"Tokens (in/out): {usage.prompt_tokens}/{usage.completion_tokens}")
    print("\nLiteLLM router OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
