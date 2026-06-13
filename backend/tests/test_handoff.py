"""
Tests for the Project Context handoff service + POST /file / GET /docs.

We patch the Drive write call and the summary-text extractor so the
test exercises the orchestration + idempotency without touching Google.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db import SessionLocal
from app.models import (
    Meeting,
    MeetingSeries,
    OAuthCredential,
    ProjectContext,
    ProjectContextDoc,
    User,
)
from app.routers import project_contexts as pc_router
from app.services import extraction as extraction_module
from app.services import handoff as handoff_module


# --- fixtures ---------------------------------------------------------------


def _signed_session_cookie(user_id: int) -> str:
    import json
    from base64 import b64encode
    from itsdangerous.timed import TimestampSigner

    from app.config import get_settings

    payload = json.dumps({"user_id": user_id}, separators=(",", ":")).encode()
    encoded = b64encode(payload)
    signer = TimestampSigner(get_settings().session_secret)
    return signer.sign(encoded).decode()


@pytest.fixture
async def seeded(client, monkeypatch):
    """Insert: user + Google cred + one meeting series + one meeting with a
    summary_file_id + one Project Context. Patch token + extraction + Drive
    write so the test doesn't reach Google."""
    async with SessionLocal() as session:
        u = User(
            google_sub="sub-handoff",
            email="ho@example.com",
            display_name="Ho Tester",
            avatar_initials="HT",
        )
        session.add(u)
        await session.flush()
        cred = OAuthCredential(
            user_id=u.id,
            provider="google",
            access_token="enc",
            refresh_token="enc",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            scopes="x",
        )
        series = MeetingSeries(
            normalized_title="standup",
            display_title="Standup",
        )
        session.add_all([cred, series])
        await session.flush()
        meeting = Meeting(
            series_id=series.id,
            title="Standup",
            occurred_at=datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc),
            summary_file_id="drive-summary-1",
            transcript_file_id="drive-transcript-1",
        )
        ctx = ProjectContext(
            label="Team Best",
            drive_folder_id="folder-team-best",
            drive_folder_url="https://drive.google.com/drive/folders/folder-team-best",
            created_by_user_id=u.id,
        )
        session.add_all([meeting, ctx])
        await session.commit()
        user_id = u.id
        meeting_id = meeting.id
        ctx_id = ctx.id

    async def fake_token(session, _user_id):
        return "fake-token"

    async def fake_extract(session, meeting, token):
        # Reuse cached value if set, else mock content
        if meeting.summary_text:
            return meeting.summary_text
        meeting.summary_text = "Discussion of the project."
        await session.commit()
        return meeting.summary_text

    async def fake_create_doc(token, name, parent, body):
        return {
            "id": f"doc-{name[:30]}",
            "name": name,
            "webViewLink": f"https://docs.google.com/document/d/doc-{name[:10]}/edit",
        }

    monkeypatch.setattr(handoff_module, "get_valid_google_token", fake_token)
    monkeypatch.setattr(handoff_module, "extract_summary_text", fake_extract)
    monkeypatch.setattr(handoff_module, "create_drive_doc", fake_create_doc)
    monkeypatch.setattr(extraction_module, "extract_summary_text", fake_extract)
    # pc_router has its own bound name; patch it too so the delete-doc
    # endpoint (which resolves the helper through this module) is mocked.
    monkeypatch.setattr(pc_router, "get_valid_google_token", fake_token)

    client.cookies.set("noted_session", _signed_session_cookie(user_id))
    yield {"user_id": user_id, "meeting_id": meeting_id, "ctx_id": ctx_id}


# --- handoff service tests --------------------------------------------------


@pytest.mark.asyncio
async def test_file_meeting_creates_doc_row(seeded):
    from app.services.handoff import file_meeting_to_context

    async with SessionLocal() as session:
        result = await file_meeting_to_context(
            session,
            meeting_id=seeded["meeting_id"],
            project_context_id=seeded["ctx_id"],
            user_id=seeded["user_id"],
        )

    assert result.status == "success"
    assert result.drive_doc_id is not None
    assert result.drive_doc_url is not None

    async with SessionLocal() as session:
        row = (
            await session.execute(
                # using a fresh session — re-query
                pc_router.select(ProjectContextDoc).where(
                    ProjectContextDoc.project_context_id == seeded["ctx_id"]
                )
            )
        ).scalar_one()
        assert row.status == "success"
        assert row.item_type == "meeting"
        assert row.item_ref == str(seeded["meeting_id"])
        assert row.trigger == "manual"


