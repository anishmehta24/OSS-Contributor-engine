"""FastAPI dependencies.

External resources (GitHub client, Voyage client, LLM router) are created
once at app startup (see lifespan in main.py) and injected per-request.
"""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import sessionmaker_factory
from app.llm.router import build_router as _build_router
from app.tools.github import GitHubClient
from app.tools.voyage_client import VoyageClient

# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def get_db_session() -> Iterator[Session]:
    """Yield a session; commit on success, rollback on exception."""
    sm = sessionmaker_factory()
    with sm() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


SessionDep = Depends(get_db_session)


# ---------------------------------------------------------------------------
# External resources (populated by lifespan, fetched from app.state)
# ---------------------------------------------------------------------------

def get_github_client(request: Request) -> GitHubClient:
    gh = getattr(request.app.state, "github", None)
    if gh is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub client not configured (set GITHUB_TOKEN)",
        )
    return gh


def get_voyage_client(request: Request) -> VoyageClient:
    voyage = getattr(request.app.state, "voyage", None)
    if voyage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voyage client not configured (set VOYAGE_API_KEY)",
        )
    return voyage


def get_llm_router(request: Request):
    router = getattr(request.app.state, "llm_router", None)
    if router is None:
        # Tests / partial-config paths can try to lazy-build here.
        try:
            router = _build_router()
            request.app.state.llm_router = router
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"LLM router not configured: {e}",
            ) from e
    return router


GHDep = Depends(get_github_client)
VoyageDep = Depends(get_voyage_client)
RouterDep = Depends(get_llm_router)


# ---------------------------------------------------------------------------
# Per-user GitHub client (uses the logged-in user's OAuth token)
# ---------------------------------------------------------------------------

# Import here to avoid a circular import at module load time
# (app.auth.dependencies → app.api.dependencies for SessionDep).
from app.auth.dependencies import current_user_github_token  # noqa: E402

_UserTokenDep = Depends(current_user_github_token)


async def get_user_github_client(token: str = _UserTokenDep):
    """Per-request GitHubClient using the logged-in user's OAuth token.

    Closes the underlying httpx client when the request finishes.
    """
    client = GitHubClient(token=token)
    try:
        yield client
    finally:
        await client.close()


UserGHDep = Depends(get_user_github_client)

