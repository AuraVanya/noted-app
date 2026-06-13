"""
Minutes endpoints. List of past occurrences + detail with extracted
summary text and signed URLs for the original PDFs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from ..db import get_session
from ..deps import current_user
from ..models import Meeting, SeriesContextLink, User
from ..services.file_urls import sign_file_url


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


def _serialize_attendees(value: Any) -> list[dict[str, str]]:
    """Normalize the JSON column into a stable shape for the API."""
    if not value:
        return []
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for a in value:
        if not isinstance(a, dict):
            continue
        out.append({
            "email": a.get("email", ""),
            "displayName": a.get("displayName") or a.get("email", ""),
        })
    return out


@router.get("")
async def list_meetings(
    _user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Past occurrences, newest first."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(Meeting)
        .options(joinedload(Meeting.series))
        .where(Meeting.occurred_at <= now)
        .order_by(Meeting.occurred_at.desc())
    )
    meetings = result.scalars().all()

    # One query to find every series with at least one *enabled* link.
    # Drives the seriesHasAutoFile flag without an N+1 over meetings.
    flagged_q = await session.execute(
        select(SeriesContextLink.series_id)
        .where(SeriesContextLink.enabled.is_(True))
        .distinct()
    )
    flagged_series: set[int] = {row[0] for row in flagged_q.all()}

    out: list[dict[str, Any]] = []
    for m in meetings:
        attendees = _serialize_attendees(m.attendees)
        out.append({
            "id": m.id,
            "title": m.title,
            "seriesId": m.series_id,
            "seriesTitle": m.series.display_title if m.series else m.title,
            "occurredAt": m.occurred_at.isoformat(),
            "attendees": attendees,
            "attendeeCount": len(attendees),
            "hasSummary": m.summary_file_id is not None,
            "hasTranscript": m.transcript_file_id is not None,
            "seriesHasAutoFile": m.series_id in flagged_series,
        })
    return out


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: int = Path(..., ge=1),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """
    Detail view. Returns metadata + signed URLs for the summary and
    transcript PDFs. Per spec §7 and CLAUDE.md rule 5, the UI embeds the
    original summary PDF — we do *not* extract text here. Extraction
    (`services/extraction.py`) is reused by the Phase 4 Claude-Project
    Doc handoff and the Phase 6 Confluence generation path.
    """
    result = await session.execute(
        select(Meeting)
        .options(joinedload(Meeting.series))
        .where(Meeting.id == meeting_id)
    )
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(status_code=404, detail="meeting not found")

    summary_url: str | None = None
    if meeting.summary_file_id:
        path, _ttl = sign_file_url(user.id, meeting.summary_file_id)
        summary_url = path

    transcript_url: str | None = None
    if meeting.transcript_file_id:
        path, _ttl = sign_file_url(user.id, meeting.transcript_file_id)
        transcript_url = path

    return {
        "id": meeting.id,
        "title": meeting.title,
        "seriesId": meeting.series_id,
        "seriesTitle": meeting.series.display_title if meeting.series else meeting.title,
        "occurredAt": meeting.occurred_at.isoformat(),
        "attendees": _serialize_attendees(meeting.attendees),
        "summary": (
            {"signedUrl": summary_url} if summary_url else None
        ),
        "transcript": (
            {"signedUrl": transcript_url} if transcript_url else None
        ),
    }