@pytest.mark.asyncio
async def test_file_meeting_idempotent(seeded):
    """Second call returns 'skipped' with the existing Doc, no second Drive
    write."""
    from app.services.handoff import file_meeting_to_context

    calls = {"count": 0}

    real_create_doc = handoff_module.create_drive_doc

    async def counting_create_doc(*args, **kwargs):
        calls["count"] += 1
        return await real_create_doc(*args, **kwargs)

    handoff_module.create_drive_doc = counting_create_doc
    try:
        async with SessionLocal() as session:
            first = await file_meeting_to_context(
                session,
                meeting_id=seeded["meeting_id"],
                project_context_id=seeded["ctx_id"],
                user_id=seeded["user_id"],
            )
        async with SessionLocal() as session:
            second = await file_meeting_to_context(
                session,
                meeting_id=seeded["meeting_id"],
                project_context_id=seeded["ctx_id"],
                user_id=seeded["user_id"],
            )
    finally:
        handoff_module.create_drive_doc = real_create_doc

    assert first.status == "success"
    assert second.status == "skipped"
    assert second.drive_doc_id == first.drive_doc_id
    assert calls["count"] == 1  # only the first run actually hit Drive


@pytest.mark.asyncio
async def test_file_meeting_missing_summary_file(seeded):
    """A meeting without a summary_file_id is recorded as 'failed' with a
    clear message; no Drive write happens."""
    from app.services.handoff import file_meeting_to_context

    # Strip the summary id
    async with SessionLocal() as session:
        meeting = await session.get(Meeting, seeded["meeting_id"])
        meeting.summary_file_id = None
        await session.commit()

    async with SessionLocal() as session:
        result = await file_meeting_to_context(
            session,
            meeting_id=seeded["meeting_id"],
            project_context_id=seeded["ctx_id"],
            user_id=seeded["user_id"],
        )
    assert result.status == "failed"
    assert "summary" in result.error.lower()


@pytest.mark.asyncio
async def test_file_meeting_unknown_meeting(seeded):
    from app.services.handoff import file_meeting_to_context

    async with SessionLocal() as session:
        result = await file_meeting_to_context(
            session,
            meeting_id=99999,
            project_context_id=seeded["ctx_id"],
            user_id=seeded["user_id"],
        )
    assert result.status == "failed"
    assert "not found" in result.error.lower()


# --- HTTP endpoint tests ----------------------------------------------------


@pytest.mark.asyncio
async def test_post_file_meeting_succeeds(client, seeded):
    r = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["projectContextId"] == seeded["ctx_id"]
    assert len(body["results"]) == 1
    item = body["results"][0]
    assert item["status"] == "success"
    assert item["driveDocId"] is not None


@pytest.mark.asyncio
async def test_post_file_ticket_succeeds(client, seeded, monkeypatch):
    """Ticket handoff: backend fetches the Jira issue, builds a Doc, files
    into the Project Context's folder."""
    from app.models import OAuthCredential
    from app.services import handoff as handoff_module

    # Atlassian credential needs to exist for cloud_id lookup
    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=seeded["user_id"],
                provider="atlassian",
                access_token="enc",
                refresh_token="enc",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    async def fake_atlassian_token(session, _user_id):
        return "atl-token"

    async def fake_get_issue(token, cloud_id, key):
        assert key == "BACK-12"
        return {
            "key": "BACK-12",
            "summary": "Fix the thing",
            "type": "Bug",
            "priority": "High",
            "status": "In Progress",
            "project": {"key": "BACK", "name": "Backend"},
            "assignee": {"email": "x@y.com", "displayName": "X Y"},
            "updatedAt": "2026-06-14T10:00:00.000Z",
            "description": "Broken",
            "comments": [
                {
                    "id": "1",
                    "author": {
                        "email": "a@b.com",
                        "displayName": "A B",
                    },
                    "body": "Looking",
                    "createdAt": "2026-06-14T11:00:00.000Z",
                }
            ],
        }

    monkeypatch.setattr(handoff_module, "get_valid_atlassian_token", fake_atlassian_token)
    monkeypatch.setattr(handoff_module, "get_issue", fake_get_issue)

    r = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "ticket", "ref": "BACK-12"}]},
    )
    assert r.status_code == 200, r.text
    item = r.json()["results"][0]
    assert item["status"] == "success", item
    assert item["driveDocId"] is not None
    assert item["type"] == "ticket"
    assert item["ref"] == "BACK-12"


