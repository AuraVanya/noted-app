"""
Thin async Google clients (Drive + Calendar) built on httpx.

We use raw HTTP instead of `google-api-python-client` because:
- the SDK is synchronous-first and heavy,
- we only touch three endpoints,
- httpx is already a dep from Phase 1.

Token lifecycle lives here too: `get_valid_google_token` is the single
entry point for any caller that needs to talk to Google as a given user.
It refreshes and re-encrypts the stored credential when needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import decrypt, encrypt
from ..models import OAuthCredential


log = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_FILES_URL = "https://www.googleapis.com/drive/v3/files"
CALENDAR_EVENTS_URL = (
    "https://www.googleapis.com/calendar/v3/calendars/primary/events"
)

# Refresh ahead of expiry by this much so a request issued *now* still has
# time to hit Google with a valid token.
_REFRESH_LEEWAY = timedelta(seconds=60)


class GoogleAuthError(RuntimeError):
    """The user's Google credential is unusable (missing or refresh failed)."""


async def get_valid_google_token(session: AsyncSession, user_id: int) -> str:
    """
    Return a non-expired plaintext access token for the user.

    Refreshes via Google's token endpoint if necessary, persists the new
    encrypted token + expiry to oauth_credentials, and commits.
    """
    settings = get_settings()

    result = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user_id,
            OAuthCredential.provider == "google",
        )
    )
    cred = result.scalar_one_or_none()
    if cred is None:
        raise GoogleAuthError(f"User {user_id} has no Google credential on file")

    now = datetime.now(timezone.utc)
    needs_refresh = cred.expires_at is None or cred.expires_at - now <= _REFRESH_LEEWAY

    if not needs_refresh:
        try:
            return decrypt(cred.access_token)
        except InvalidToken as exc:
            # Stored token was encrypted with a *different* TOKEN_ENC_KEY
            # than the one currently in env — usually means the key was
            # rotated. Surface cleanly so the caller can prompt re-auth.
            raise GoogleAuthError(
                f"User {user_id} stored Google access token cannot be decrypted "
                "(encryption key rotated?); user must re-consent."
            ) from exc

    if not cred.refresh_token:
        raise GoogleAuthError(
            f"User {user_id} Google credential expired and has no refresh token; "
            "the user needs to re-consent."
        )

    try:
        refresh_token_plain = decrypt(cred.refresh_token)
    except InvalidToken as exc:
        raise GoogleAuthError(
            f"User {user_id} stored Google refresh token cannot be decrypted "
            "(encryption key rotated?); user must re-consent."
        ) from exc

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh_token_plain,
                "grant_type": "refresh_token",
            },
        )

    if resp.status_code != 200:
        # Google returned 4xx/5xx — log without leaking secrets
        log.warning(
            "google token refresh failed for user_id=%s status=%s",
            user_id,
            resp.status_code,
        )
        raise GoogleAuthError(
            f"Google token refresh failed (status {resp.status_code})"
        )

    payload = resp.json()
    new_access = payload["access_token"]
    expires_in = int(payload.get("expires_in", 3600))
    new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    cred.access_token = encrypt(new_access)
    cred.expires_at = new_expires_at
    # Google may issue a new refresh token here; usually it does not.
    if "refresh_token" in payload:
        cred.refresh_token = encrypt(payload["refresh_token"])
    if "scope" in payload:
        cred.scopes = payload["scope"]

    await session.commit()
    return new_access


# --- Drive --------------------------------------------------------------------


