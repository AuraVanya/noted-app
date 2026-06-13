from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .types import UTCDateTime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    avatar_initials: Mapped[str] = mapped_column(String(4), default="")
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    credentials: Mapped[list["OAuthCredential"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_oauth_credentials_user_provider"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # 'google' | 'atlassian'

    access_token: Mapped[str] = mapped_column(Text)  # Fernet-encrypted
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="")  # space-separated
    atlassian_cloud_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="credentials")


class MeetingSeries(Base):
    """A recurring (or one-off) meeting name. One row per `normalized_title`."""

    __tablename__ = "meeting_series"

    id: Mapped[int] = mapped_column(primary_key=True)
    normalized_title: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    display_title: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    meetings: Mapped[list["Meeting"]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
    )


class Meeting(Base):
    """
    A single occurrence of a series. Identity = (series_id, occurred_at).
    The same `occurred_at` will not exist twice in a series; the unique
    constraint enforces this and makes the sync job naturally idempotent.
    """

    __tablename__ = "meetings"
    __table_args__ = (
        UniqueConstraint("series_id", "occurred_at", name="uq_meetings_series_occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("meeting_series.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))  # display title at upsert time
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)

    summary_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    transcript_file_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Filled in lazily in Phase 3 when chat / Confluence needs the text.
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Calendar match — filled by the sync job, best-effort
    attendees: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=_utcnow)

    series: Mapped[MeetingSeries] = relationship(back_populates="meetings")
