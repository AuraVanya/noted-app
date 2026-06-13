"""
Sync orchestrator. Pulls a user's Drive folders, parses filenames, upserts
meeting_series and meetings, and (best-effort) matches each occurrence to a
Google Calendar event within ±10 min.

Idempotency rules (CLAUDE.md §8 / spec §6):
- (series_id, occurred_at) is unique — the second run cannot create duplicates.
- On update, we fill NULL file ids in only; never overwrite an existing id
  with NULL. This is what makes "summary arrives, then transcript arrives
  next sync" Just Work.
- Failures in any per-meeting step are logged into the summary's `errors[]`
  and do not abort the run.

Out of scope here (CLAUDE.md domain rule 4): PDF text extraction. We store
file ids only; `summary_text` stays NULL until Phase 3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Meeting, MeetingSeries
from .filename import ParsedFilename, parse_filename
from .google import (
    GoogleAuthError,
    collect_normalized_titles,
    event_attendees,
    event_start,
    get_valid_google_token,
    list_calendar_events,
    list_drive_folder,
)


log = logging.getLogger(__name__)

CALENDAR_TOLERANCE = timedelta(minutes=10)
_CALENDAR_FETCH_BUFFER = timedelta(minutes=15)  # bigger than tolerance, deliberately


@dataclass
class SyncSummary:
    user_id: int
    series_upserted: int = 0
    meetings_upserted: int = 0
    meetings_skipped: int = 0
    calendar_matched: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "series_upserted": self.series_upserted,
            "meetings_upserted": self.meetings_upserted,
            "meetings_skipped": self.meetings_skipped,
            "calendar_matched": self.calendar_matched,
            "errors": self.errors,
        }


# (normalized_title, occurred_at) → file_id ; second slot keeps the display title
_OccKey = tuple[str, datetime]
_OccValue = tuple[str, str]  # (file_id, display_title)


def _parse_into(
    files: list[dict[str, Any]],
    expected_kind: str,
    summary: SyncSummary,
) -> dict[_OccKey, _OccValue]:
    """Walk a folder listing, parse each name, drop non-matching kinds."""
    out: dict[_OccKey, _OccValue] = {}
    for f in files:
        name = f.get("name") or ""
        parsed: ParsedFilename | None = parse_filename(name)
        if parsed is None:
            summary.meetings_skipped += 1
            log.info("sync: skipping non-conforming filename %r", name)
            continue
        if parsed.kind != expected_kind:
            # File was in the wrong folder; skip it. We don't try to be clever
            # and use it from the other side — the convention is that summaries
            # live in the summaries folder.
            summary.meetings_skipped += 1
            log.info(
                "sync: %s in %s folder, skipping",
                parsed.kind,
                expected_kind,
            )
            continue
        out[(parsed.normalized_title, parsed.occurred_at)] = (
            f["id"],
            parsed.display_title,
        )
    return out


async def _upsert_series(
    session: AsyncSession,
    normalized: str,
    display: str,
    summary: SyncSummary,
) -> MeetingSeries:
    existing = await session.execute(
        select(MeetingSeries).where(MeetingSeries.normalized_title == normalized)
    )
    series = existing.scalar_one_or_none()
    if series is None:
        series = MeetingSeries(normalized_title=normalized, display_title=display)
        session.add(series)
        await session.flush()
        summary.series_upserted += 1
    return series


async def _upsert_meeting(
    session: AsyncSession,
    series: MeetingSeries,
    occurred_at: datetime,
    display_title: str,
    summary_file_id: str | None,
    transcript_file_id: str | None,
    summary: SyncSummary,
) -> Meeting:
    existing = await session.execute(
        select(Meeting).where(
            Meeting.series_id == series.id,
            Meeting.occurred_at == occurred_at,
        )
    )
    meeting = existing.scalar_one_or_none()

    if meeting is None:
        meeting = Meeting(
            series_id=series.id,
            title=display_title,
            occurred_at=occurred_at,
            summary_file_id=summary_file_id,
            transcript_file_id=transcript_file_id,
        )
        session.add(meeting)
        await session.flush()
        summary.meetings_upserted += 1
        return meeting

    # Fill-NULL-only update. This is the load-bearing rule for the
    # "summary now, transcript later" case.
    changed = False
    if meeting.summary_file_id is None and summary_file_id is not None:
        meeting.summary_file_id = summary_file_id
        changed = True
    if meeting.transcript_file_id is None and transcript_file_id is not None:
        meeting.transcript_file_id = transcript_file_id
        changed = True
    # Keep display title fresh if Drive sent a tidier version
    if display_title and meeting.title != display_title:
        meeting.title = display_title
        changed = True
    if changed:
        summary.meetings_upserted += 1
    return meeting


def _find_matching_event(
    occurred_at: datetime,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Among events with the same normalized title, find the one whose start
    is within ±10 min of `occurred_at`. Closest match wins."""
    best: dict[str, Any] | None = None
    best_delta: timedelta | None = None
    for ev in candidates:
        start = event_start(ev)
        if start is None:
            continue
        delta = abs(start - occurred_at)
        if delta <= CALENDAR_TOLERANCE and (best_delta is None or delta < best_delta):
            best = ev
            best_delta = delta
    return best


