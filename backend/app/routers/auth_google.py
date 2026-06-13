from datetime import datetime, timedelta, timezone

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..crypto import encrypt
from ..db import get_session
from ..models import OAuthCredential, User


router = APIRouter(prefix="/api/auth", tags=["auth"])

_settings = get_settings()

oauth = OAuth()
oauth.register(
    name="google",
    client_id=_settings.google_client_id,
    client_secret=_settings.google_client_secret,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": " ".join(_settings.google_scopes)},
)


def _initials_from(name: str, email: str) -> str:
    parts = [p for p in (name or "").strip().split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if len(parts) == 1 and parts[0]:
        return parts[0][:2].upper()
    return (email[:2] or "??").upper()


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = _settings.google_redirect_uri
    # access_type=offline + prompt=consent guarantees a refresh token on first auth
    return await oauth.google.authorize_redirect(
        request,
        redirect_uri,
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )


@router.get("/google/callback")
async def google_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth error: {exc.error}",
        ) from exc

    userinfo = token.get("userinfo")
    if userinfo is None:
        # Some flows require an explicit userinfo fetch
        resp = await oauth.google.get("https://openidconnect.googleapis.com/v1/userinfo", token=token)
        userinfo = resp.json()

    google_sub = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name") or email or "User"
    if not google_sub or not email:
        raise HTTPException(status_code=400, detail="Google userinfo missing sub/email")

    # Upsert user (look up by google_sub first, fall back to email match)
    result = await session.execute(select(User).where(User.google_sub == google_sub))
    user = result.scalar_one_or_none()
    if user is None:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is not None:
            user.google_sub = google_sub

    if user is None:
        user = User(
            google_sub=google_sub,
            email=email,
            display_name=name,
            avatar_initials=_initials_from(name, email),
        )
        session.add(user)
    else:
        user.email = email
        user.display_name = name
        user.avatar_initials = _initials_from(name, email)

    await session.flush()  # assign user.id

    # Compute expires_at
    expires_at: datetime | None = None
    if "expires_at" in token:
        expires_at = datetime.fromtimestamp(int(token["expires_at"]), tz=timezone.utc)
    elif "expires_in" in token:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token["expires_in"]))

    granted_scope = token.get("scope", " ".join(_settings.google_scopes))

    # Upsert credential row
    cred_q = await session.execute(
        select(OAuthCredential).where(
            OAuthCredential.user_id == user.id,
            OAuthCredential.provider == "google",
        )
    )
    cred = cred_q.scalar_one_or_none()
    enc_access = encrypt(token["access_token"])
    enc_refresh = encrypt(token["refresh_token"]) if token.get("refresh_token") else None

    if cred is None:
        cred = OAuthCredential(
            user_id=user.id,
            provider="google",
            access_token=enc_access,
            refresh_token=enc_refresh,
            expires_at=expires_at,
            scopes=granted_scope,
        )
        session.add(cred)
    else:
        cred.access_token = enc_access
        # Keep an existing refresh token if Google didn't return a new one
        if enc_refresh is not None:
            cred.refresh_token = enc_refresh
        cred.expires_at = expires_at
        cred.scopes = granted_scope

    await session.commit()

    request.session["user_id"] = user.id

    return RedirectResponse(url=_settings.frontend_url, status_code=302)


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    request.session.clear()
    return Response(status_code=204)
