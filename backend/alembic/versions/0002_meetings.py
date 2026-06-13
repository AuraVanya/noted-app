"""meetings: meeting_series + meetings tables

Revision ID: 0002_meetings
Revises: 0001_initial
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_meetings"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meeting_series",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("normalized_title", sa.String(length=512), nullable=False),
        sa.Column("display_title", sa.String(length=512), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index(
        "ix_meeting_series_normalized_title",
        "meeting_series",
        ["normalized_title"],
        unique=True,
    )

    op.create_table(
        "meetings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("meeting_series.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_file_id", sa.String(length=128), nullable=True),
        sa.Column("transcript_file_id", sa.String(length=128), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("attendees", sa.JSON(), nullable=True),
        sa.Column("calendar_event_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "series_id", "occurred_at", name="uq_meetings_series_occurred_at"
        ),
    )
    op.create_index("ix_meetings_series_id", "meetings", ["series_id"], unique=False)
    op.create_index("ix_meetings_occurred_at", "meetings", ["occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_meetings_occurred_at", table_name="meetings")
    op.drop_index("ix_meetings_series_id", table_name="meetings")
    op.drop_table("meetings")
    op.drop_index("ix_meeting_series_normalized_title", table_name="meeting_series")
    op.drop_table("meeting_series")
