"""
Thin async Atlassian (Jira + Confluence) client.

Phase 5 uses only the Jira-read endpoints, but the OAuth scope set we
request now also covers Confluence read/write so Phase 6 doesn't trigger
a second consent prompt.

Token lifecycle:
- Atlassian access tokens last ~1 hour. The refresh helper here mirrors
  `services/google.get_valid_google_token` — decrypt, check expiry, hit
  the token endpoint with `grant_type=refresh_token` if needed, persist.
- Atlassian rotates refresh tokens on every refresh — we always store
  the new refresh token returned in the refresh response.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..models import OAuthCredential


log = logging.getLogger(__name__)

ATLASSIAN_AUTHORIZE_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_ACCESSIBLE_RESOURCES_URL = (
    "https://api.atlassian.com/oauth/token/accessible-resources"
)
ATLASSIAN_API_BASE = "https://api.atlassian.com/ex/jira"

_REFRESH_LEEWAY = timedelta(seconds=60)


class AtlassianAuthError(RuntimeError):
    """The user's Atlassian credential is unusable — missing, can't be
    decrypted, refresh failed, or the user revoked access. Callers should
    surface this so the UI can prompt the user to reconnect Atlassian."""


async def list_accessible_resources(token: str) -> list[dict[str, Any]]:
    """Return the array of {id, name, url, scopes, avatarUrl} a user has
    consented to. We persist the first id as `oauth_credentials.atlassian_cloud_id`."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(ATLASSIAN_ACCESSIBLE_RESOURCES_URL, headers=headers)
    if resp.status_code != 200:
        raise AtlassianAuthError(
            f"accessible-resources returned {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()


async def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    """Atlassian-specific code exchange — Authlib can do this for us, but
    keeping it explicit makes the test surface clearer."""
    settings = get_settings()
    body = {
        "grant_type": "authorization_code",
        "client_id": settings.atlassian_client_id,
        "client_secret": settings.atlassian_client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            ATLASSIAN_TOKEN_URL,
            json=body,
            headers={"Content-Type": "application/json"},
        )
    if resp.status_code != 200:
        raise AtlassianAuthError(
            f"token exchange failed: {resp.status_code} {resp.text[:200]}"
        )
    return resp.json()


async def get_valid_atlassian_token(session: AsyncSession, user_id: int) -> str:
    """Return a non-expired plaintext access token for the user. Refreshes
    when needed and persists the new pair (Atlassian rotates refresh tokens)."""
    settings = get_settings()

    result = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user_id,
            OAuthCredential.provider == "atlassian",
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        raise AtlassianAuthError(
            f"User {user_id} has no Atlassian credential — user must connect Atlassian"
        )

    now = datetime.now(timezone.utc)
    needs_refresh = cred.expires_at is None or cred.expires_at - now <= _REFRESH_LEEWAY

    if not needs_refresh:
        try:
            return decrypt(cred.access_token)
        except InvalidToken as exc:
            raise AtlassianAuthError(
                f"User {user_id} stored Atlassian access token can't be decrypted "
                "(encryption key rotated?); user must reconnect Atlassian."
            ) from exc

    if not cred.refresh_token:
        raise AtlassianAuthError(
            f"User {user_id} Atlassian credential expired and has no refresh token; "
            "user must reconnect Atlassian."
        )

    try:
        refresh_token_plain = decrypt(cred.refresh_token)
    except InvalidToken as exc:
        raise AtlassianAuthError(
            f"User {user_id} stored Atlassian refresh token can't be decrypted; "
            "user must reconnect Atlassian."
        ) from exc

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            ATLASSIAN_TOKEN_URL,
            json={
                "grant_type": "refresh_token",
                "client_id": settings.atlassian_client_id,
                "client_secret": settings.atlassian_client_secret,
                "refresh_token": refresh_token_plain,
            },
            headers={"Content-Type": "application/json"},
        )

    if resp.status_code != 200:
        log.warning(
            "atlassian token refresh failed user_id=%s status=%s",
            user_id,
            resp.status_code,
        )
        raise AtlassianAuthError(
            f"Atlassian token refresh failed (status {resp.status_code})"
        )

    payload = resp.json()
    new_access = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    cred.access_token = encrypt(new_access)
    cred.expires_at = new_expires_at
    # Atlassian rotates the refresh token on every refresh — always persist
    # the new one if present.
    if "refresh_token" in payload and payload["refresh_token"]:
        cred.refresh_token = encrypt(payload["refresh_token"])
    if "scope" in payload:
        cred.scopes = payload["scope"]

    await session.commit()
    return new_access


