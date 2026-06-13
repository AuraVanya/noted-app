"""Unit tests for the signed file-URL helpers."""

import time

import pytest

from app.services.file_urls import (
    FileTokenError,
    sign_file_url,
    verify_file_token,
)


class TestSignAndVerify:
    def test_roundtrip(self):
        url, ttl = sign_file_url(user_id=42, drive_file_id="abc123")
        assert url.startswith("/api/files/abc123?token=")
        assert ttl > 0
        token = url.split("token=", 1)[1]
        assert verify_file_token(token, "abc123") == 42

    def test_mismatched_file_id_rejected(self):
        url, _ = sign_file_url(user_id=1, drive_file_id="file-x")
        token = url.split("token=", 1)[1]
        with pytest.raises(FileTokenError, match="match"):
            verify_file_token(token, "file-y")

    def test_tampered_signature_rejected(self):
        url, _ = sign_file_url(user_id=1, drive_file_id="x")
        token = url.split("token=", 1)[1]
        # Tamper with the last few chars; almost certainly invalidates the HMAC
        tampered = token[:-3] + "AAA"
        with pytest.raises(FileTokenError, match="invalid"):
            verify_file_token(tampered, "x")

    def test_empty_token_rejected(self):
        with pytest.raises(FileTokenError):
            verify_file_token("", "x")

    def test_expired_token_rejected(self, monkeypatch):
        """
        Forge a token whose embedded timestamp is far in the past by
        patching itsdangerous's view of the wall clock during dumps. After
        we undo the patch, `loads(max_age=...)` reads the real clock,
        sees the token is older than ttl, and raises SignatureExpired.
        """
        import itsdangerous.timed

        past = int(time.time()) - 60 * 60 * 24  # one day ago
        monkeypatch.setattr(itsdangerous.timed.time, "time", lambda: past)

        url, _ = sign_file_url(user_id=1, drive_file_id="x")
        token = url.split("token=", 1)[1]

        monkeypatch.undo()

        with pytest.raises(FileTokenError, match="expired"):
            verify_file_token(token, "x")
