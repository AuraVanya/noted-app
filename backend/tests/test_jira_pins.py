"""Tests for /api/me/jira-pins (GET + PUT)."""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import User


def _signed_session_cookie(user_id: int) -> str:
    import json
    from base64 import b64encode
    from itsdangerous.timed import TimestampSigner

    from app.config import get_settings

    payload = json.dumps({"user_id": user_id}, separators=(",", ":")).encode()
    return TimestampSigner(get_settings().session_secret).sign(b64encode(payload)).decode()


@pytest.fixture
async def signed_in_user(client):
    async with SessionLocal() as session:
        u = User(
            google_sub="sub-pins-test",
            email="pins@example.com",
            display_name="Pins Tester",
            avatar_initials="PT",
        )
        session.add(u)
        await session.commit()
        user_id = u.id
    client.cookies.set("noted_session", _signed_session_cookie(user_id))
    yield user_id


@pytest.mark.asyncio
async def test_empty_pins(client, signed_in_user):
    r = await client.get("/api/me/jira-pins")
    assert r.status_code == 200
    assert r.json() == {"projectKeys": []}


@pytest.mark.asyncio
async def test_put_pins_persists_in_order(client, signed_in_user):
    r = await client.put(
        "/api/me/jira-pins",
        json={"projectKeys": ["NOT", "PURBECK"]},
    )
    assert r.status_code == 200
    assert r.json()["projectKeys"] == ["NOT", "PURBECK"]

    g = await client.get("/api/me/jira-pins")
    assert g.json()["projectKeys"] == ["NOT", "PURBECK"]


@pytest.mark.asyncio
async def test_put_pins_replaces_set(client, signed_in_user):
    await client.put("/api/me/jira-pins", json={"projectKeys": ["NOT", "PURBECK"]})
    await client.put("/api/me/jira-pins", json={"projectKeys": ["I2G"]})
    g = await client.get("/api/me/jira-pins")
    assert g.json()["projectKeys"] == ["I2G"]


@pytest.mark.asyncio
async def test_put_pins_dedupes_and_trims(client, signed_in_user):
    r = await client.put(
        "/api/me/jira-pins",
        json={"projectKeys": ["NOT", "NOT", " ", "PURBECK", "NOT"]},
    )
    assert r.json()["projectKeys"] == ["NOT", "PURBECK"]


@pytest.mark.asyncio
async def test_pins_unauthenticated(client):
    client.cookies.clear()
    r = await client.get("/api/me/jira-pins")
    assert r.status_code == 401
    r = await client.put("/api/me/jira-pins", json={"projectKeys": []})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_put_pins_isolated_per_user(client):
    """Two users' pin sets don't bleed into each other."""
    async with SessionLocal() as session:
        u1 = User(
            google_sub="u1",
            email="u1@example.com",
            display_name="U1",
            avatar_initials="U1",
        )
        u2 = User(
            google_sub="u2",
            email="u2@example.com",
            display_name="U2",
            avatar_initials="U2",
        )
        session.add_all([u1, u2])
        await session.commit()
        u1_id = u1.id
        u2_id = u2.id

    # u1 sets pins
    client.cookies.clear()
    client.cookies.set("noted_session", _signed_session_cookie(u1_id))
    await client.put("/api/me/jira-pins", json={"projectKeys": ["NOT"]})

    # u2 sees an empty list
    client.cookies.clear()
    client.cookies.set("noted_session", _signed_session_cookie(u2_id))
    g = await client.get("/api/me/jira-pins")
    assert g.json()["projectKeys"] == []
