"""AI pointer reviews for the 15 Oct Report (owner decision, 16 Oct 2026).

The owner approved AI scores for the Report's 27 pointers (rulebook 693645b0):
an AI draft, not reviewed by Dipak. One row is one saved review of one report
draft: per-pointer status, score and feedback, with evidence by transcript
segment. Rows are only ever added (the app has no update or delete path); a
newer review supersedes an older one by being newer.

A new, empty table may be rolled back; once any review exists, its history
requires forward recovery.

Chain: after 20261013_0090 (recording duration).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0091"
down_revision = "20261013_0090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_pointer_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("report_draft_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("transcript_revision", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_pointer_review_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_pointer_review_recording"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["conversation_runs.id"], name="fk_pointer_review_run"),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_pointer_review_report_draft",
        ),
        sa.CheckConstraint("version = 'pointer-review/1'", name="pointer_review_version"),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(payload_sha256) = 64"
            " AND length(prompt_sha256) = 64",
            name="pointer_review_digests",
        ),
    )
    op.create_index(
        "ix_pointer_review_read",
        "conversation_pointer_reviews",
        ["recording_id", "run_id", "created_at"],
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE conversation_pointer_reviews IN ACCESS EXCLUSIVE MODE"))
    history = sa.table("conversation_pointer_reviews", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(history.c.id.is_not(None)))):
        raise RuntimeError("Pointer review history requires forward recovery.")
    op.drop_index("ix_pointer_review_read", table_name="conversation_pointer_reviews")
    op.drop_table("conversation_pointer_reviews")
