"""
Tests for the Project Context registry endpoints + Drive folder search.

We patch the Drive-write helpers so the test never reaches Google. The
DB tables and constraints are the load-bearing thing here; tests verify
the API shape and the dedupe behavior.
"""

from __future__ import annotations

import pytest

from app.db import SessionLocal
from app.models import OAuthCredential, User
from app.routers import project_contexts as pc_router
from app.services import google as google_module


@pytest.fixture
async def signed_in_user(client, monkeypatch):
    """Insert a user + Google credential, set the session cookie, patch the
    token helper so subsequent requests don't try to refresh against
    Google."""
    from datetime import datetime, timedelta, timezone

    async with SessionLocal() as session:
        u = User(
            google_sub="sub-pc-test",
            email="pc@example.com",
            display_name="PC Tester",
            avatar_initials="PT",
        )
        session.add(u)
        await session.flush()
        cred = OAuthCredential(
            user_id=u.id,
            provider="google",
            access_token="enc",
            refresh_token="enc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes="openid email profile",
        )
        session.add(cred)
        await session.commit()
        user_id = u.id

    async def fake_token(session, _user_id):
        return "fake-token"

    monkeypatch.setattr(pc_router, "get_valid_google_token", fake_token)

    client.cookies.set("noted_session", _signed_session_cookie(user_id))
    yield user_id


def _signed_session_cookie(user_id: int) -> str:
    """Build the SessionMiddleware cookie value for the given user_id."""
    import json
    from base64 import b64encode
    from itsdangerous.timed import TimestampSigner

    from app.config import get_settings

    payload = json.dumps({"user_id": user_id}, separators=(",", ":")).encode()
    encoded = b64encode(payload)
    signer = TimestampSigner(get_settings().session_secret)
    signed = signer.sign(encoded)
    return signed.decode()


