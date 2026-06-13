"""rename claude_projects -> project_contexts (and friends)

Rename the three Phase 4 tables + their FK columns so the data layer uses
the same vocabulary as the UI ("Project Context"). Data is preserved.

NB: we avoid `op.batch_alter_table` here. Under render_as_batch=True (our
env.py default for SQLite), it triggers a table-rebuild that tries to
resolve foreign keys — and after a table rename, the FK on
`series_context_links.claude_project_id -> claude_projects.id` still
references the old table name in sqlite_master, which makes the rebuild
fail with NoSuchTableError(claude_projects). Plain `ALTER TABLE …
RENAME COLUMN …` skips the rebuild and works on SQLite ≥ 3.25 and
PostgreSQL.

Revision ID: 0004_rename_to_project_contexts
Revises: 0003_claude_projects
Create Date: 2026-06-13

"""
from typing import Sequence, Union

from alembic import op


revision: str = "0004_rename_to_project_contexts"
down_revision: Union[str, None] = "0003_claude_projects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Indexes first — they need to be dropped under their old names before
    # the tables are renamed (SQLite carries the indexes with the table
    # but keeps the original index names, which would collide with the new
    # ones we create below).
    op.execute("DROP INDEX IF EXISTS ix_claude_project_docs_project")
    op.execute("DROP INDEX IF EXISTS ix_series_project_links_claude_project_id")
    op.execute("DROP INDEX IF EXISTS ix_series_project_links_series_id")

    # Rename tables. SQLAlchemy's rename_table emits ALTER TABLE … RENAME TO,
    # which works on both SQLite and Postgres.
    op.rename_table("claude_projects", "project_contexts")
    op.rename_table("series_project_links", "series_context_links")
    op.rename_table("claude_project_docs", "project_context_docs")

    # Rename FK columns. Raw ALTER TABLE … RENAME COLUMN — no batch.
    op.execute(
        "ALTER TABLE series_context_links RENAME COLUMN claude_project_id "
        "TO project_context_id"
    )
    op.execute(
        "ALTER TABLE project_context_docs RENAME COLUMN claude_project_id "
        "TO project_context_id"
    )

    # Recreate indexes under their new names.
    op.create_index(
        "ix_series_context_links_series_id",
        "series_context_links",
        ["series_id"],
        unique=False,
    )
    op.create_index(
        "ix_series_context_links_project_context_id",
        "series_context_links",
        ["project_context_id"],
        unique=False,
    )
    op.create_index(
        "ix_project_context_docs_project",
        "project_context_docs",
        ["project_context_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_project_context_docs_project")
    op.execute("DROP INDEX IF EXISTS ix_series_context_links_project_context_id")
    op.execute("DROP INDEX IF EXISTS ix_series_context_links_series_id")

    op.execute(
        "ALTER TABLE project_context_docs RENAME COLUMN project_context_id "
        "TO claude_project_id"
    )
    op.execute(
        "ALTER TABLE series_context_links RENAME COLUMN project_context_id "
        "TO claude_project_id"
    )

    op.rename_table("project_context_docs", "claude_project_docs")
    op.rename_table("series_context_links", "series_project_links")
    op.rename_table("project_contexts", "claude_projects")

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
    op.create_index(
        "ix_claude_project_docs_project",
        "claude_project_docs",
        ["claude_project_id"],
        unique=False,
    )
