"""The advanced bug reporter (owner, 31 Oct 2026: annotations, element comments, telemetry,
steps and files, for the team and the testers the owner lets in).

- New table ``bug_report_files``: the files that follow a report, each written once: the
  picture before its marks, each commented part's small picture (with the comment's number)
  and the person's own files (pictures, short screen recordings, logs). The files sit in the
  Sales X-Ray store beside the report's picture.
- New table ``bug_reporter_access``: the append-only history of who may use the advanced
  reporter (asked, let in, turned down, taken away); the newest entry per person stands.

The steps, element comments, slow calls and speed travel in the report's context, written
with it (no column).

Rollback: possible only while both tables are empty; once they hold files or access history,
the history requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261030_0147.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261031_0149"
down_revision = "20261030_0147"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bug_report_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bug_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("part", sa.SmallInteger(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_file_report"),
        sa.UniqueConstraint("bug_id", "position", name="uq_bug_file_position"),
        sa.CheckConstraint("position BETWEEN 1 AND 30", name="bug_file_position"),
        sa.CheckConstraint("role IN ('original', 'element', 'attachment')", name="bug_file_role"),
        sa.CheckConstraint(
            "(role = 'element') = (part IS NOT NULL) AND (part IS NULL OR part BETWEEN 1 AND 50)",
            name="bug_file_part",
        ),
        sa.CheckConstraint(
            "content_type IN ('image/webp', 'video/webm', 'video/mp4', 'text/plain', 'text/csv',"
            " 'application/json', 'application/pdf')",
            name="bug_file_type",
        ),
        sa.CheckConstraint(
            "bytes > 0 AND length(sha256) = 64 AND length(trim(name)) > 0", name="bug_file_size"
        ),
    )
    op.create_table(
        "bug_reporter_access",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_bug_access_person"),
        sa.ForeignKeyConstraint(["actor_person_id"], ["persons.id"], name="fk_bug_access_actor"),
        sa.CheckConstraint(
            "kind IN ('requested', 'granted', 'denied', 'revoked')", name="bug_access_kind"
        ),
        sa.CheckConstraint(
            "(kind = 'requested') = (actor_person_id = person_id)", name="bug_access_actor"
        ),
    )
    op.create_index("ix_bug_access_person", "bug_reporter_access", ["person_id", "created_at"])


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE bug_report_files, bug_reporter_access IN ACCESS EXCLUSIVE MODE"))
    files = sa.table("bug_report_files", sa.column("id"))
    access = sa.table("bug_reporter_access", sa.column("id"))
    used = sa.or_(
        sa.exists().where(files.c.id.is_not(None)),
        sa.exists().where(access.c.id.is_not(None)),
    )
    if op.get_bind().scalar(sa.select(used)):
        raise RuntimeError("Advanced bug report history requires forward recovery.")
    op.drop_index("ix_bug_access_person", table_name="bug_reporter_access")
    op.drop_table("bug_reporter_access")
    op.drop_table("bug_report_files")
