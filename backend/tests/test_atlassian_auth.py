"""
Tests for Atlassian OAuth wiring + token refresh.

The full /callback path involves Authlib's state/code exchange which is
verified by Authlib's own test suite — we focus here on:
- /login returns 501 when ATLASSIAN_CLIENT_ID is unset (the default
  in the test env)
- /disconnect drops the credential row idempotently
- get_valid_atlassian_token refreshes a near-expired credential and
  persists the rotated refresh token
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.crypto import decrypt, encrypt
from app.db import SessionLocal
from app.models import OAuthCredential, User
from app.services import atlassian as atlassian_module
from app.services.atlassian import (
    AtlassianAuthError,
    get_valid_atlassian_token,
)


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
            google_sub="sub-atlassian-test",
            email="atl@example.com",
            display_name="Atlassian Tester",
            avatar_initials="AT",
        )
        session.add(u)
        await session.commit()
        user_id = u.id
    client.cookies.set("noted_session", _signed_session_cookie(user_id))
    yield user_id


@pytest.mark.asyncio
async def test_login_returns_501_when_unconfigured(client, signed_in_user):
    """The default test env leaves ATLASSIAN_CLIENT_ID empty, so the route
    returns a clean 501 rather than redirecting to Atlassian with empty
    credentials."""
    r = await client.get("/api/auth/atlassian/login", follow_redirects=False)
    assert r.status_code == 501
    assert "ATLASSIAN_CLIENT_ID" in r.json()["detail"]


@pytest.mark.asyncio
async def test_disconnect_removes_credential(client, signed_in_user):
    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=signed_in_user,
                provider="atlassian",
                access_token=encrypt("a"),
                refresh_token=encrypt("r"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    r = await client.post("/api/auth/atlassian/disconnect")
    assert r.status_code == 204

    async with SessionLocal() as session:
        from sqlalchemy import select

        rows = (
            await session.execute(
                select(OAuthCredential).where(
                    OAuthCredential.provider == "atlassian"
                )
            )
        ).scalars().all()
        assert rows == []


@pytest.mark.asyncio
async def test_disconnect_idempotent_when_no_row(client, signed_in_user):
    r = await client.post("/api/auth/atlassian/disconnect")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_disconnect_unauthenticated(client):
    client.cookies.clear()
    r = await client.post("/api/auth/atlassian/disconnect")
    assert r.status_code == 401


# --- refresh helper ----------------------------------------------------------


class _MockResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_get_valid_token_returns_cached_when_fresh(signed_in_user, monkeypatch):
    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=signed_in_user,
                provider="atlassian",
                access_token=encrypt("fresh-access"),
                refresh_token=encrypt("rfr"),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    async def boom(*args, **kwargs):
        raise AssertionError("should not refresh when cache is fresh")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)

    async with SessionLocal() as session:
        token = await get_valid_atlassian_token(session, signed_in_user)
    assert token == "fresh-access"


@pytest.mark.asyncio
async def test_get_valid_token_refreshes_when_expired(signed_in_user, monkeypatch):
    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=signed_in_user,
                provider="atlassian",
                access_token=encrypt("stale-access"),
                refresh_token=encrypt("old-refresh"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    posted_payloads: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            posted_payloads.append(json or {})
            return _MockResponse(
                200,
                {
                    "access_token": "shiny-new-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                    "scope": "read:jira-work offline_access",
                },
            )

    monkeypatch.setattr(atlassian_module.httpx, "AsyncClient", FakeClient)

    async with SessionLocal() as session:
        token = await get_valid_atlassian_token(session, signed_in_user)
    assert token == "shiny-new-access"

    # Refresh body shape sanity
    assert posted_payloads[0]["grant_type"] == "refresh_token"
    assert posted_payloads[0]["refresh_token"] == "old-refresh"

    # Persisted rotated refresh token + new access token
    async with SessionLocal() as session:
        from sqlalchemy import select

        cred = (
            await session.execute(
                select(OAuthCredential).where(
                    OAuthCredential.user_id == signed_in_user,
                    OAuthCredential.provider == "atlassian",
                )
            )
        ).scalar_one()
        assert decrypt(cred.access_token) == "shiny-new-access"
        assert decrypt(cred.refresh_token) == "rotated-refresh"
        assert cred.scopes == "read:jira-work offline_access"


@pytest.mark.asyncio
async def test_get_valid_token_missing_credential_raises(signed_in_user):
    async with SessionLocal() as session:
        with pytest.raises(AtlassianAuthError, match="no Atlassian credential"):
            await get_valid_atlassian_token(session, signed_in_user)


@pytest.mark.asyncio
async def test_get_valid_token_refresh_failure_raises(signed_in_user, monkeypatch):
    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=signed_in_user,
                provider="atlassian",
                access_token=encrypt("expired"),
                refresh_token=encrypt("bad-refresh"),
                expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None, **kwargs):
            return _MockResponse(400, {"error": "invalid_grant"})

    monkeypatch.setattr(atlassian_module.httpx, "AsyncClient", FakeClient)

    async with SessionLocal() as session:
        with pytest.raises(AtlassianAuthError, match="refresh failed"):
            await get_valid_atlassian_token(session, signed_in_user)
