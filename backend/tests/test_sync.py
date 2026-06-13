"""
Integration tests for the sync pipeline against an in-memory SQLite DB and
a fake Google client. The point here is the *behaviour* — idempotent
upsert, fill-NULL semantics, calendar matching — not the HTTP wire format
(that's exercised live against Drive in Slice 3 acceptance).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import Meeting, MeetingSeries, OAuthCredential, User
from app.services import sync as sync_module
from app.services.sync import sync_user


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _drive_file(file_id: str, name: str) -> dict[str, Any]:
    return {
        "id": file_id,
        "name": name,
        "createdTime": "2026-06-12T00:00:00.000Z",
        "mimeType": "application/pdf",
    }


def _cal_event(event_id: str, title: str, start: datetime, attendees=None) -> dict[str, Any]:
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
        "attendees": attendees or [],
    }


@pytest.fixture(autouse=True)
async def _reset_schema():
    """Fresh schema for every test. The session-level conftest fixture set
    APP env vars, but doesn't drop tables between tests; this does."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def db_session():
    async with SessionLocal() as session:
        yield session


@pytest.fixture
async def user(db_session) -> User:
    u = User(
        google_sub="sub-1",
        email="user@example.com",
        display_name="Test User",
        avatar_initials="TU",
    )
    db_session.add(u)
    await db_session.flush()
    # Encrypted token blobs are not exercised here — token refresh is patched.
    cred = OAuthCredential(
        user_id=u.id,
        provider="google",
        access_token="enc-access",
        refresh_token="enc-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scopes="openid email profile",
    )
    db_session.add(cred)
    await db_session.commit()
    return u


