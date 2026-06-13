"""Smoke tests for the Meetings endpoints + the extraction text cleaner."""

import pytest

from app.services.extraction import _clean  # noqa: F401 — module-private helper


@pytest.mark.asyncio
async def test_meetings_list_unauthenticated(client):
    r = await client.get("/api/meetings")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_meetings_detail_unauthenticated(client):
    r = await client.get("/api/meetings/1")
    assert r.status_code == 401


class TestClean:
    def test_collapses_runs_of_spaces(self):
        assert _clean("foo    bar") == "foo bar"

    def test_preserves_single_blank_line(self):
        assert _clean("a\n\nb") == "a\n\nb"

    def test_collapses_three_or_more_blank_lines(self):
        assert _clean("a\n\n\n\n\nb") == "a\n\nb"

    def test_strips_trailing_whitespace_per_line(self):
        assert _clean("a   \nb") == "a\nb"

    def test_strips_outer_whitespace(self):
        assert _clean("\n\n  hello world  \n\n") == "hello world"
