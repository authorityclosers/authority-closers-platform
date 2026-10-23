"""Feedback and voice notes (owner, 23 Oct 2026: a reviews engine, and voice notes on bugs).

- New table ``feedback_responses``: append-only answers to small prompts after key moments
  (a rating from 1 to 3 with an optional comment, "not now", "don't ask again"), with the
  screen, release and scrubbed device context. A retried send (same person and command id)
  finds the first answer.
- New table ``bug_report_attachments``: a voice note sent with a bug report, written with it
  and never changed; the file sits in the Sales X-Ray store beside the report's picture.

Rollback: forward-only (the restore-drill policy); answers and attachments are history.

Chain: after 20261023_0126.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0127"
down_revision = "20261023_0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_responses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("moment", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.String(1000), nullable=True),
        sa.Column("route", sa.String(512), nullable=False),
        sa.Column("release", sa.String(40), nullable=True),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "command_id", name="uq_feedback_command"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_feedback_tenant"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_feedback_person"),
        sa.CheckConstraint("kind IN ('rating', 'dismissed', 'opt_out')", name="feedback_kind"),
        sa.CheckConstraint(
            "(kind = 'rating') = (rating IS NOT NULL)"
            " AND (rating IS NULL OR rating BETWEEN 1 AND 3)"
            " AND (kind = 'rating' OR comment IS NULL)",
            name="feedback_rating",
        ),
        sa.CheckConstraint("length(moment) BETWEEN 2 AND 32", name="feedback_moment"),
    )
    op.create_index("ix_feedback_moment", "feedback_responses", ["moment", "created_at"])
    op.create_index("ix_feedback_person", "feedback_responses", ["person_id", "created_at"])
    op.create_index("ix_feedback_tenant", "feedback_responses", ["tenant_id", "created_at"])
    op.create_table(
        "bug_report_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bug_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bug_id"], ["bug_reports.id"], name="fk_bug_attachment_report"),
        sa.UniqueConstraint("bug_id", "kind", name="uq_bug_attachment_kind"),
        sa.CheckConstraint("kind IN ('voice')", name="bug_attachment_kind"),
        sa.CheckConstraint(
            "content_type IN ('audio/webm', 'audio/ogg', 'audio/mp4')",
            name="bug_attachment_type",
        ),
        sa.CheckConstraint(
            "bytes > 0 AND length(sha256) = 64 AND seconds BETWEEN 1 AND 120",
            name="bug_attachment_size",
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Feedback and bug attachments are forward-only: a later migration changes them."
    )
