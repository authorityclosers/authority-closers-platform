"""Guest sessions and durable acquisition allowance continuity.

Revision ID: 20260914_0036
Revises: 20260913_0035
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0036"
down_revision = "20260913_0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_visitors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.UniqueConstraint("id", "tenant_id"),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint("length(token_hash) = 32", name="token_length"),
        sa.CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    op.create_table(
        "conversation_visitor_claims",
        sa.Column("visitor_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("visitor_id"),
        sa.ForeignKeyConstraint(
            ["visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
    )
    op.create_table(
        "conversation_acquisition_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("visitor_id", sa.Uuid()),
        sa.Column("person_id", sa.Uuid()),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("duration_evidence_sha256", sa.String(64), nullable=False),
        sa.Column("reserved_seconds", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "submission_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(
            ["visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
        sa.CheckConstraint("(visitor_id IS NULL) <> (person_id IS NULL)", name="one_owner"),
        sa.CheckConstraint("reserved_seconds BETWEEN 1 AND 6000", name="duration_bound"),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        sa.CheckConstraint("length(duration_evidence_sha256) = 64", name="duration_evidence"),
    )
    op.create_table(
        "conversation_acquisition_settlements",
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("charged_seconds", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("receipt_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("usage_id"),
        sa.ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        sa.CheckConstraint("charged_seconds BETWEEN 0 AND 6000", name="duration_bound"),
        sa.CheckConstraint("length(receipt_sha256) = 64", name="receipt_hash"),
        sa.CheckConstraint("kind IN ('completed', 'no_work_performed')", name="kind"),
        sa.CheckConstraint(
            "kind <> 'no_work_performed' OR charged_seconds = 0", name="no_work_charge"
        ),
    )
    op.create_index(
        "ix_conversation_visitor_claims_person",
        "conversation_visitor_claims",
        ["tenant_id", "person_id"],
    )
    op.create_index(
        "ix_conversation_acquisition_usage_person",
        "conversation_acquisition_usage",
        ["tenant_id", "person_id"],
    )
    op.create_index(
        "ix_conversation_acquisition_usage_visitor",
        "conversation_acquisition_usage",
        ["tenant_id", "visitor_id"],
    )
    for table in (
        "conversation_visitor_claims",
        "conversation_acquisition_usage",
        "conversation_acquisition_settlements",
    ):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError("Acquisition usage is immutable history; recovery is forward-only.")
