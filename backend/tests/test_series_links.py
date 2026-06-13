"""Tests for /api/series/{id}/context-links."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    MeetingSeries,
    OAuthCredential,
    ProjectContext,
    SeriesContextLink,
    User,
)


def _signed_session_cookie(user_id: int) -> str:
    import json
    from base64 import b64encode
    from itsdangerous.timed import TimestampSigner

    from app.config import get_settings

    payload = json.dumps({"user_id": user_id}, separators=(",", ":")).encode()
    return TimestampSigner(get_settings().session_secret).sign(b64encode(payload)).decode()


@pytest.fixture
async def seeded_series(client):
    """User + Google cred + two registered Project Contexts + two series."""
    async with SessionLocal() as session:
        u = User(
            google_sub="sub-series-test",
            email="series@example.com",
            display_name="Series Tester",
            avatar_initials="ST",
        )
        session.add(u)
        await session.flush()
        session.add(
            OAuthCredential(
                user_id=u.id,
                provider="google",
                access_token="enc",
                refresh_token="enc",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="x",
            )
        )
        ctx_a = ProjectContext(
            label="Context A",
            drive_folder_id="folder-a",
            drive_folder_url="https://drive.google.com/drive/folders/folder-a",
            created_by_user_id=u.id,
        )
        ctx_b = ProjectContext(
            label="Context B",
            drive_folder_id="folder-b",
            drive_folder_url="https://drive.google.com/drive/folders/folder-b",
            created_by_user_id=u.id,
        )
        s1 = MeetingSeries(normalized_title="standup", display_title="Standup")
        s2 = MeetingSeries(normalized_title="design", display_title="Design")
        session.add_all([ctx_a, ctx_b, s1, s2])
        await session.commit()
        out = {
            "user_id": u.id,
            "ctx_a_id": ctx_a.id,
            "ctx_b_id": ctx_b.id,
            "s1_id": s1.id,
            "s2_id": s2.id,
        }

    client.cookies.set("noted_session", _signed_session_cookie(out["user_id"]))
    yield out


@pytest.mark.asyncio
async def test_get_links_shows_all_contexts_unlinked_by_default(client, seeded_series):
    r = await client.get(f"/api/series/{seeded_series['s1_id']}/context-links")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    labels = {row["label"] for row in body}
    assert labels == {"Context A", "Context B"}
    assert all(row["enabled"] is False for row in body)


@pytest.mark.asyncio
async def test_put_links_enables_and_persists(client, seeded_series):
    r = await client.put(
        f"/api/series/{seeded_series['s1_id']}/context-links",
        json={
            "links": [
                {"projectContextId": seeded_series["ctx_a_id"], "enabled": True},
            ]
        },
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    by_ctx = {row["projectContextId"]: row for row in rows}
    assert by_ctx[seeded_series["ctx_a_id"]]["enabled"] is True
    assert by_ctx[seeded_series["ctx_b_id"]]["enabled"] is False

    # GET reflects the persisted state
    g = await client.get(f"/api/series/{seeded_series['s1_id']}/context-links")
    by_ctx_g = {row["projectContextId"]: row for row in g.json()}
    assert by_ctx_g[seeded_series["ctx_a_id"]]["enabled"] is True


@pytest.mark.asyncio
async def test_put_links_disable_keeps_row(client, seeded_series):
    # Enable, then disable
    await client.put(
        f"/api/series/{seeded_series['s1_id']}/context-links",
        json={"links": [{"projectContextId": seeded_series["ctx_a_id"], "enabled": True}]},
    )
    await client.put(
        f"/api/series/{seeded_series['s1_id']}/context-links",
        json={"links": [{"projectContextId": seeded_series["ctx_a_id"], "enabled": False}]},
    )

    # Row persists with enabled=false (audit-trail intent)
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(SeriesContextLink).where(
                    SeriesContextLink.series_id == seeded_series["s1_id"],
                    SeriesContextLink.project_context_id == seeded_series["ctx_a_id"],
                )
            )
        ).scalar_one()
        assert row.enabled is False


@pytest.mark.asyncio
async def test_put_links_unknown_context_400(client, seeded_series):
    r = await client.put(
        f"/api/series/{seeded_series['s1_id']}/context-links",
        json={"links": [{"projectContextId": 99999, "enabled": True}]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_put_links_unknown_series_404(client, seeded_series):
    r = await client.put(
        "/api/series/99999/context-links",
        json={"links": []},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_links_unauthenticated(client):
    client.cookies.clear()
    r = await client.get("/api/series/1/context-links")
    assert r.status_code == 401
    r = await client.put("/api/series/1/context-links", json={"links": []})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_links_isolated_per_series(client, seeded_series):
    """Enabling a link on series 1 doesn't show on series 2."""
    await client.put(
        f"/api/series/{seeded_series['s1_id']}/context-links",
        json={"links": [{"projectContextId": seeded_series["ctx_a_id"], "enabled": True}]},
    )
    g = await client.get(f"/api/series/{seeded_series['s2_id']}/context-links")
    assert all(row["enabled"] is False for row in g.json())
