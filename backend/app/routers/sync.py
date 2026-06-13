"""
Sync routes. Currently only the dev/manual trigger; the periodic scheduler
calls the same `sync_user` function directly without going through HTTP.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import User
from ..services.sync import sync_user


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.post("/run")
async def run_sync(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Run an ingestion pass for the signed-in user, return a summary."""
    summary = await sync_user(session, user.id)
    return summary.as_dict()