# --- Jira read client --------------------------------------------------------


def _jira_base(cloud_id: str) -> str:
    """Atlassian routes Jira API v3 through the central api.atlassian.com
    host scoped by cloudId."""
    return f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"


def status_to_column(status: dict[str, Any]) -> str:
    """Map a Jira issue's `status` object to one of our four Kanban columns.

    We use `statusCategory.key` because it's stable across custom workflows
    (Jira guarantees only three categories: `new`, `indeterminate`, `done`).
    The `In Review` column is a heuristic — any `indeterminate` status whose
    name contains "review" lands there; everything else `indeterminate` is
    `in_progress`. Per spec §11 this maps the customer's *actual* workflow
    rather than hardcoding four columns into the data model.
    """
    category = (status.get("statusCategory") or {}).get("key", "")
    name = (status.get("name") or "").lower()
    if category == "new":
        return "todo"
    if category == "done":
        return "done"
    if "review" in name:
        return "in_review"
    return "in_progress"


def adf_to_text(node: Any) -> str:
    """
    Walk an Atlassian Document Format tree and return a plain-text rendering.

    ADF is a JSON tree of nodes with `type`, optional `text`, and optional
    `content`. We concatenate text leaves and insert newlines around block
    elements (paragraph, heading, listItem, codeBlock). Lossy but faithful
    for the kinds of formatting Jira comments typically contain.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    text = node.get("text")
    children: list[Any] = node.get("content") or []

    if text is not None:
        # Leaf text node — `marks` (bold, code, etc.) are ignored in the
        # plain-text rendering.
        return str(text)

    parts = [adf_to_text(child) for child in children]
    joined = "".join(parts)

    # Add block-level separators
    block_types = {
        "paragraph",
        "heading",
        "listItem",
        "bulletList",
        "orderedList",
        "codeBlock",
        "blockquote",
        "rule",
    }
    if node_type in block_types:
        return joined + "\n"
    if node_type == "doc":
        return joined.strip()
    return joined


async def list_assigned_issues(
    token: str, cloud_id: str
) -> list[dict[str, Any]]:
    """
    Issues assigned to the current user, newest first. Returns a trimmed
    projection ready for the Kanban — including the pre-mapped `column`.

    JQL: `assignee = currentUser() ORDER BY updated DESC` (per spec §11).
    We don't paginate beyond the first 100 in the MVP — sorting by `updated`
    means the active stuff is on top, and Jira's max page size is 100.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {
        "jql": "assignee = currentUser() ORDER BY updated DESC",
        "fields": "summary,status,issuetype,priority,project,assignee,updated",
        "maxResults": "100",
    }
    # NB: Atlassian retired /search in May 2025 in favour of /search/jql
    # (cursor pagination, no `total`, explicit `fields` required). The new
    # endpoint returns the same shape for our purposes — we ignore
    # nextPageToken for the MVP since maxResults=100 + ORDER BY updated DESC
    # keeps the active set on top.
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{_jira_base(cloud_id)}/search/jql",
            headers=headers,
            params=params,
        )
    if resp.status_code != 200:
        log.warning("jira search failed status=%s body=%s", resp.status_code, resp.text[:200])
        raise AtlassianAuthError(
            f"Jira search failed with status {resp.status_code}"
        )
    payload = resp.json()

    out: list[dict[str, Any]] = []
    for issue in payload.get("issues", []):
        fields = issue.get("fields", {}) or {}
        status = fields.get("status") or {}
        project = fields.get("project") or {}
        issuetype = fields.get("issuetype") or {}
        priority = fields.get("priority") or {}
        assignee = fields.get("assignee") or {}
        out.append(
            {
                "key": issue.get("key", ""),
                "summary": fields.get("summary", ""),
                "type": issuetype.get("name") or "",
                "typeIconUrl": issuetype.get("iconUrl"),
                "priority": priority.get("name"),
                "priorityIconUrl": priority.get("iconUrl"),
                "status": status.get("name", ""),
                "column": status_to_column(status),
                "project": {
                    "key": project.get("key", ""),
                    "name": project.get("name", ""),
                    "iconUrl": ((project.get("avatarUrls") or {}).get("24x24")),
                },
                "assignee": (
                    {
                        "email": assignee.get("emailAddress") or "",
                        "displayName": assignee.get("displayName") or "",
                        "avatarUrl": (assignee.get("avatarUrls") or {}).get("24x24"),
                    }
                    if assignee
                    else None
                ),
                "updatedAt": fields.get("updated"),
            }
        )
    return out


