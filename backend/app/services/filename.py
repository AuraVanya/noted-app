"""
Parse Fireflies-produced PDF filenames from Google Drive.

Filename convention (spec §3, stable, confirmed):

    [Title]-summary-[ISO8601 UTC timestamp].pdf
    [Title]-transcript-[ISO8601 UTC timestamp].pdf

The timestamp's date keeps its hyphens; the time's colons are written as
hyphens, e.g. "2026-06-12T06-15-00.000Z" -> 06:15:00 UTC.

The title is the verbatim calendar event title and may itself contain hyphens
(e.g. "Q2 Planning - Phase 1"). The regex is anchored on both ends so the
rigid `(summary|transcript)-<timestamp>.pdf` tail forces the greedy title
match to stop at the right place. This is the "parse from the right"
guarantee — no left-to-right `.split("-")` will work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


Kind = Literal["summary", "transcript"]


# Stem regex (matches the part before `.pdf`).
_STEM_RE = re.compile(
    r"^(?P<title>.+)-(?P<kind>summary|transcript)"
    r"-(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z)$"
)

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedFilename:
    """Structured view of a Drive filename."""

    original_name: str
    display_title: str       # exact title from filename, preserved for UI
    normalized_title: str    # trim + collapse-ws + lower, for matching only
    kind: Kind
    occurred_at: datetime    # tz-aware, UTC


def normalize_title(title: str) -> str:
    """Trim, collapse internal whitespace, lowercase. Matching key only."""
    return _WHITESPACE_RE.sub(" ", title.strip()).lower()


def _parse_timestamp(raw: str) -> datetime:
    """
    Reconstruct the UTC datetime from a filename-encoded ISO string.

    Input  : "2026-06-12T06-15-00.000Z"
    Output : datetime(2026, 6, 12, 6, 15, 0, microsecond=0, tzinfo=UTC)

    The date's dashes stay; only the two dashes between `T` and `.` become
    colons. We do this by surgical replace on the time portion rather than
    on the whole string, so a title-side dash can never be touched here.
    """
    date_part, _, time_part = raw.partition("T")
    # time_part is like "06-15-00.000Z"
    time_fixed = time_part.replace("-", ":", 2)
    iso = f"{date_part}T{time_fixed}".replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    # fromisoformat with +00:00 yields a tz-aware datetime; ensure UTC.
    return dt.astimezone(timezone.utc)


def parse_filename(name: str) -> ParsedFilename | None:
    """
    Parse a Drive filename. Returns None for non-conforming names so the
    caller can log + skip without exception handling.
    """
    if not name.endswith(".pdf"):
        return None
    stem = name[:-4]  # strip ".pdf"

    match = _STEM_RE.match(stem)
    if match is None:
        return None

    title = match.group("title")
    kind = match.group("kind")
    ts_raw = match.group("ts")

    try:
        occurred_at = _parse_timestamp(ts_raw)
    except ValueError:
        # Regex matched the shape but the date/time values are out of range
        # (e.g. month 13). Treat as non-conforming.
        return None

    return ParsedFilename(
        original_name=name,
        display_title=title,
        normalized_title=normalize_title(title),
        kind=kind,  # type: ignore[arg-type]
        occurred_at=occurred_at,
    )
