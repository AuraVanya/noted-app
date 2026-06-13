"""claude_projects + series_project_links + claude_project_docs

Revision ID: 0003_claude_projects
Revises: 0002_meetings
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_claude_projects"
down_revision: Union[str, None] = "0002_meetings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "claude_projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("drive_folder_id", sa.String(length=128), nullable=False),
        sa.Column("drive_folder_url", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint("label", name="uq_claude_projects_label"),
        sa.UniqueConstraint("drive_folder_id", name="uq_claude_projects_drive_folder_id"),
    )

    op.create_table(
        "series_project_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "series_id",
            sa.Integer(),
            sa.ForeignKey("meeting_series.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claude_project_id",
            sa.Integer(),
            sa.ForeignKey("claude_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "series_id",
            "claude_project_id",
            name="uq_series_project_links_series_project",
        ),
    )
    op.create_index(
        "ix_series_project_links_series_id",
        "series_project_links",
        ["series_id"],
        unique=False,
    )
    op.create_index(
        "ix_series_project_links_claude_project_id",
        "series_project_links",
        ["claude_project_id"],
        unique=False,
    )

    op.create_table(
        "claude_project_docs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "claude_project_id",
            sa.Integer(),
            sa.ForeignKey("claude_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("item_ref", sa.String(length=128), nullable=False),
        sa.Column("drive_doc_id", sa.String(length=128), nullable=True),
        sa.Column("drive_doc_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "claude_project_id",
            "item_type",
            "item_ref",
            name="uq_claude_project_docs_project_item",
        ),
    )
    op.create_index(
        "ix_claude_project_docs_project",
        "claude_project_docs",
        ["claude_project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_claude_project_docs_project", table_name="claude_project_docs")
    op.drop_table("claude_project_docs")
    op.drop_index(
        "ix_series_project_links_claude_project_id", table_name="series_project_links"
    )
    op.drop_index(
        "ix_series_project_links_series_id", table_name="series_project_links"
    )
    op.drop_table("series_project_links")
    op.drop_table("claude_projects")
