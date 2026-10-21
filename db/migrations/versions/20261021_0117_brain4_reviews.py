"""Brain 4.0 shadow reads of saved reports (orchestrator, 21 Oct 2026), beta only.

- New table ``conversation_brain4_reviews``: append-only attempts of the coaching
  lead's 18-dimension rubric (``brain4-review/1``) on one saved report's transcript: a
  'running' row committed before the provider call, then its outcome on the same row
  ('saved' with the checked answer, or 'failed' with a stable code), with tokens and a
  list-price rupee estimate for the AI spend ledger. Never an official score (AC-SVAL
  gates). Privacy erasure empties the answer with the call's pointer reviews.

A rollback is possible while the table is empty; after that, the history requires
forward recovery.

Chain: after 20261021_0116 (the one-pass trial).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0117"
down_revision = "20261021_0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_brain4_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("report_draft_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("transcript_revision", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("rubric_sha256", sa.String(64), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_brain4_review_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_brain4_review_recording"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["conversation_runs.id"], name="fk_brain4_review_run"),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_brain4_review_report_draft",
        ),
        sa.CheckConstraint("version = 'brain4-review/1'", name="brain4_review_version"),
        sa.CheckConstraint("state IN ('running', 'saved', 'failed')", name="brain4_review_state"),
        sa.CheckConstraint("trigger IN ('auto', 'operator')", name="brain4_review_trigger"),
        sa.CheckConstraint(
            "(state = 'saved' AND erased_at IS NULL) = (payload IS NOT NULL)",
            name="brain4_review_payload",
        ),
        sa.CheckConstraint(
            "(payload IS NULL OR length(payload_sha256) = 64) AND length(source_sha256) = 64"
            " AND length(rubric_sha256) = 64 AND length(prompt_sha256) = 64",
            name="brain4_review_digests",
        ),
        sa.CheckConstraint(
            "(state = 'running') = (finished_at IS NULL)", name="brain4_review_finished"
        ),
    )
    op.create_index(
        "ix_brain4_review_read",
        "conversation_brain4_reviews",
        ["recording_id", "run_id", "created_at"],
    )
    op.create_index(
        "ix_brain4_review_recent", "conversation_brain4_reviews", ["state", "created_at"]
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE conversation_brain4_reviews IN ACCESS EXCLUSIVE MODE"))
    saved = sa.table("conversation_brain4_reviews", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("Brain 4.0 review history requires forward recovery.")
    op.drop_index("ix_brain4_review_recent", table_name="conversation_brain4_reviews")
    op.drop_index("ix_brain4_review_read", table_name="conversation_brain4_reviews")
    op.drop_table("conversation_brain4_reviews")
