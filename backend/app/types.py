"""
Shared SQLAlchemy column types.

`UTCDateTime` is the type we use for every datetime column in the app. We
*always* store UTC, *always* hand UTC out, and never let a naive datetime
enter the database.

SQLite is the immediate motivator: it stores `DateTime(timezone=True)` as a
naive string and returns it without tzinfo, which breaks any tz-aware
arithmetic (e.g. `cred.expires_at - datetime.now(timezone.utc)`). The
TypeDecorator pattern fixes this without a schema change — Postgres will
also be a UTC tz-aware column, which is what we want.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.types import DateTime, TypeDecorator


class UTCDateTime(TypeDecorator):
    """Tz-aware datetime, always normalized to UTC on both write and read."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"UTCDateTime expects datetime, got {type(value)}")
        if value.tzinfo is None:
            # Catch developer error early. Spec is "store UTC"; if you're
            # binding a naive datetime, you've already lost the offset.
            raise ValueError("UTCDateTime requires a tz-aware datetime")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
