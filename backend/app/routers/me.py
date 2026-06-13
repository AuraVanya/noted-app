from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import OAuthCredential, User, UserJiraProjectPin
from ..schemas import Connections, MeResponse
from ..services.atlassian import (
    AtlassianAuthError,
    get_myself,
    get_valid_atlassian_token,
)


router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me", response_model=MeResponse, response_model_by_alias=True)
async def get_me(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeResponse:
    result = await session.execute(
        select(OAuthCredential.provider).where(OAuthCredential.user_id == user.id)
    )
    providers = {row[0] for row in result.all()}
    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_initials=user.avatar_initials,
        connections=Connections(
            google="google" in providers,
            atlassian="atlassian" in providers,
        ),
    )


# --- Jira project pins ------------------------------------------------------


class JiraPinsBody(BaseModel):
    project_keys: list[str] = Field(default_factory=list, alias="projectKeys")

    model_config = {"populate_by_name": True}


@router.get("/me/jira-pins")
async def list_jira_pins(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[str]]:
    """Return the user's pinned Jira project keys, ordered by pin time
    (earliest first — gives a stable display order)."""
    result = await session.execute(
        select(UserJiraProjectPin.project_key)
        .where(UserJiraProjectPin.user_id == user.id)
        .order_by(UserJiraProjectPin.created_at.asc())
    )
    return {"projectKeys": [row[0] for row in result.all()]}


@router.put("/me/jira-pins")
async def replace_jira_pins(
    body: JiraPinsBody,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, list[str]]:
    """Replace the pinned-keys set. Order in `body.projectKeys` is the
    intended display order; we encode that by deleting and re-inserting in
    sequence so `created_at` reflects the user's chosen order."""
    # Dedupe + trim while preserving order
    seen: set[str] = set()
    keys: list[str] = []
    for k in body.project_keys:
        k = k.strip()
        if not k or k in seen:
            continue
        seen.add(k)
        keys.append(k)

    # Wipe existing pins for this user
    existing_q = await session.execute(
        select(UserJiraProjectPin).where(UserJiraProjectPin.user_id == user.id)
    )
    for row in existing_q.scalars().all():
        await session.delete(row)
    await session.flush()

    # Insert in the order received so created_at sorts the same way
    for k in keys:
        session.add(UserJiraProjectPin(user_id=user.id, project_key=k))

    await session.commit()
    return {"projectKeys": keys}


# --- Atlassian identity ----------------------------------------------------


@router.get("/me/atlassian-identity")
async def get_atlassian_identity(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Surface the Atlassian user behind the OAuth token (via /rest/api/3/myself).
    Lets the UI show "Connected as <name>" and lets the user spot a
    wrong-account OAuth grant (e.g. accidentally connected via personal vs
    work account)."""
    cred = (
        await session.execute(
            select(OAuthCredential).where(
                OAuthCredential.user_id == user.id,
                OAuthCredential.provider == "atlassian",
            )
        )
    ).scalar_one_or_none()
    if cred is None or not cred.atlassian_cloud_id:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Atlassian is not connected.",
        )
    try:
        token = await get_valid_atlassian_token(session, user.id)
        return await get_myself(token, cred.atlassian_cloud_id)
    except AtlassianAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
