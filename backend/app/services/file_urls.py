"""
Signed file-proxy URLs.

`GET /api/files/<id>?token=...` is opened in a new tab, which won't carry
an Authorization header or even a session cookie reliably. The auth on
this endpoint is the signed token in the query string instead — it carries
both the user id and the file id, so the link is single-use-ish (expires)
and tamper-evident.

Signing key (`FILE_URL_SECRET`) is separate from the session secret so the
two can be rotated independently.
"""

from __future__ import annotations

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import get_settings


_SALT = "noted-file-url-v1"


class FileTokenError(ValueError):
    """Token is missing, malformed, expired, or for the wrong file."""


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().file_url_secret, salt=_SALT)


def sign_file_url(user_id: int, drive_file_id: str) -> tuple[str, int]:
    """Return `(url_path, ttl_seconds)`. URL is relative; pair with the host
    on the way out if you need an absolute URL."""
    settings = get_settings()
    token = _serializer().dumps({"u": user_id, "f": drive_file_id})
    return f"/api/files/{drive_file_id}?token={token}", settings.file_url_ttl_seconds


def verify_file_token(token: str, expected_file_id: str) -> int:
    """
    Validate token, confirm its file id matches `expected_file_id`, return
    the user id baked into the token. Raises `FileTokenError` on any
    failure (expired, bad signature, mismatched file id, malformed payload).
    """
    settings = get_settings()
    try:
        payload = _serializer().loads(token, max_age=settings.file_url_ttl_seconds)
    except SignatureExpired as exc:
        raise FileTokenError("token expired") from exc
    except BadSignature as exc:
        raise FileTokenError("invalid token") from exc

    if not isinstance(payload, dict):
        raise FileTokenError("malformed token payload")

    user_id = payload.get("u")
    file_id = payload.get("f")

    if not isinstance(user_id, int) or not isinstance(file_id, str):
        raise FileTokenError("malformed token payload")

    if file_id != expected_file_id:
        # Defence in depth — a token minted for file X must not unlock file Y.
        raise FileTokenError("token does not match requested file")

    return user_id