@pytest.fixture
def fake_google(monkeypatch):
    """Capture-and-replay style fake. Tests set .summary_files / .transcript_files /
    .calendar_events and the patched functions return them."""

    class Fake:
        summary_files: list[dict[str, Any]] = []
        transcript_files: list[dict[str, Any]] = []
        calendar_events: list[dict[str, Any]] = []

    async def fake_token(session, user_id):
        return "fake-token"

    async def fake_drive_list(token, folder_id):
        # The same fake serves both folders; we distinguish via settings.
        from app.config import get_settings
        s = get_settings()
        if folder_id == s.drive_summaries_folder_id:
            return list(Fake.summary_files)
        if folder_id == s.drive_transcripts_folder_id:
            return list(Fake.transcript_files)
        return []

    async def fake_calendar_list(token, time_min, time_max):
        return list(Fake.calendar_events)

    monkeypatch.setenv("DRIVE_SUMMARIES_FOLDER_ID", "summaries-folder")
    monkeypatch.setenv("DRIVE_TRANSCRIPTS_FOLDER_ID", "transcripts-folder")
    # The settings object is cached; clear and re-prime
    from app.config import get_settings
    get_settings.cache_clear()  # type: ignore[attr-defined]

    monkeypatch.setattr(sync_module, "get_valid_google_token", fake_token)
    monkeypatch.setattr(sync_module, "list_drive_folder", fake_drive_list)
    monkeypatch.setattr(sync_module, "list_calendar_events", fake_calendar_list)
    yield Fake
    get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_first_run_creates_series_and_meeting(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("file-sum-1", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.transcript_files = [
        _drive_file("file-tr-1", "Standup-transcript-2026-06-12T09-00-00.000Z.pdf"),
    ]

    result = await sync_user(db_session, user.id)

    assert result.series_upserted == 1
    assert result.meetings_upserted == 1
    assert result.meetings_skipped == 0
    assert result.errors == []

    series_count = (await db_session.execute(select(MeetingSeries))).all()
    assert len(series_count) == 1

    meeting = (await db_session.execute(select(Meeting))).scalar_one()
    assert meeting.title == "Standup"
    assert meeting.occurred_at == _utc(2026, 6, 12, 9)
    assert meeting.summary_file_id == "file-sum-1"
    assert meeting.transcript_file_id == "file-tr-1"
    # Phase 2 doesn't extract text
    assert meeting.summary_text is None


@pytest.mark.asyncio
async def test_second_run_no_duplicates(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("file-sum-1", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.transcript_files = [
        _drive_file("file-tr-1", "Standup-transcript-2026-06-12T09-00-00.000Z.pdf"),
    ]

    await sync_user(db_session, user.id)
    second = await sync_user(db_session, user.id)

    assert second.series_upserted == 0
    assert second.meetings_upserted == 0

    series = (await db_session.execute(select(MeetingSeries))).scalars().all()
    meetings = (await db_session.execute(select(Meeting))).scalars().all()
    assert len(series) == 1
    assert len(meetings) == 1


@pytest.mark.asyncio
async def test_transcript_arrives_later_fills_null(db_session, user, fake_google):
    """Summary arrives in run 1, transcript shows up in run 2 — the existing
    row should pick up transcript_file_id without losing summary_file_id."""
    fake_google.summary_files = [
        _drive_file("file-sum-1", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.transcript_files = []

    await sync_user(db_session, user.id)
    meeting = (await db_session.execute(select(Meeting))).scalar_one()
    assert meeting.summary_file_id == "file-sum-1"
    assert meeting.transcript_file_id is None

    # Second run: transcript appears
    fake_google.transcript_files = [
        _drive_file("file-tr-1", "Standup-transcript-2026-06-12T09-00-00.000Z.pdf"),
    ]
    await sync_user(db_session, user.id)

    await db_session.refresh(meeting)
    assert meeting.summary_file_id == "file-sum-1"  # NOT overwritten
    assert meeting.transcript_file_id == "file-tr-1"


@pytest.mark.asyncio
async def test_same_day_recurring_distinct_rows(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("a", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
        _drive_file("b", "Standup-summary-2026-06-12T15-30-00.000Z.pdf"),
    ]
    fake_google.transcript_files = []

    result = await sync_user(db_session, user.id)
    assert result.meetings_upserted == 2

    meetings = (
        await db_session.execute(select(Meeting).order_by(Meeting.occurred_at))
    ).scalars().all()
    assert len(meetings) == 2
    assert meetings[0].occurred_at == _utc(2026, 6, 12, 9)
    assert meetings[1].occurred_at == _utc(2026, 6, 12, 15, 30)
    # Same series
    assert meetings[0].series_id == meetings[1].series_id


@pytest.mark.asyncio
async def test_hyphenated_title_does_not_split(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file(
            "x", "Q2 Planning - Phase 1-summary-2026-06-12T14-30-00.000Z.pdf"
        ),
    ]
    fake_google.transcript_files = []

    await sync_user(db_session, user.id)
    series = (await db_session.execute(select(MeetingSeries))).scalar_one()
    assert series.display_title == "Q2 Planning - Phase 1"
    assert series.normalized_title == "q2 planning - phase 1"


@pytest.mark.asyncio
async def test_non_conforming_filename_skipped_not_aborted(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("bad", "junk.pdf"),
        _drive_file("good", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.transcript_files = []

    result = await sync_user(db_session, user.id)
    assert result.meetings_upserted == 1
    assert result.meetings_skipped == 1
    assert result.errors == []


@pytest.mark.asyncio
async def test_calendar_match_within_tolerance(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("s", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.calendar_events = [
        _cal_event(
            "evt-1",
            "Standup",
            _utc(2026, 6, 12, 9, 3),  # 3 min off — within ±10
            attendees=[{"email": "a@x.com", "displayName": "Alice"}],
        ),
    ]
    await sync_user(db_session, user.id)

    meeting = (await db_session.execute(select(Meeting))).scalar_one()
    assert meeting.calendar_event_id == "evt-1"
    assert meeting.attendees == [{"email": "a@x.com", "displayName": "Alice"}]


@pytest.mark.asyncio
async def test_calendar_match_outside_tolerance_skipped(db_session, user, fake_google):
    fake_google.summary_files = [
        _drive_file("s", "Standup-summary-2026-06-12T09-00-00.000Z.pdf"),
    ]
    fake_google.calendar_events = [
        _cal_event("evt-1", "Standup", _utc(2026, 6, 12, 9, 11)),  # 11 min off
    ]
    await sync_user(db_session, user.id)

    meeting = (await db_session.execute(select(Meeting))).scalar_one()
    assert meeting.calendar_event_id is None
    assert meeting.attendees is None


@pytest.mark.asyncio
async def test_drive_list_failure_logs_does_not_abort(db_session, user, fake_google, monkeypatch):
    async def boom(token, folder_id):
        raise RuntimeError("drive blew up")

    monkeypatch.setattr(sync_module, "list_drive_folder", boom)
    result = await sync_user(db_session, user.id)
    # No data, but the run didn't crash
    assert result.meetings_upserted == 0
    assert any("drive list" in e for e in result.errors)
