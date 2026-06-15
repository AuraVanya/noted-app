"""
Calendar read endpoints. Backed by live Google Calendar reads — we don't
persist events of our own. Each event is annotated with `meetingId` when
its Google Calendar id matches a row in `meetings` (the sync job populates
`meetings.calendar_event_id`), so the UI can route past meetings through
to their Minutes detail page.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import Meeting, User
from ..services.demo_filters import meeting_title_visible
from ..services.google import (
    GoogleAuthError,
    event_attendees,
    event_start,
    get_valid_google_token,
    list_calendar_events,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _resolve_tz(tz: str | None) -> ZoneInfo:
    if not tz:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        # Don't reject the request — fall back to UTC and log
        log.info("calendar: unknown tz %r, falling back to UTC", tz)
        return ZoneInfo("UTC")


def _event_end(event: dict[str, Any]) -> datetime | None:
    end = event.get("end") or {}
    raw = end.get("dateTime")
    if not raw:
        return None
    iso = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc)
    except ValueError:
        return None


async def _annotate(
    session: AsyncSession,
    events: list[dict[str, Any]],
    now_utc: datetime,
) -> list[dict[str, Any]]:
    """Attach meetingId, isPast, attendeeCount to each event."""
    event_ids = [e["id"] for e in events if e.get("id")]
    if event_ids:
        result = await session.execute(
            select(Meeting.id, Meeting.calendar_event_id, Meeting.summary_file_id).where(
                Meeting.calendar_event_id.in_(event_ids)
            )
        )
        # Only surface a meetingId when the meeting actually has a summary
        # — otherwise clicking it lands on a "no summary" detail page.
        by_event = {
            cal_id: meeting_id
            for (meeting_id, cal_id, summary_id) in result.all()
            if summary_id is not None
        }
    else:
        by_event = {}

    out: list[dict[str, Any]] = []
    for ev in events:
        start_dt = event_start(ev)
        end_dt = _event_end(ev)
        if start_dt is None:
            # All-day events or events without a dateTime are skipped — they
            # aren't Fireflies-eligible and would mis-position on the grid.
            continue
        title = ev.get("summary") or "(no title)"
        # Demo-mode prefix allowlist
        if not meeting_title_visible(title):
            continue
        out.append({
            "id": ev.get("id"),
            "title": title,
            "start": start_dt.isoformat(),
            "end": (end_dt.isoformat() if end_dt else None),
            "isPast": start_dt < now_utc,
            "meetingId": by_event.get(ev.get("id")),
            "attendeeCount": len(event_attendees(ev)),
        })
    return out


@router.get("/week")
async def get_week(
    start: str = Query(..., description="Monday of the target week, YYYY-MM-DD in the user's local TZ"),
    tz: str | None = Query(None, description="IANA TZ name, e.g. America/New_York"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        start_date = date.fromisoformat(start)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bad start date") from exc

    zone = _resolve_tz(tz)
    # Monday 00:00 in the user's local TZ → UTC, then +7 days
    local_start = datetime.combine(start_date, datetime.min.time(), tzinfo=zone)
    time_min = local_start.astimezone(timezone.utc)
    time_max = (local_start + timedelta(days=7)).astimezone(timezone.utc)

    try:
        token = await get_valid_google_token(session, user.id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        events = await list_calendar_events(token, time_min, time_max)
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar week fetch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Calendar request failed",
        ) from exc

    annotated = await _annotate(session, events, datetime.now(timezone.utc))
    return {
        "start": time_min.isoformat(),
        "end": time_max.isoformat(),
        "events": annotated,
    }


@router.get("/today")
async def get_today(
    tz: str | None = Query(None, description="IANA TZ name"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Today's events in the user's local TZ. Used by the Home widget."""
    zone = _resolve_tz(tz)
    now_local = datetime.now(zone)
    local_start = datetime.combine(now_local.date(), datetime.min.time(), tzinfo=zone)
    time_min = local_start.astimezone(timezone.utc)
    time_max = (local_start + timedelta(days=1)).astimezone(timezone.utc)

    try:
        token = await get_valid_google_token(session, user.id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        events = await list_calendar_events(token, time_min, time_max)
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar today fetch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Calendar request failed",
        ) from exc

    annotated = await _annotate(session, events, datetime.now(timezone.utc))
    return {
        "date": now_local.date().isoformat(),
        "events": annotated,
    }
