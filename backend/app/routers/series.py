"""
Series-level config endpoints. Phase 4 adds the "Always add to Project
Context" links; Phase 6 will add Confluence series config alongside.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import MeetingSeries, ProjectContext, SeriesContextLink, User


router = APIRouter(prefix="/api/series", tags=["series"])


class LinkInput(BaseModel):
    project_context_id: int = Field(..., alias="projectContextId")
    enabled: bool

    model_config = {"populate_by_name": True}


class UpdateLinksBody(BaseModel):
    links: list[LinkInput] = Field(default_factory=list)


def _link_row(
    project_context_id: int,
    label: str,
    enabled: bool,
) -> dict[str, Any]:
    return {
        "projectContextId": project_context_id,
        "label": label,
        "enabled": enabled,
    }


@router.get("/{series_id}/context-links")
async def list_series_context_links(
    series_id: int = Path(..., ge=1),
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """
    Return one row per registered Project Context, with the link's
    `enabled` state for this series (false if no link row exists). The UI
    renders this as a checklist.
    """
    series = await session.get(MeetingSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    # All registered contexts, alphabetically by label for a stable UI
    contexts_q = await session.execute(
        select(ProjectContext).order_by(ProjectContext.label.asc())
    )
    contexts = contexts_q.scalars().all()
    if not contexts:
        return []

    links_q = await session.execute(
        select(SeriesContextLink).where(SeriesContextLink.series_id == series_id)
    )
    enabled_by_ctx = {
        link.project_context_id: link.enabled for link in links_q.scalars().all()
    }

    return [
        _link_row(c.id, c.label, enabled_by_ctx.get(c.id, False)) for c in contexts
    ]


@router.put("/{series_id}/context-links")
async def update_series_context_links(
    body: UpdateLinksBody,
    series_id: int = Path(..., ge=1),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Upsert each `(series, project_context)` pair to the requested
    `enabled` value. Disabling keeps the row so the sync's audit log stays
    coherent; re-enabling later picks up where we left off."""
    series = await session.get(MeetingSeries, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series not found")

    # Snapshot existing rows for this series
    existing_q = await session.execute(
        select(SeriesContextLink).where(SeriesContextLink.series_id == series_id)
    )
    existing_by_ctx: dict[int, SeriesContextLink] = {
        row.project_context_id: row for row in existing_q.scalars().all()
    }

    # Apply each requested change
    for link_in in body.links:
        row = existing_by_ctx.get(link_in.project_context_id)
        if row is None:
            ctx = await session.get(ProjectContext, link_in.project_context_id)
            if ctx is None:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Project Context {link_in.project_context_id} does not exist"
                    ),
                )
            session.add(
                SeriesContextLink(
                    series_id=series_id,
                    project_context_id=link_in.project_context_id,
                    enabled=link_in.enabled,
                    created_by_user_id=user.id,
                )
            )
        else:
            row.enabled = link_in.enabled

    await session.commit()

    # Echo the resulting list (same shape as GET) for an easy client cache update
    return await list_series_context_links(series_id, _user=user, session=session)
