"""GET /users/me/matches — ranked OSS issues for the logged-in user."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.agents.triager.triager import rank_for_user
from app.api.dependencies import SessionDep, VoyageDep
from app.api.schemas import RankedMatchesResponse
from app.auth.dependencies import CurrentUserDep
from app.db.models import User

router = APIRouter(prefix="/users", tags=["matches"])


@router.get("/me/matches", response_model=RankedMatchesResponse)
async def get_my_matches(
    request: Request,
    top: int = Query(default=10, ge=1, le=50),
    difficulty: str = Query(default="any", pattern="^(any|easy|medium|hard)$"),
    explain: bool = Query(default=True),
    mode: str = Query(default="general", pattern="^(general|gsoc)$"),
    me: User = CurrentUserDep,
    session: Session = SessionDep,
    voyage=VoyageDep,
) -> RankedMatchesResponse:
    """Return top-N ranked issues for the logged-in user.

    `explain=true` triggers a batched LLM call to add a "why it fits" line
    per match. Set false to skip and avoid LLM cost.

    `mode="gsoc"` filters candidate issues to those whose repo owner is
    listed in the gsoc_orgs table (seeded + scraped — see Batches 17/18).
    """
    llm_router = getattr(request.app.state, "llm_router", None)
    use_explain = explain and llm_router is not None

    try:
        matches = await rank_for_user(
            github_login=me.github_login,
            session=session,
            embedder=voyage,
            router=llm_router,
            difficulty_pref=difficulty,  # type: ignore[arg-type]
            top_n=top,
            explain=use_explain,
            mode=mode,  # type: ignore[arg-type]
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return RankedMatchesResponse(
        github_login=me.github_login,
        count=len(matches),
        matches=matches,
    )