async def list_drive_folder(
    token: str, folder_id: str
) -> list[dict[str, Any]]:
    """
    Return every non-trashed file directly inside `folder_id`.

    Each item is `{id, name, createdTime, mimeType}`. Pagination is handled
    internally; the caller gets the full list. Shared-drive flags are set so
    folders living inside a shared drive also work without further config.
    """
    if not folder_id:
        return []

    headers = {"Authorization": f"Bearer {token}"}
    base_params = {
        "q": f"'{folder_id}' in parents and trashed = false",
        "fields": "nextPageToken, files(id, name, createdTime, mimeType)",
        "pageSize": "1000",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }

    out: list[dict[str, Any]] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = dict(base_params)
            if page_token:
                params["pageToken"] = page_token
            resp = await client.get(DRIVE_FILES_URL, headers=headers, params=params)
            if resp.status_code != 200:
                log.warning(
                    "drive list failed folder=%s status=%s",
                    folder_id,
                    resp.status_code,
                )
                resp.raise_for_status()
            body = resp.json()
            out.extend(body.get("files", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
    return out


# Drive file *body* streaming lives in routers/files.py — the streaming
# response needs to live in the same async scope as the client, so it's
# clearer to keep it next to the FastAPI handler than to wrap it here.


# --- Drive write (needs the drive.file scope) ---------------------------------


class DriveAccessError(RuntimeError):
    """Drive returned 4xx for a write operation. Most commonly a missing
    scope on the user's token (they need to re-consent) or a stale
    folder id."""


def _ensure_drive_ok(resp: httpx.Response, action: str) -> None:
    if resp.status_code in (200, 201):
        return
    body_snip = resp.text[:200] if resp.text else ""
    if resp.status_code == 401:
        raise DriveAccessError(
            f"{action}: Drive returned 401 (token invalid or scope missing — re-consent required)"
        )
    if resp.status_code == 403:
        raise DriveAccessError(
            f"{action}: Drive returned 403 (insufficient scope; sign out and back in to grant Drive write)"
        )
    if resp.status_code == 404:
        raise DriveAccessError(f"{action}: Drive returned 404 (folder/file not found)")
    raise DriveAccessError(f"{action}: Drive returned {resp.status_code} {body_snip}")


async def create_drive_folder(
    token: str, name: str, parent_id: str | None = None
) -> dict[str, Any]:
    """Create a new Drive folder. Returns `{id, name, webViewLink}`."""
    headers = {"Authorization": f"Bearer {token}"}
    body: dict[str, Any] = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        body["parents"] = [parent_id]
    params = {
        "fields": "id, name, webViewLink",
        "supportsAllDrives": "true",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(DRIVE_FILES_URL, headers=headers, json=body, params=params)
    _ensure_drive_ok(resp, "create_drive_folder")
    return resp.json()


async def get_drive_folder(token: str, folder_id: str) -> dict[str, Any]:
    """Resolve a folder id to `{id, name, webViewLink, mimeType}`."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "fields": "id, name, webViewLink, mimeType",
        "supportsAllDrives": "true",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{DRIVE_FILES_URL}/{folder_id}", headers=headers, params=params
        )
    _ensure_drive_ok(resp, "get_drive_folder")
    payload = resp.json()
    if payload.get("mimeType") != "application/vnd.google-apps.folder":
        raise DriveAccessError(
            f"get_drive_folder: {folder_id} is not a folder ({payload.get('mimeType')})"
        )
    return payload


async def trash_drive_file(token: str, file_id: str) -> None:
    """
    Move a Drive file (or folder) to trash. We prefer trash over outright
    delete so the user can restore from Drive's trash UI within ~30 days
    if they regret the action.

    Limited by the drive.file scope to files Noted created (folders made
    via the Create-new-folder path) or that the user explicitly shared with
    our OAuth client (the Use-existing-folder path may or may not qualify).
    Caller should treat 403 as "we can't touch this; tell the user."
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    params = {"supportsAllDrives": "true"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{DRIVE_FILES_URL}/{file_id}",
            headers=headers,
            params=params,
            json={"trashed": True},
        )
    _ensure_drive_ok(resp, "trash_drive_file")


async def create_drive_doc(
    token: str,
    name: str,
    parent_folder_id: str,
    body_text: str,
) -> dict[str, Any]:
    """
    Create a Google Doc inside `parent_folder_id` with the given text body.

    Implementation uses Drive's `multipart` upload type: metadata + a
    text/plain body part. Setting `mimeType = application/vnd.google-apps
    .document` on the metadata makes Drive auto-convert the upload into a
    native Google Doc on the way in (much simpler than calling the Docs
    API afterwards to insert text).

    Returns `{id, name, webViewLink}`.
    """
    import json
    import secrets

    boundary = "noted-" + secrets.token_hex(16)
    metadata = {
        "name": name,
        "parents": [parent_folder_id],
        "mimeType": "application/vnd.google-apps.document",
    }
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n"
        f"--{boundary}\r\n"
        f"Content-Type: text/plain; charset=UTF-8\r\n\r\n"
        f"{body_text}\r\n"
        f"--{boundary}--"
    ).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/related; boundary={boundary}",
    }
    params = {
        "uploadType": "multipart",
        "fields": "id, name, webViewLink",
        "supportsAllDrives": "true",
    }
    upload_url = "https://www.googleapis.com/upload/drive/v3/files"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(upload_url, headers=headers, params=params, content=body)
    _ensure_drive_ok(resp, "create_drive_doc")
    return resp.json()


async def search_drive_folders(
    token: str, query: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Search the user's Drive for folders whose name contains `query`."""
    if not query.strip():
        return []
    # Escape single quotes to keep the q string sane
    safe_q = query.replace("'", "\\'")
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "q": (
            "mimeType = 'application/vnd.google-apps.folder' "
            f"and name contains '{safe_q}' and trashed = false"
        ),
        "fields": "files(id, name, webViewLink)",
        "pageSize": str(limit),
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
        "orderBy": "modifiedTime desc",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(DRIVE_FILES_URL, headers=headers, params=params)
    _ensure_drive_ok(resp, "search_drive_folders")
    return resp.json().get("files", [])


# --- Calendar -----------------------------------------------------------------


async def list_calendar_events(
    token: str, time_min: datetime, time_max: datetime
) -> list[dict[str, Any]]:
    """
    Return calendar events on the primary calendar in [time_min, time_max].

    Recurring events are expanded via singleEvents=true so each occurrence is
    its own item. Items include `id`, `summary`, `start`, `end`, `attendees`.
    """
    headers = {"Authorization": f"Bearer {token}"}
    base_params = {
        "timeMin": _iso_utc(time_min),
        "timeMax": _iso_utc(time_max),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": "2500",
    }

    out: list[dict[str, Any]] = []
    page_token: str | None = None
    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params = dict(base_params)
            if page_token:
                params["pageToken"] = page_token
            resp = await client.get(
                CALENDAR_EVENTS_URL, headers=headers, params=params
            )
            if resp.status_code != 200:
                log.warning("calendar list failed status=%s", resp.status_code)
                resp.raise_for_status()
            body = resp.json()
            out.extend(body.get("items", []))
            page_token = body.get("nextPageToken")
            if not page_token:
                break
    return out


def _iso_utc(dt: datetime) -> str:
    """RFC3339 with explicit Z, which Calendar's timeMin/timeMax expects."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def event_start(event: dict[str, Any]) -> datetime | None:
    """Pull the UTC start datetime from a Calendar event, if any."""
    start = event.get("start") or {}
    raw = start.get("dateTime")
    if not raw:
        return None  # all-day events have `date` instead of `dateTime`
    # dateTime is RFC3339 with offset, e.g. "2026-06-12T06:15:00+00:00" or "...Z"
    iso = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc)
    except ValueError:
        return None


def event_attendees(event: dict[str, Any]) -> list[dict[str, str]]:
    """Lean projection: [{email, displayName}] only."""
    attendees = event.get("attendees") or []
    out: list[dict[str, str]] = []
    for a in attendees:
        out.append({
            "email": a.get("email", ""),
            "displayName": a.get("displayName") or a.get("email", ""),
        })
    return out


def collect_normalized_titles(events: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Index events by normalized title for O(1) lookup during matching."""
    from .filename import normalize_title  # local import to avoid cycle at module load

    by_title: dict[str, list[dict[str, Any]]] = {}
    for ev in events:
        summary = ev.get("summary")
        if not summary:
            continue
        key = normalize_title(summary)
        by_title.setdefault(key, []).append(ev)
    return by_title
