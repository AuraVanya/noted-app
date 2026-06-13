"""
Tests for the Drive filename parser. Every case in the Phase 2 acceptance
criteria has a dedicated test.
"""

from datetime import datetime, timezone

import pytest

from app.services.filename import (
    ParsedFilename,
    normalize_title,
    parse_filename,
)


def _utc(year: int, month: int, day: int, hour: int, minute: int, second: int) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


class TestParseFilename:
    def test_plain_title_transcript(self):
        result = parse_filename("TSD Daily Sync-transcript-2026-06-12T06-15-00.000Z.pdf")
        assert result is not None
        assert result.display_title == "TSD Daily Sync"
        assert result.normalized_title == "tsd daily sync"
        assert result.kind == "transcript"
        assert result.occurred_at == _utc(2026, 6, 12, 6, 15, 0)

    def test_plain_title_summary(self):
        result = parse_filename("Standup-summary-2026-01-02T09-00-00.000Z.pdf")
        assert result is not None
        assert result.display_title == "Standup"
        assert result.kind == "summary"
        assert result.occurred_at == _utc(2026, 1, 2, 9, 0, 0)

    def test_title_with_internal_hyphens(self):
        """The regex must not split mid-title."""
        result = parse_filename(
            "Q2 Planning - Phase 1-summary-2026-06-12T14-30-00.000Z.pdf"
        )
        assert result is not None
        assert result.display_title == "Q2 Planning - Phase 1"
        assert result.normalized_title == "q2 planning - phase 1"
        assert result.kind == "summary"
        assert result.occurred_at == _utc(2026, 6, 12, 14, 30, 0)

    def test_title_with_many_hyphens(self):
        result = parse_filename(
            "Eng - Backend - Weekly-transcript-2026-06-12T15-00-00.000Z.pdf"
        )
        assert result is not None
        assert result.display_title == "Eng - Backend - Weekly"

    def test_title_ending_in_a_hyphen(self):
        """Pathological: title ends with `-`, so stem looks like `Foo --summary-...`."""
        result = parse_filename("Foo --summary-2026-06-12T06-15-00.000Z.pdf")
        assert result is not None
        assert result.display_title == "Foo -"

    def test_summary_and_transcript_pair_for_same_occurrence(self):
        """Both files for one meeting must produce the same (title, timestamp) pair."""
        summary = parse_filename("Design Review-summary-2026-06-12T18-00-00.000Z.pdf")
        transcript = parse_filename(
            "Design Review-transcript-2026-06-12T18-00-00.000Z.pdf"
        )
        assert summary is not None and transcript is not None
        assert summary.normalized_title == transcript.normalized_title
        assert summary.occurred_at == transcript.occurred_at
        assert {summary.kind, transcript.kind} == {"summary", "transcript"}

    def test_same_day_recurring_two_occurrences(self):
        """Two occurrences of the same recurring meeting on the same day."""
        morning = parse_filename(
            "Standup-summary-2026-06-12T09-00-00.000Z.pdf"
        )
        afternoon = parse_filename(
            "Standup-summary-2026-06-12T15-30-00.000Z.pdf"
        )
        assert morning is not None and afternoon is not None
        assert morning.normalized_title == afternoon.normalized_title
        assert morning.occurred_at != afternoon.occurred_at
        # Both UTC, six and a half hours apart
        assert (afternoon.occurred_at - morning.occurred_at).total_seconds() == 6.5 * 3600

    def test_utc_timezone_attached(self):
        result = parse_filename(
            "Anything-transcript-2026-06-12T06-15-00.000Z.pdf"
        )
        assert result is not None
        assert result.occurred_at.tzinfo is not None
        assert result.occurred_at.utcoffset().total_seconds() == 0

    def test_time_with_seconds_minutes_hours_distinct_components(self):
        """Confirm date dashes stay as dashes and only time dashes become colons."""
        result = parse_filename(
            "X-summary-2026-12-31T23-59-58.000Z.pdf"
        )
        assert result is not None
        assert result.occurred_at == _utc(2026, 12, 31, 23, 59, 58)

    def test_whitespace_normalization(self):
        a = parse_filename("  TSD daily sync  -summary-2026-06-12T06-15-00.000Z.pdf")
        b = parse_filename("TSD Daily Sync-summary-2026-06-12T06-15-00.000Z.pdf")
        assert a is not None and b is not None
        # Internal title diffs are preserved in display_title
        assert a.display_title == "  TSD daily sync  "
        assert b.display_title == "TSD Daily Sync"
        # ...but the normalized form is the same
        assert a.normalized_title == b.normalized_title == "tsd daily sync"

    def test_multiple_internal_whitespace_collapsed(self):
        assert normalize_title("Foo   Bar\t Baz") == "foo bar baz"


class TestNonConforming:
    @pytest.mark.parametrize(
        "name",
        [
            "",
            "not a meeting.pdf",
            # Wrong kind token:
            "Standup-recording-2026-06-12T06-15-00.000Z.pdf",
            # Missing kind token entirely:
            "Standup-2026-06-12T06-15-00.000Z.pdf",
            # Missing milliseconds:
            "Standup-summary-2026-06-12T06-15-00Z.pdf",
            # Missing the Z (timezone):
            "Standup-summary-2026-06-12T06-15-00.000.pdf",
            # Bad date shape (only 2-digit year):
            "Standup-summary-26-06-12T06-15-00.000Z.pdf",
            # Non-pdf extension:
            "Standup-summary-2026-06-12T06-15-00.000Z.docx",
            # No extension:
            "Standup-summary-2026-06-12T06-15-00.000Z",
            # Looks right but month 13 is invalid:
            "Standup-summary-2026-13-12T06-15-00.000Z.pdf",
            # Looks right but hour 25:
            "Standup-summary-2026-06-12T25-00-00.000Z.pdf",
        ],
    )
    def test_returns_none_no_crash(self, name):
        assert parse_filename(name) is None


class TestParsedFilenameShape:
    def test_dataclass_immutability(self):
        p = parse_filename("Standup-summary-2026-06-12T09-00-00.000Z.pdf")
        assert isinstance(p, ParsedFilename)
        with pytest.raises(Exception):
            p.display_title = "tampered"  # type: ignore[misc]
