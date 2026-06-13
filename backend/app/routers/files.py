"""
File proxy. Two endpoints:

- `GET /api/files/{drive_file_id}/signed-url` — session-authenticated. Mints
  a short-lived signed URL the frontend can hand to a `<a target=_blank>`
  or stash in an `<iframe src>`.
- `GET /api/files/{drive_file_id}?token=...` — *not* session-authenticated.
  Validates the signed token, looks up the user's Google credentials, and
  streams the PDF bytes from Drive with `Content-Disposition: inline` so
  the browser shows it instead of downloading.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user
from ..models import User
from ..services.file_urls import (
    FileTokenError,
    sign_file_url,
    verify_file_token,
)
from ..services.google import (
    GoogleAuthError,
    get_valid_google_token,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

DRIVE_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

_CHUNK_BYTES = 64 * 1024  # 64KB


@router.get("/{drive_file_id}/signed-url")
async def mint_signed_url(
    drive_file_id: str = Path(..., min_length=1, max_length=128),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Issue a short-lived signed URL the user can open in a new tab."""
    # Confirm the user has a Google credential on file — otherwise the
    # eventual GET will fail at fetch time, and we should surface that now.
    try:
        await get_valid_google_token(session, user.id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    url, ttl = sign_file_url(user.id, drive_file_id)
    return {"url": url, "ttl_seconds": ttl}


@router.get("/{drive_file_id}")
async def stream_drive_file(
    drive_file_id: str = Path(..., min_length=1, max_length=128),
    token: str = Query(..., min_length=1),
    session: AsyncSession = Depends(get_session),
):
    """Verify the signed token, stream the PDF bytes from Drive."""
    try:
        user_id = verify_file_token(token, drive_file_id)
    except FileTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    try:
        google_token = await get_valid_google_token(session, user_id)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    drive_url = DRIVE_DOWNLOAD_URL.format(file_id=drive_file_id)
    headers = {"Authorization": f"Bearer {google_token}"}

    # Open the upstream stream *before* returning the response so we can
    # propagate Drive's status code (404, 403) accurately instead of
    # always 200-ing and then choking mid-body.
    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0))
    try:
        req = client.build_request("GET", drive_url, headers=headers)
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        log.warning("drive proxy network error file=%s: %s", drive_file_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Drive request failed",
        ) from exc

    if upstream.status_code == 404:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=404, detail="file not found")
    if upstream.status_code == 403:
        await upstream.aclose()
        await client.aclose()
        raise HTTPException(status_code=403, detail="forbidden")
    if upstream.status_code != 200:
        body_snip = ""
        try:
            body_snip = (await upstream.aread()).decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        await upstream.aclose()
        await client.aclose()
        log.warning(
            "drive proxy upstream %s file=%s body=%r",
            upstream.status_code,
            drive_file_id,
            body_snip,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Drive returned an unexpected status",
        )

    async def body_iter():
        try:
            async for chunk in upstream.aiter_bytes(_CHUNK_BYTES):
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response_headers = {
        "Content-Disposition": "inline",
        "Cache-Control": "private, max-age=60",
    }
    if "content-length" in upstream.headers:
        response_headers["Content-Length"] = upstream.headers["content-length"]

    return StreamingResponse(
        body_iter(),
        media_type="application/pdf",
        headers=response_headers,
    )
