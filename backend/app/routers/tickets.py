"""
Tickets endpoints — live Jira reads (no persistence per spec §5).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import OAuthCredential, User
from ..services.atlassian import (
    AtlassianAuthError,
    get_issue,
    get_valid_atlassian_token,
    list_assigned_issues,
)
from ..services.demo_filters import jira_project_visible


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


async def _cloud_id_for(session: AsyncSession, user_id: int) -> str:
    cred = (
        await session.execute(
            select(OAuthCredential).where(
                OAuthCredential.user_id == user_id,
                OAuthCredential.provider == "atlassian",
            )
        )
    ).scalar_one_or_none()
    if cred is None or not cred.atlassian_cloud_id:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Atlassian is not connected.",
        )
    return cred.atlassian_cloud_id


@router.get("")
async def list_tickets(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Returns `{ projects: [...], tickets: [...] }` in one call.

    The project list is derived from the tickets that came back — that's
    what the UI's filter chips need (only show projects the user has
    tickets in)."""
    cloud_id = await _cloud_id_for(session, user.id)
    try:
        token = await get_valid_atlassian_token(session, user.id)
    except AtlassianAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        tickets = await list_assigned_issues(token, cloud_id)
    except AtlassianAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Demo-mode project allowlist — drop tickets in disallowed projects.
    tickets = [
        t for t in tickets if jira_project_visible((t.get("project") or {}).get("name", ""))
    ]

    # Derive project list (unique, sorted by name)
    seen: dict[str, dict[str, Any]] = {}
    for t in tickets:
        proj = t.get("project") or {}
        key = proj.get("key")
        if key and key not in seen:
            seen[key] = proj
    projects = sorted(seen.values(), key=lambda p: p.get("name", ""))

    return {"projects": projects, "tickets": tickets}


@router.get("/{issue_key}")
async def get_ticket(
    issue_key: str = Path(..., min_length=1, max_length=64),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    cloud_id = await _cloud_id_for(session, user.id)
    try:
        token = await get_valid_atlassian_token(session, user.id)
    except AtlassianAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        ticket = await get_issue(token, cloud_id, issue_key)
    except AtlassianAuthError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from exc
        raise HTTPException(status_code=502, detail=msg) from exc

    # Demo-mode allowlist — hide as 404
    if not jira_project_visible((ticket.get("project") or {}).get("name", "")):
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket
