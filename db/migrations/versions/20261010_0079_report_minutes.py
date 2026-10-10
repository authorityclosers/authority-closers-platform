"""Append-only report-delivery customer minutes; provider history is preserved."""

import sqlalchemy as sa
from alembic import op

revision = "20261010_0079"
down_revision = "20261008_0078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_report_minute_events",
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("report_draft_id", sa.Uuid(), nullable=True),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("usage_id", "revision"),
        sa.ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["conversation_processing_plans.id"]),
        sa.ForeignKeyConstraint(["report_draft_id"], ["conversation_report_drafts.id"]),
        sa.UniqueConstraint("usage_id", "key"),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint("kind IN ('reserved','released','delivered')", name="kind"),
        sa.CheckConstraint("seconds BETWEEN 0 AND 6000", name="duration_bound"),
        sa.CheckConstraint("(kind = 'released') = (seconds = 0)", name="release_zero"),
        sa.CheckConstraint("(kind = 'delivered') = (report_draft_id IS NOT NULL)", name="delivery"),
        sa.CheckConstraint("length(receipt_sha256) = 64", name="receipt_hash"),
    )
    op.create_index(
        "uq_conversation_report_minute_events_delivery",
        "conversation_report_minute_events",
        ["usage_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'delivered'"),
    )
    op.execute(
        "CREATE TRIGGER conversation_report_minute_events_append_only "
        "BEFORE UPDATE OR DELETE ON conversation_report_minute_events "
        "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
    )


def downgrade() -> None:
    raise RuntimeError("Customer minute receipts are immutable; recovery is forward-only.")
