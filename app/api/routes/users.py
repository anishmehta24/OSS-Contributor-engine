"""Users endpoints — self-service only (v2).

Logged-in users can only operate on themselves:
    POST   /users/me/profile   — (re)profile the logged-in user
    GET    /users/me           — return cached profile
    GET    /users/me/summary   — lightweight metadata
    DELETE /users/me           — delete own account (cascades skill + investigations)

There is no `/users/{login}` endpoint anymore. CLI tools still work for
admin/dev use; the API is strictly self-service.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.orm import Session

from app.agents.profiles.schemas import SkillProfile
from app.agents.profiles.skill_profiler import profile_user
from app.api.dependencies import RouterDep, SessionDep, UserGHDep
from app.api.schemas import (
    ProfileResponse,
    UserSummary,
)
from app.auth.dependencies import CurrentUserDep
from app.db.models import User

router = APIRouter(prefix="/users", tags=["users"])


def _summary_from(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        github_login=user.github_login,
        github_id=user.github_id,
        name=user.name,
        has_skill_profile=user.skill is not None,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post(
    "/me/profile",
    response_model=ProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def profile_me(
    me: User = CurrentUserDep,
    session: Session = SessionDep,
    gh=UserGHDep,
    router_=RouterDep,
) -> ProfileResponse:
    """(Re)profile the logged-in user using their own OAuth token."""
    profile = await profile_user(
        me.github_login, gh=gh, router=router_, session=session,
    )
    return ProfileResponse(profile=profile)


@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(
    me: User = CurrentUserDep,
) -> ProfileResponse:
    """Return the logged-in user's cached profile."""
    if me.skill is None:
        raise HTTPException(
            status_code=409,
            detail="No profile yet — POST /users/me/profile to build one",
        )
    skill = me.skill
    profile = SkillProfile(
        github_login=me.github_login,
        github_id=me.github_id,
        name=me.name,
        languages=list(skill.languages or []),
        frameworks=list(skill.frameworks or []),
        domains=list(skill.domains or []),
        experience_signal=skill.experience_signal,  # type: ignore[arg-type]
        summary=skill.summary,
        repos_analyzed=len(skill.languages or []),  # placeholder
        profiled_at=skill.updated_at or datetime.now(UTC).replace(tzinfo=None),
    )
    return ProfileResponse(profile=profile)


@router.get("/me/summary", response_model=UserSummary)
async def get_my_summary(me: User = CurrentUserDep) -> UserSummary:
    return _summary_from(me)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(
    me: User = CurrentUserDep,
    session: Session = SessionDep,
) -> None:
    session.delete(me)