async def sync_user(session: AsyncSession, user_id: int) -> SyncSummary:
    """Run one ingestion pass for `user_id`. Always returns a summary; the
    summary's `errors` carry any non-fatal failures."""
    settings = get_settings()
    summary = SyncSummary(user_id=user_id)

    try:
        token = await get_valid_google_token(session, user_id)
    except GoogleAuthError as exc:
        summary.errors.append(f"auth: {exc}")
        return summary

    # 1) Enumerate both folders
    try:
        summary_files = await list_drive_folder(token, settings.drive_summaries_folder_id)
    except Exception as exc:  # noqa: BLE001 — third-party HTTP, log + continue
        summary.errors.append(f"drive list summaries: {exc}")
        summary_files = []

    try:
        transcript_files = await list_drive_folder(
            token, settings.drive_transcripts_folder_id
        )
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"drive list transcripts: {exc}")
        transcript_files = []

    # 2) Parse names; build occurrence dicts keyed by (norm_title, occurred_at)
    summaries_by_key = _parse_into(summary_files, "summary", summary)
    transcripts_by_key = _parse_into(transcript_files, "transcript", summary)

    all_keys = set(summaries_by_key) | set(transcripts_by_key)
    if not all_keys:
        return summary

    # 3) Upsert series (one per unique normalized title)
    series_cache: dict[str, MeetingSeries] = {}
    for normalized in {k[0] for k in all_keys}:
        # Prefer the display title from the summary side; fall back to transcript
        display = ""
        for key in all_keys:
            if key[0] != normalized:
                continue
            display = (
                summaries_by_key.get(key, (None, ""))[1]
                or transcripts_by_key.get(key, (None, ""))[1]
                or display
            )
            if display:
                break
        try:
            series_cache[normalized] = await _upsert_series(
                session, normalized, display, summary
            )
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"series upsert {normalized!r}: {exc}")

    # 4) Upsert meetings
    meetings_by_key: dict[_OccKey, Meeting] = {}
    for key in all_keys:
        normalized, occurred_at = key
        series = series_cache.get(normalized)
        if series is None:
            continue  # series upsert failed; error already recorded
        summary_id = summaries_by_key.get(key, (None, ""))[0]
        transcript_id = transcripts_by_key.get(key, (None, ""))[0]
        display_title = (
            summaries_by_key.get(key, (None, ""))[1]
            or transcripts_by_key.get(key, (None, ""))[1]
            or series.display_title
        )
        try:
            meetings_by_key[key] = await _upsert_meeting(
                session=session,
                series=series,
                occurred_at=occurred_at,
                display_title=display_title,
                summary_file_id=summary_id,
                transcript_file_id=transcript_id,
                summary=summary,
            )
        except Exception as exc:  # noqa: BLE001
            summary.errors.append(f"meeting upsert {normalized!r} @ {occurred_at}: {exc}")

    # 5) Calendar match — one fetch covers the whole batch
    try:
        time_min = min(k[1] for k in all_keys) - _CALENDAR_FETCH_BUFFER
        time_max = max(k[1] for k in all_keys) + _CALENDAR_FETCH_BUFFER
        events = await list_calendar_events(token, time_min, time_max)
        by_title = collect_normalized_titles(events)

        for key, meeting in meetings_by_key.items():
            normalized, occurred_at = key
            candidates = by_title.get(normalized, [])
            if not candidates:
                # fall back to normalizing the event titles already returned above
                continue
            event = _find_matching_event(occurred_at, candidates)
            if event is None:
                continue
            new_event_id = event.get("id")
            new_attendees = event_attendees(event)
            changed = False
            if meeting.calendar_event_id != new_event_id:
                meeting.calendar_event_id = new_event_id
                changed = True
            if new_attendees and meeting.attendees != new_attendees:
                meeting.attendees = new_attendees
                changed = True
            if changed:
                summary.calendar_matched += 1
    except Exception as exc:  # noqa: BLE001
        summary.errors.append(f"calendar match: {exc}")

    await session.commit()
    return summary
