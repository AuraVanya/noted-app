"""
Atlassian OAuth 2.0 (3LO) flow. Mirrors the Google auth pattern from
Phase 1 — Authlib drives the authorize/callback handshake, tokens are
Fernet-encrypted at rest in `oauth_credentials`, and the resolved
`cloudId` lands in `oauth_credentials.atlassian_cloud_id`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import encrypt
from ..db import get_session
from ..deps import current_user
from ..models import OAuthCredential, User
from ..services.atlassian import (
    ATLASSIAN_AUTHORIZE_URL,
    ATLASSIAN_TOKEN_URL,
    AtlassianAuthError,
    list_accessible_resources,
)


log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth/atlassian", tags=["auth"])

_settings = get_settings()

oauth = OAuth()
oauth.register(
    name="atlassian",
    client_id=_settings.atlassian_client_id,
    client_secret=_settings.atlassian_client_secret,
    authorize_url=ATLASSIAN_AUTHORIZE_URL,
    access_token_url=ATLASSIAN_TOKEN_URL,
    client_kwargs={"scope": " ".join(_settings.atlassian_scopes)},
)


@router.get("/login")
async def atlassian_login(request: Request):
    if not _settings.atlassian_client_id:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=(
                "Atlassian OAuth is not configured. Set ATLASSIAN_CLIENT_ID + "
                "ATLASSIAN_CLIENT_SECRET in backend/.env."
            ),
        )
    return await oauth.atlassian.authorize_redirect(
        request,
        _settings.atlassian_redirect_uri,
        # Atlassian-specific extras — required for 3LO flows
        audience="api.atlassian.com",
        prompt="consent",
    )


@router.get("/callback")
async def atlassian_callback(
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    """Exchange the auth code, resolve the cloudId, persist the credential."""
    try:
        token = await oauth.atlassian.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Atlassian OAuth error: {exc.error}",
        ) from exc

    access_token = token.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=502, detail="Atlassian token response missing access_token"
        )

    # Resolve the cloudId via accessible-resources. The MVP is single-site, so
    # we pick the first one. If a user is in multiple sites we'd add a picker.
    try:
        resources = await list_accessible_resources(access_token)
    except AtlassianAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not resources:
        raise HTTPException(
            status_code=400,
            detail=(
                "Atlassian returned no accessible resources — your account "
                "doesn't have access to any sites with the requested scopes."
            ),
        )
    cloud_id = resources[0]["id"]
    cloud_url = resources[0].get("url", "")

    # Compute expires_at
    expires_at: datetime | None = None
    if "expires_at" in token:
        expires_at = datetime.fromtimestamp(int(token["expires_at"]), tz=timezone.utc)
    elif "expires_in" in token:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token["expires_in"]))

    granted_scope = token.get("scope", " ".join(_settings.atlassian_scopes))
    enc_access = encrypt(access_token)
    enc_refresh = encrypt(token["refresh_token"]) if token.get("refresh_token") else None

    # Upsert the credential
    existing_q = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user.id,
            OAuthCredential.provider == "atlassian",
        )
    )
    cred = existing_q.scalar_one_or_none()

    if cred is None:
        cred = OAuthCredential(
            user_id=user.id,
            provider="atlassian",
            access_token=enc_access,
            refresh_token=enc_refresh,
            expires_at=expires_at,
            scopes=granted_scope,
            atlassian_cloud_id=cloud_id,
        )
        session.add(cred)
    else:
        cred.access_token = enc_access
        if enc_refresh is not None:
            cred.refresh_token = enc_refresh
        cred.expires_at = expires_at
        cred.scopes = granted_scope
        cred.atlassian_cloud_id = cloud_id

    await session.commit()

    log.info(
        "atlassian connected user_id=%s cloud_id=%s url=%s",
        user.id,
        cloud_id,
        cloud_url,
    )

    return RedirectResponse(url=f"{_settings.frontend_url}/profile", status_code=302)


@router.post("/disconnect")
async def atlassian_disconnect(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Soft disconnect: drop the credential row so the user has to re-consent
    next time. We don't try to revoke Atlassian-side; the user can also revoke
    from their Atlassian account settings if they want."""
    result = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user.id,
            OAuthCredential.provider == "atlassian",
        )
    )
    cred = result.scalar_one_or_none()
    if cred is not None:
        await session.delete(cred)
        await session.commit()
    return Response(status_code=204)
