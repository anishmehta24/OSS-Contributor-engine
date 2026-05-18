"""GET /health — reports which external services are configured."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.schemas import HealthResponse

router = APIRouter(tags=["health"])

VERSION = "0.1.0"  # mirrored from pyproject.toml; manual until Batch 12


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Liveness + configuration report. Always returns 200 if the app is up."""
    embedder = getattr(request.app.state, "embedder", None)
    return HealthResponse(
        status="ok",
        version=VERSION,
        services={
            "github": getattr(request.app.state, "github", None) is not None,
            "embedder": embedder is not None,
            "voyage": embedder is not None,  # back-compat alias
            "llm_router": getattr(request.app.state, "llm_router", None) is not None,
        },
    )
