"""
Tests for the Jira read client + /api/tickets routes.

Atlassian HTTP is patched; the focus is on:
- status → column mapping (load-bearing for the Kanban)
- ADF → text rendering (load-bearing for Slice C's ticket Doc body)
- ticket projection shape
- auth + precondition behaviour on the routes
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.crypto import encrypt
from app.db import SessionLocal
from app.models import OAuthCredential, User
from app.routers import tickets as tickets_router
from app.services.atlassian import adf_to_text, status_to_column


# --- status mapping (pure function) -----------------------------------------


class TestStatusToColumn:
    def test_new_category_to_todo(self):
        assert (
            status_to_column({"name": "To Do", "statusCategory": {"key": "new"}})
            == "todo"
        )

    def test_done_category_to_done(self):
        assert (
            status_to_column({"name": "Done", "statusCategory": {"key": "done"}})
            == "done"
        )

    def test_indeterminate_to_in_progress(self):
        assert (
            status_to_column(
                {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}
            )
            == "in_progress"
        )

    def test_review_name_to_in_review(self):
        assert (
            status_to_column(
                {"name": "In Review", "statusCategory": {"key": "indeterminate"}}
            )
            == "in_review"
        )

    def test_code_review_name_to_in_review(self):
        assert (
            status_to_column(
                {"name": "Code Review", "statusCategory": {"key": "indeterminate"}}
            )
            == "in_review"
        )

    def test_unknown_category_falls_back_to_in_progress(self):
        # Falls into the indeterminate branch, no "review" in name → in_progress
        assert status_to_column({"name": "Limbo"}) == "in_progress"


# --- ADF -> text -------------------------------------------------------------


class TestAdfToText:
    def test_simple_paragraph(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}],
                }
            ],
        }
        assert adf_to_text(adf) == "Hello world"

    def test_multiple_paragraphs_separated_by_newline(self):
        adf = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "One"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "Two"}]},
            ],
        }
        # Trailing newline stripped by `doc`; one block boundary between
        assert adf_to_text(adf) == "One\nTwo"

    def test_bullet_list(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Item A"}
                                    ],
                                }
                            ],
                        },
                        {
                            "type": "listItem",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "text", "text": "Item B"}
                                    ],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
        out = adf_to_text(adf)
        assert "Item A" in out
        assert "Item B" in out

    def test_marks_ignored(self):
        """Bold/italic marks are dropped — plain text only."""
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "Bold!",
                            "marks": [{"type": "strong"}],
                        }
                    ],
                }
            ],
        }
        assert adf_to_text(adf) == "Bold!"

    def test_empty_doc(self):
        assert adf_to_text({"type": "doc", "content": []}) == ""

    def test_none_returns_empty(self):
        assert adf_to_text(None) == ""


# --- /api/tickets routes ----------------------------------------------------


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
            google_sub="sub-tickets-test",
            email="t@example.com",
            display_name="T",
            avatar_initials="T",
        )
        session.add(u)
        await session.commit()
        user_id = u.id
    client.cookies.set("noted_session", _signed_session_cookie(user_id))
    yield user_id


@pytest.fixture
async def with_atlassian_cred(signed_in_user):
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
    return signed_in_user


@pytest.mark.asyncio
async def test_tickets_unauthenticated(client):
    client.cookies.clear()
    r = await client.get("/api/tickets")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_tickets_412_when_atlassian_not_connected(client, signed_in_user):
    r = await client.get("/api/tickets")
    assert r.status_code == 412
    assert "Atlassian" in r.json()["detail"]


@pytest.mark.asyncio
async def test_tickets_happy_path_groups_projects(
    client, with_atlassian_cred, monkeypatch
):
    async def fake_token(session, _user_id):
        return "fake-token"

    async def fake_list(token, cloud_id):
        # Two tickets in the same project, one in another — project list
        # should de-dupe and sort
        return [
            {
                "key": "BACK-1",
                "summary": "First",
                "type": "Bug",
                "typeIconUrl": None,
                "priority": "High",
                "priorityIconUrl": None,
                "status": "To Do",
                "column": "todo",
                "project": {"key": "BACK", "name": "Backend", "iconUrl": None},
                "assignee": None,
                "updatedAt": "2026-06-14T10:00:00.000Z",
            },
            {
                "key": "BACK-2",
                "summary": "Second",
                "type": "Story",
                "typeIconUrl": None,
                "priority": None,
                "priorityIconUrl": None,
                "status": "In Progress",
                "column": "in_progress",
                "project": {"key": "BACK", "name": "Backend", "iconUrl": None},
                "assignee": None,
                "updatedAt": "2026-06-14T09:00:00.000Z",
            },
            {
                "key": "AAA-9",
                "summary": "Other",
                "type": "Task",
                "typeIconUrl": None,
                "priority": None,
                "priorityIconUrl": None,
                "status": "Done",
                "column": "done",
                "project": {"key": "AAA", "name": "Apps", "iconUrl": None},
                "assignee": None,
                "updatedAt": "2026-06-14T08:00:00.000Z",
            },
        ]

    monkeypatch.setattr(tickets_router, "get_valid_atlassian_token", fake_token)
    monkeypatch.setattr(tickets_router, "list_assigned_issues", fake_list)

    r = await client.get("/api/tickets")
    assert r.status_code == 200
    body = r.json()
    assert len(body["tickets"]) == 3
    # Projects sorted by name
    assert [p["key"] for p in body["projects"]] == ["AAA", "BACK"]


@pytest.mark.asyncio
async def test_ticket_detail_happy_path(
    client, with_atlassian_cred, monkeypatch
):
    async def fake_token(session, _user_id):
        return "fake-token"

    async def fake_get(token, cloud_id, issue_key):
        assert issue_key == "BACK-1"
        return {
            "key": "BACK-1",
            "summary": "Make it work",
            "type": "Bug",
            "typeIconUrl": None,
            "priority": "High",
            "priorityIconUrl": None,
            "status": "In Progress",
            "column": "in_progress",
            "project": {"key": "BACK", "name": "Backend", "iconUrl": None},
            "assignee": {"email": "x@y.com", "displayName": "X Y", "avatarUrl": None},
            "updatedAt": "2026-06-14T10:00:00.000Z",
            "description": "Broken thing",
            "descriptionHtml": "<p>Broken thing</p>",
            "comments": [
                {
                    "id": "1",
                    "author": {
                        "email": "a@b.com",
                        "displayName": "A B",
                        "avatarUrl": None,
                    },
                    "body": "I'll take a look",
                    "bodyHtml": "<p>I'll take a look</p>",
                    "createdAt": "2026-06-14T11:00:00.000Z",
                    "updatedAt": "2026-06-14T11:00:00.000Z",
                }
            ],
        }

    monkeypatch.setattr(tickets_router, "get_valid_atlassian_token", fake_token)
    monkeypatch.setattr(tickets_router, "get_issue", fake_get)

    r = await client.get("/api/tickets/BACK-1")
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "BACK-1"
    assert body["description"] == "Broken thing"
    assert len(body["comments"]) == 1


@pytest.mark.asyncio
async def test_ticket_detail_404(client, with_atlassian_cred, monkeypatch):
    from app.services.atlassian import AtlassianAuthError

    async def fake_token(session, _user_id):
        return "fake-token"

    async def fake_get(token, cloud_id, issue_key):
        raise AtlassianAuthError(f"Jira issue {issue_key} not found")

    monkeypatch.setattr(tickets_router, "get_valid_atlassian_token", fake_token)
    monkeypatch.setattr(tickets_router, "get_issue", fake_get)

    r = await client.get("/api/tickets/NOPE-99")
    assert r.status_code == 404
