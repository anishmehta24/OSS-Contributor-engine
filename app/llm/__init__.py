"""LLM access layer.

All agent code goes through this module so:
    - Provider failover (Gemini -> Groq) is centralized
    - Every LLM call captures telemetry to the agent_runs table
    - Swapping providers is a one-line change

Public API:
    from app.llm import call_llm, get_router, LLMResult
"""
from app.llm.call import LLMResult, ProvidersExhaustedError, call_llm
from app.llm.router import build_router, get_router

__all__ = [
    "LLMResult",
    "ProvidersExhaustedError",
    "build_router",
    "call_llm",
    "get_router",
]
