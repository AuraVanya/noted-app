from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import OAuthCredential, User
from ..schemas import Connections, MeResponse


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
