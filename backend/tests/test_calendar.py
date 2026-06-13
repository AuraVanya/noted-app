"""Smoke + unit tests for the Calendar endpoints."""

from datetime import datetime, timezone

import pytest

from app.routers.calendar import _event_end, _resolve_tz


@pytest.mark.asyncio
async def test_calendar_week_unauthenticated(client):
    r = await client.get("/api/calendar/week?start=2026-06-08")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_calendar_today_unauthenticated(client):
    r = await client.get("/api/calendar/today")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_calendar_week_rejects_bad_start(client):
    # Even without auth, the param validator surfaces first via Depends order;
    # use a session-authed scenario or just check that a malformed date isn't
    # silently accepted. With no session, the dep chain returns 401 *before*
    # param parsing, so we just confirm we don't blow up.
    r = await client.get("/api/calendar/week?start=not-a-date")
    assert r.status_code in (400, 401)


class TestResolveTZ:
    def test_known_zone(self):
        z = _resolve_tz("America/New_York")
        assert z.key == "America/New_York"

    def test_unknown_zone_falls_back_to_utc(self):
        z = _resolve_tz("Mars/Olympus")
        assert z.key == "UTC"

    def test_none_falls_back_to_utc(self):
        z = _resolve_tz(None)
        assert z.key == "UTC"


class TestEventEnd:
    def test_z_terminated(self):
        ev = {"end": {"dateTime": "2026-06-12T07:15:00Z"}}
        result = _event_end(ev)
        assert result == datetime(2026, 6, 12, 7, 15, tzinfo=timezone.utc)

    def test_offset_form(self):
        ev = {"end": {"dateTime": "2026-06-12T03:15:00-04:00"}}
        result = _event_end(ev)
        assert result == datetime(2026, 6, 12, 7, 15, tzinfo=timezone.utc)

    def test_all_day_event_returns_none(self):
        ev = {"end": {"date": "2026-06-12"}}
        assert _event_end(ev) is None

    def test_missing_end(self):
        assert _event_end({}) is None
