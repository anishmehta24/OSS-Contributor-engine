"""GET /health — reports which external services are configured.
GET /features — runtime feature flags the frontend uses to decide what to render."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.api.schemas import HealthResponse
from app.core.config import settings

router = APIRouter(tags=["health"])

VERSION = "0.1.0"  # mirrored from pyproject.toml; manual until Batch 12


class FeaturesResponse(BaseModel):
    """Server-side flags the frontend reads to pick which UI to render.

    Kept separate from /health so it's cacheable and cheap — the frontend
    fetches it on every server render to decide whether to show the Pilot
    panel, which features are disabled on this deployment, etc."""
    pilot_enabled: bool


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


@router.get("/features", response_model=FeaturesResponse)
async def get_features() -> FeaturesResponse:
    """Runtime feature flags. Used by the frontend to hide UI for capabilities
    the current deployment can't actually serve (e.g. the Pilot on free PaaS).
    """
    return FeaturesResponse(pilot_enabled=settings.pilot_enabled)