@pytest.mark.asyncio
async def test_list_empty(client, signed_in_user):
    r = await client.get("/api/project-contexts")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_new_folder(client, signed_in_user, monkeypatch):
    async def fake_create(token, name, parent_id=None):
        assert name == "Team Best"
        return {
            "id": "drive-folder-abc",
            "name": "Team Best",
            "webViewLink": "https://drive.google.com/drive/folders/drive-folder-abc",
        }

    monkeypatch.setattr(pc_router, "create_drive_folder", fake_create)

    r = await client.post(
        "/api/project-contexts",
        json={"label": "Team Best", "mode": "create"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "Team Best"
    assert body["driveFolderId"] == "drive-folder-abc"
    assert body["docCount"] == 0


@pytest.mark.asyncio
async def test_create_existing_folder(client, signed_in_user, monkeypatch):
    async def fake_get(token, folder_id):
        assert folder_id == "existing-folder-x"
        return {
            "id": "existing-folder-x",
            "name": "Some Folder",
            "webViewLink": "https://drive.google.com/drive/folders/existing-folder-x",
            "mimeType": "application/vnd.google-apps.folder",
        }

    monkeypatch.setattr(pc_router, "get_drive_folder", fake_get)

    r = await client.post(
        "/api/project-contexts",
        json={"label": "Worx", "mode": "existing", "folderId": "existing-folder-x"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["driveFolderId"] == "existing-folder-x"


@pytest.mark.asyncio
async def test_duplicate_label_rejected(client, signed_in_user, monkeypatch):
    async def fake_create(token, name, parent_id=None):
        return {"id": "f1", "name": name, "webViewLink": "u"}

    monkeypatch.setattr(pc_router, "create_drive_folder", fake_create)

    r1 = await client.post(
        "/api/project-contexts",
        json={"label": "Dup", "mode": "create"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/project-contexts",
        json={"label": "Dup", "mode": "create"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_folder_rejected(client, signed_in_user, monkeypatch):
    async def fake_get(token, folder_id):
        return {
            "id": folder_id,
            "name": "F",
            "webViewLink": "u",
            "mimeType": "application/vnd.google-apps.folder",
        }

    monkeypatch.setattr(pc_router, "get_drive_folder", fake_get)

    r1 = await client.post(
        "/api/project-contexts",
        json={"label": "A", "mode": "existing", "folderId": "same-folder"},
    )
    assert r1.status_code == 201
    r2 = await client.post(
        "/api/project-contexts",
        json={"label": "B", "mode": "existing", "folderId": "same-folder"},
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_delete_project_context(client, signed_in_user, monkeypatch):
    async def fake_create(token, name, parent_id=None):
        return {"id": "fid", "name": name, "webViewLink": "u"}

    trash_calls: list[str] = []

    async def fake_trash(token, file_id):
        trash_calls.append(file_id)

    monkeypatch.setattr(pc_router, "create_drive_folder", fake_create)
    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    r = await client.post(
        "/api/project-contexts",
        json={"label": "ToDelete", "mode": "create"},
    )
    pid = r.json()["id"]

    rd = await client.delete(f"/api/project-contexts/{pid}")
    assert rd.status_code == 200, rd.text
    body = rd.json()
    assert body["driveFolderTrashed"] is True
    assert body["driveFolderError"] is None
    assert trash_calls == ["fid"]

    rg = await client.get("/api/project-contexts")
    assert rg.json() == []


@pytest.mark.asyncio
async def test_delete_project_context_keep_drive_folder(
    client, signed_in_user, monkeypatch
):
    """deleteDriveFolder=false leaves the folder alone."""

    async def fake_create(token, name, parent_id=None):
        return {"id": "fid2", "name": name, "webViewLink": "u"}

    trash_calls: list[str] = []

    async def fake_trash(token, file_id):
        trash_calls.append(file_id)

    monkeypatch.setattr(pc_router, "create_drive_folder", fake_create)
    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    r = await client.post(
        "/api/project-contexts",
        json={"label": "KeepFolder", "mode": "create"},
    )
    pid = r.json()["id"]

    rd = await client.delete(
        f"/api/project-contexts/{pid}?deleteDriveFolder=false"
    )
    assert rd.status_code == 200
    body = rd.json()
    assert body["driveFolderTrashed"] is False
    assert trash_calls == []


@pytest.mark.asyncio
async def test_delete_project_context_drive_error_still_removes_row(
    client, signed_in_user, monkeypatch
):
    """If the Drive trash call fails (no permission, etc.) the registry row
    is still removed and the error is surfaced in the response."""
    from app.services.google import DriveAccessError

    async def fake_create(token, name, parent_id=None):
        return {"id": "fid3", "name": name, "webViewLink": "u"}

    async def fake_trash(token, file_id):
        raise DriveAccessError("simulated 403")

    monkeypatch.setattr(pc_router, "create_drive_folder", fake_create)
    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    r = await client.post(
        "/api/project-contexts",
        json={"label": "ErrFolder", "mode": "create"},
    )
    pid = r.json()["id"]

    rd = await client.delete(f"/api/project-contexts/{pid}")
    assert rd.status_code == 200
    body = rd.json()
    assert body["driveFolderTrashed"] is False
    assert "simulated 403" in body["driveFolderError"]

    # Row still removed
    rg = await client.get("/api/project-contexts")
    labels = [p["label"] for p in rg.json()]
    assert "ErrFolder" not in labels


@pytest.mark.asyncio
async def test_delete_missing_404(client, signed_in_user):
    r = await client.delete("/api/project-contexts/99999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_drive_folder_search(client, signed_in_user, monkeypatch):
    async def fake_search(token, q, limit=20):
        assert q == "engineering"
        return [
            {
                "id": "f1",
                "name": "Engineering",
                "webViewLink": "https://drive.google.com/drive/folders/f1",
            },
            {
                "id": "f2",
                "name": "Engineering Drafts",
                "webViewLink": "https://drive.google.com/drive/folders/f2",
            },
        ]

    monkeypatch.setattr(pc_router, "search_drive_folders", fake_search)

    r = await client.get("/api/drive/folders?q=engineering")
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 2
    assert body[0] == {
        "id": "f1",
        "name": "Engineering",
        "url": "https://drive.google.com/drive/folders/f1",
    }


# --- Unauthenticated ---------------------------------------------------------


@pytest.mark.asyncio
async def test_list_unauthenticated(client):
    r = await client.get("/api/project-contexts")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_drive_search_unauthenticated(client):
    r = await client.get("/api/drive/folders?q=x")
    assert r.status_code == 401


# --- Drive helper unit tests -------------------------------------------------


def test_search_query_empty_short_circuits():
    """search_drive_folders returns [] for empty/whitespace queries without
    even calling Drive."""
    import asyncio

    out = asyncio.run(google_module.search_drive_folders("token", "   "))
    assert out == []
