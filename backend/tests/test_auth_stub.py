import pytest


@pytest.mark.asyncio
async def test_me_unauthenticated(client):
    r = await client.get("/api/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_atlassian_login_stub(client):
    r = await client.get("/api/auth/atlassian/login")
    assert r.status_code == 501


@pytest.mark.asyncio
async def test_logout_clears_session(client):
    r = await client.post("/api/auth/logout")
    assert r.status_code == 204
