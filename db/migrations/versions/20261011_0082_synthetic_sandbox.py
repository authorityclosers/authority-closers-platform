"""Explicit sandbox opt-in and preserved synthetic revisions, separate from real runs."""

import sqlalchemy as sa
from alembic import op

revision = "20261011_0082"
down_revision = "20261011_0081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_sandbox_organisations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("approval_reference", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["organisations.tenant_id"]),
        sa.ForeignKeyConstraint(["approved_by_person_id"], ["persons.id"]),
    )
    op.create_table(
        "conversation_synthetic_records",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("synthetic_key", sa.String(160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.String(160), nullable=False),
        sa.Column("imported_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "kind", "synthetic_key", "revision"),
        sa.ForeignKeyConstraint(["tenant_id"], ["conversation_sandbox_organisations.tenant_id"]),
        sa.ForeignKeyConstraint(["imported_by_person_id"], ["persons.id"]),
        sa.CheckConstraint("revision >= 1", name="positive_revision"),
        sa.CheckConstraint("length(payload_sha256) = 64", name="payload_hash"),
        sa.CheckConstraint("synthetic_key LIKE 'syn-%'", name="synthetic_identity"),
        sa.CheckConstraint("business_id LIKE 'syn-%'", name="synthetic_business"),
    )
    op.create_index(
        "ix_conversation_synthetic_records_date",
        "conversation_synthetic_records",
        ["tenant_id", "kind", "occurred_at", "synthetic_key"],
    )
    for table in ("conversation_sandbox_organisations", "conversation_synthetic_records"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )


def downgrade() -> None:
    raise RuntimeError("Synthetic provenance is retained; recovery is forward-only.")
