"""Saved reports (Reports V4, Dipak's spec, 13 Nov 2026: "Saved Reports" in the filter).

- New table ``conversation_report_saves``: each Save or Unsave of a call's report by one
  person, append-only; the newest revision per person and call stands. It holds no call
  content and is erased with the recording or the person's account.

Rollback: possible only while the table is empty; once it holds a person's saves, they
require forward recovery (the 0088+ restore-drill policy).

Chain: after 20261113_0151.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261113_0152"
down_revision = "20261113_0151"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_report_saves",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("saved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_report_save_submission",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_report_save_member",
        ),
        sa.UniqueConstraint(
            "tenant_id", "person_id", "submission_id", "revision", name="uq_report_save_revision"
        ),
        sa.CheckConstraint("revision >= 1", name="report_save_revision"),
    )
    op.create_index(
        "ix_report_save_submission", "conversation_report_saves", ["tenant_id", "submission_id"]
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE conversation_report_saves IN ACCESS EXCLUSIVE MODE"))
    saves = sa.table("conversation_report_saves", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saves.c.id.is_not(None)))):
        raise RuntimeError("Saved report history requires forward recovery.")
    op.drop_index("ix_report_save_submission", table_name="conversation_report_saves")
    op.drop_table("conversation_report_saves")