@pytest.mark.asyncio
async def test_ticket_handoff_idempotent(client, seeded, monkeypatch):
    """Second file of the same ticket returns 'skipped' with the existing
    Doc; only the first call hits Drive."""
    from app.models import OAuthCredential
    from app.services import handoff as handoff_module

    async with SessionLocal() as session:
        session.add(
            OAuthCredential(
                user_id=seeded["user_id"],
                provider="atlassian",
                access_token="enc",
                refresh_token="enc",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                scopes="x",
                atlassian_cloud_id="cloud-1",
            )
        )
        await session.commit()

    drive_calls = {"n": 0}
    real_create = handoff_module.create_drive_doc

    async def counting_create(token, name, parent, body):
        drive_calls["n"] += 1
        return await real_create(token, name, parent, body)

    async def fake_atlassian_token(session, _user_id):
        return "atl-token"

    async def fake_get_issue(token, cloud_id, key):
        return {
            "key": key,
            "summary": "Whatever",
            "type": "Task",
            "status": "To Do",
            "project": {"key": "P", "name": "P"},
            "assignee": None,
            "description": "",
            "comments": [],
        }

    monkeypatch.setattr(handoff_module, "get_valid_atlassian_token", fake_atlassian_token)
    monkeypatch.setattr(handoff_module, "get_issue", fake_get_issue)
    monkeypatch.setattr(handoff_module, "create_drive_doc", counting_create)

    r1 = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "ticket", "ref": "P-1"}]},
    )
    r2 = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "ticket", "ref": "P-1"}]},
    )
    assert r1.json()["results"][0]["status"] == "success"
    assert r2.json()["results"][0]["status"] == "skipped"
    assert drive_calls["n"] == 1


@pytest.mark.asyncio
async def test_ticket_handoff_atlassian_not_connected(client, seeded):
    """File a ticket when the user has no Atlassian credential — records a
    failed row with a clear error."""
    r = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "ticket", "ref": "P-2"}]},
    )
    assert r.status_code == 200
    item = r.json()["results"][0]
    assert item["status"] == "failed"
    assert "not connected" in item["error"].lower()


# --- Ticket Doc body shape -------------------------------------------------


def test_ticket_doc_name_truncates_long_summaries():
    from app.services.handoff import _ticket_doc_name

    ticket = {"key": "BACK-1", "summary": "x" * 100}
    out = _ticket_doc_name(ticket, "Team Best")
    assert out.startswith("[Team Best] BACK-1 - ")
    assert "…" in out
    assert len(out) <= len("[Team Best] BACK-1 - ") + 80


def test_ticket_doc_body_includes_meta_and_comments():
    from app.services.handoff import _ticket_doc_body

    body = _ticket_doc_body(
        {
            "key": "BACK-1",
            "summary": "Fix it",
            "type": "Bug",
            "priority": "High",
            "status": "In Progress",
            "project": {"key": "BACK", "name": "Backend"},
            "assignee": {"email": "x@y.com", "displayName": "X Y"},
            "description": "It broke.",
            "comments": [
                {
                    "author": {"displayName": "A B"},
                    "body": "I'll look.",
                    "createdAt": "2026-06-14T11:00:00.000Z",
                }
            ],
        }
    )
    assert "Ticket: BACK-1" in body
    assert "Project: Backend (BACK)" in body
    assert "Assignee: X Y <x@y.com>" in body
    assert "It broke." in body
    assert "Comments (1):" in body
    assert "I'll look." in body


