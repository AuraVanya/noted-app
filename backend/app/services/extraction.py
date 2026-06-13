"""
Lazy summary-PDF text extraction.

CLAUDE.md domain rule 4: feed *summaries* (not transcripts) to chat. So
this service only extracts summary text. Transcripts stay display-only,
served as PDFs through the signed-URL file proxy.

We cache on `meetings.summary_text` so the second request is free, and
Phase 4's chat path inherits a populated cache.
"""

from __future__ import annotations

import io
import logging
import re

import httpx
from pypdf import PdfReader
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Meeting


log = logging.getLogger(__name__)

DRIVE_DOWNLOAD_URL = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"

_MAX_PDF_BYTES = 8 * 1024 * 1024  # 8MB — Fireflies summaries are ~20KB; be generous
_MULTI_WS = re.compile(r"[ \t]+")
_MULTI_BLANK = re.compile(r"\n{3,}")


class SummaryUnavailable(RuntimeError):
    """Meeting has no summary file id, or Drive can't return the file."""


def _clean(text: str) -> str:
    """Collapse weird whitespace pypdf occasionally emits without
    flattening paragraph breaks."""
    # pypdf splits text on newlines per visual line; turn runs of spaces/tabs
    # into a single space, then collapse 3+ blank lines down to 2.
    lines = [_MULTI_WS.sub(" ", line).rstrip() for line in text.splitlines()]
    joined = "\n".join(lines).strip()
    return _MULTI_BLANK.sub("\n\n", joined)


async def _download_pdf(token: str, file_id: str) -> bytes:
    """Stream the PDF body into memory, capped at _MAX_PDF_BYTES."""
    url = DRIVE_DOWNLOAD_URL.format(file_id=file_id)
    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)

    buf = bytearray()
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code == 404:
                raise SummaryUnavailable(f"summary PDF {file_id} not found in Drive")
            if resp.status_code == 403:
                raise SummaryUnavailable(f"no access to summary PDF {file_id}")
            if resp.status_code != 200:
                raise SummaryUnavailable(
                    f"Drive returned {resp.status_code} for summary {file_id}"
                )
            async for chunk in resp.aiter_bytes(64 * 1024):
                buf.extend(chunk)
                if len(buf) > _MAX_PDF_BYTES:
                    raise SummaryUnavailable(
                        f"summary PDF {file_id} exceeds {_MAX_PDF_BYTES} bytes"
                    )
    return bytes(buf)


def _extract_text(pdf_bytes: bytes) -> str:
    """Synchronous CPU-bound. Caller can run via asyncio.to_thread if it
    becomes a hot path; for now Fireflies summaries are tiny enough that
    inline is fine."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = [(page.extract_text() or "") for page in reader.pages]
    return _clean("\n\n".join(pages))


async def extract_summary_text(
    session: AsyncSession, meeting: Meeting, google_token: str
) -> str:
    """
    Return the meeting's extracted summary text. If `meeting.summary_text`
    is already populated, return that. Otherwise download the summary PDF
    from Drive, extract, persist, and return.

    Raises `SummaryUnavailable` if the meeting has no summary file id or
    the file can't be fetched.
    """
    if meeting.summary_text:
        return meeting.summary_text

    if not meeting.summary_file_id:
        raise SummaryUnavailable(f"meeting {meeting.id} has no summary file id")

    log.info("extracting summary text for meeting_id=%s", meeting.id)
    pdf_bytes = await _download_pdf(google_token, meeting.summary_file_id)
    text = _extract_text(pdf_bytes)

    if not text:
        # Don't cache empty; let a future extraction try again with a fresh
        # pypdf version or a re-uploaded PDF.
        raise SummaryUnavailable(
            f"summary PDF for meeting {meeting.id} produced no text"
        )

    meeting.summary_text = text
    await session.commit()
    return text
