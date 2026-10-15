"""AI pointer reviews for the 15 Oct Report (owner decision, 16 Oct 2026).

The owner approved AI scores for the Report's 27 pointers (rulebook 693645b0):
an AI draft, not reviewed by Dipak. One row is one saved review of one report
draft: per-pointer status, score and feedback, with evidence by transcript
segment. Append-only; a newer review supersedes by being newer.

Chain: after 20261013_0090 (recording duration).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261016_0091"
down_revision = "20261013_0090"
branch_labels = None
depends_on = None

TABLE = "conversation_pointer_reviews"


def upgrade() -> None:
    op.create_table(
        TABLE,
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
    op.create_index("ix_pointer_review_read", TABLE, ["recording_id", "run_id", "created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION protect_pointer_review_history() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Pointer reviews preserve history';
            END;
            $$
        """)
        op.execute(f"""
            CREATE TRIGGER pointer_review_history
            BEFORE UPDATE OR DELETE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION protect_pointer_review_history()
        """)


def downgrade() -> None:
    raise RuntimeError("Pointer reviews are forward-only: saved AI reviews stay as history.")