@pytest.mark.asyncio
async def test_post_file_unknown_context_404(client, seeded):
    r = await client.post(
        "/api/project-contexts/9999/file",
        json={"items": [{"type": "meeting", "ref": "1"}]},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_docs_list(client, seeded):
    # File one first so there's something to list
    await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )

    r = await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    assert r.status_code == 200
    docs = r.json()
    assert len(docs) == 1
    assert docs[0]["itemType"] == "meeting"
    assert docs[0]["itemRef"] == str(seeded["meeting_id"])
    assert docs[0]["status"] == "success"


@pytest.mark.asyncio
async def test_get_docs_unknown_context_404(client, seeded):
    r = await client.get("/api/project-contexts/9999/docs")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_file_unauthenticated(client):
    # Clear any session cookie
    client.cookies.clear()
    r = await client.post(
        "/api/project-contexts/1/file",
        json={"items": [{"type": "meeting", "ref": "1"}]},
    )
    assert r.status_code == 401


# --- delete filed Doc -------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_filed_doc_trashes_drive(client, seeded, monkeypatch):
    """Deleting a filed Doc removes the row AND trashes the Drive file."""
    trash_calls: list[str] = []

    async def fake_trash(token, file_id):
        trash_calls.append(file_id)

    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    # First file the meeting so there's a doc row
    file_r = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )
    assert file_r.status_code == 200
    doc_drive_id = file_r.json()["results"][0]["driveDocId"]

    # Look up the doc_id from the docs list
    docs_r = await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    assert docs_r.status_code == 200
    doc_id = docs_r.json()[0]["id"]

    # Delete it
    del_r = await client.delete(
        f"/api/project-contexts/{seeded['ctx_id']}/docs/{doc_id}"
    )
    assert del_r.status_code == 200, del_r.text
    body = del_r.json()
    assert body["driveTrashed"] is True
    assert body["driveDocId"] == doc_drive_id
    assert trash_calls == [doc_drive_id]

    # Row is gone
    docs_after = await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    assert docs_after.json() == []


@pytest.mark.asyncio
async def test_delete_filed_doc_keep_drive(client, seeded, monkeypatch):
    """deleteDriveFile=false leaves the Drive Doc alone."""
    trash_calls: list[str] = []

    async def fake_trash(token, file_id):
        trash_calls.append(file_id)

    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    file_r = await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )
    doc_id = (
        await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    ).json()[0]["id"]

    del_r = await client.delete(
        f"/api/project-contexts/{seeded['ctx_id']}/docs/{doc_id}?deleteDriveFile=false"
    )
    assert del_r.status_code == 200
    assert del_r.json()["driveTrashed"] is False
    assert trash_calls == []
    assert file_r.status_code == 200  # silence unused


@pytest.mark.asyncio
async def test_delete_filed_doc_wrong_context_404(client, seeded, monkeypatch):
    async def fake_trash(token, file_id):
        pass

    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )
    doc_id = (
        await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    ).json()[0]["id"]

    # Attempt delete under the wrong context id
    r = await client.delete(f"/api/project-contexts/99999/docs/{doc_id}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_filed_doc_drive_error_still_removes_row(
    client, seeded, monkeypatch
):
    from app.services.google import DriveAccessError

    async def fake_trash(token, file_id):
        raise DriveAccessError("simulated 403")

    monkeypatch.setattr(pc_router, "trash_drive_file", fake_trash)

    await client.post(
        f"/api/project-contexts/{seeded['ctx_id']}/file",
        json={"items": [{"type": "meeting", "ref": str(seeded["meeting_id"])}]},
    )
    doc_id = (
        await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    ).json()[0]["id"]

    r = await client.delete(
        f"/api/project-contexts/{seeded['ctx_id']}/docs/{doc_id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["driveTrashed"] is False
    assert "simulated 403" in body["driveError"]
    # Row still removed
    docs_after = await client.get(f"/api/project-contexts/{seeded['ctx_id']}/docs")
    assert docs_after.json() == []