async def get_myself(token: str, cloud_id: str) -> dict[str, Any]:
    """`GET /rest/api/3/myself` — the Atlassian user the OAuth token belongs
    to. Used by /api/me/atlassian-identity so the UI can show "Connected
    as <name>" and the user can spot a wrong-account OAuth grant."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_jira_base(cloud_id)}/myself", headers=headers)
    if resp.status_code != 200:
        raise AtlassianAuthError(
            f"/myself failed with status {resp.status_code}: {resp.text[:200]}"
        )
    payload = resp.json()
    avatar_urls = payload.get("avatarUrls") or {}
    return {
        "accountId": payload.get("accountId"),
        "email": payload.get("emailAddress") or "",
        "displayName": payload.get("displayName") or "",
        "avatarUrl": avatar_urls.get("48x48") or avatar_urls.get("32x32"),
    }


async def get_issue(
    token: str, cloud_id: str, issue_key: str
) -> dict[str, Any]:
    """Issue detail: description + comments, ADF -> plain text."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params = {
        "fields": "summary,status,issuetype,priority,project,assignee,updated,description,comment",
        # `renderedFields` adds an HTML-rendered version of the description
        # and each comment body alongside the raw ADF. We surface both:
        # text for Slice C's Doc handoff body, HTML for the UI.
        "expand": "renderedFields",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(
            f"{_jira_base(cloud_id)}/issue/{issue_key}",
            headers=headers,
            params=params,
        )
    if resp.status_code == 404:
        raise AtlassianAuthError(f"Jira issue {issue_key} not found")
    if resp.status_code != 200:
        log.warning(
            "jira get_issue failed key=%s status=%s body=%s",
            issue_key,
            resp.status_code,
            resp.text[:200],
        )
        raise AtlassianAuthError(
            f"Jira get_issue {issue_key} failed with status {resp.status_code}"
        )
    issue = resp.json()
    fields = issue.get("fields", {}) or {}
    status = fields.get("status") or {}
    project = fields.get("project") or {}
    issuetype = fields.get("issuetype") or {}
    priority = fields.get("priority") or {}
    assignee = fields.get("assignee") or {}

    rendered = issue.get("renderedFields") or {}

    description_adf = fields.get("description")
    description_text = adf_to_text(description_adf) if description_adf else ""
    description_html = rendered.get("description") or ""

    # The rendered-fields comment payload mirrors the raw comments list
    # one-to-one; align them by id for safety.
    rendered_comments_by_id: dict[str, str] = {}
    for rc in ((rendered.get("comment") or {}).get("comments") or []):
        cid = rc.get("id")
        if cid:
            rendered_comments_by_id[cid] = rc.get("body", "") or ""

    comments_out: list[dict[str, Any]] = []
    for c in ((fields.get("comment") or {}).get("comments") or []):
        author = c.get("author") or {}
        comments_out.append(
            {
                "id": c.get("id"),
                "bodyHtml": rendered_comments_by_id.get(c.get("id"), ""),
                "author": {
                    "email": author.get("emailAddress") or "",
                    "displayName": author.get("displayName") or "",
                    "avatarUrl": (author.get("avatarUrls") or {}).get("24x24"),
                },
                "body": adf_to_text(c.get("body")),
                "createdAt": c.get("created"),
                "updatedAt": c.get("updated"),
            }
        )

    return {
        "key": issue.get("key", ""),
        "summary": fields.get("summary", ""),
        "type": issuetype.get("name") or "",
        "typeIconUrl": issuetype.get("iconUrl"),
        "priority": priority.get("name"),
        "priorityIconUrl": priority.get("iconUrl"),
        "status": status.get("name", ""),
        "column": status_to_column(status),
        "project": {
            "key": project.get("key", ""),
            "name": project.get("name", ""),
            "iconUrl": ((project.get("avatarUrls") or {}).get("24x24")),
        },
        "assignee": (
            {
                "email": assignee.get("emailAddress") or "",
                "displayName": assignee.get("displayName") or "",
                "avatarUrl": (assignee.get("avatarUrls") or {}).get("24x24"),
            }
            if assignee
            else None
        ),
        "updatedAt": fields.get("updated"),
        "description": description_text,
        "descriptionHtml": description_html,
        "comments": comments_out,
    }
