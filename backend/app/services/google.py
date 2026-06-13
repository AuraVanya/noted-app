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
