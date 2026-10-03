"""Store first-report numeric measurements with recording-owned retention."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261003_0071"
down_revision = "20261003_0070"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_call_metrics",
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("report_draft_id", sa.Uuid(), nullable=False),
        sa.Column("rules", sa.Text(), nullable=False),
        sa.Column(
            "summary",
            sa.JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
            nullable=True,
        ),
        sa.Column("summary_sha256", sa.String(64), nullable=False),
        sa.Column("outcome_kind", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["usage_id"],
            ["conversation_acquisition_settlements.usage_id"],
            name=op.f("fk_conversation_call_metrics_usage_id_conversation_acquisition_settlements"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_conversation_call_metrics_tenant_id_tenants"),
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["conversation_recordings.id"],
            name=op.f("fk_conversation_call_metrics_recording_id_conversation_recordings"),
        ),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name=op.f("fk_conversation_call_metrics_report_draft_id_conversation_report_drafts"),
        ),
        sa.PrimaryKeyConstraint("usage_id", name=op.f("pk_conversation_call_metrics")),
    )
    op.create_index(
        "ix_conversation_call_metrics_tenant_created",
        "conversation_call_metrics",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Call measurements are forward-only; content is cleared by erasure.")
