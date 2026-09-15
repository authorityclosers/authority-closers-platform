"""Append-only owner-authorized continuation for an expired guest lease.

Revision ID: 20260914_0040
Revises: 20260914_0039
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0040"
down_revision = "20260914_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_processing_continuations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("processing_lease_id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid()),
        sa.Column("owner_visitor_id", sa.Uuid()),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_processing_continuations"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            name=op.f("uq_conversation_processing_continuations_id"),
        ),
        sa.ForeignKeyConstraint(
            ["processing_lease_id", "tenant_id", "person_id"],
            [
                "conversation_processing_leases.id",
                "conversation_processing_leases.tenant_id",
                "conversation_processing_leases.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["owner_visitor_id", "tenant_id"],
            ["conversation_visitors.id", "conversation_visitors.tenant_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
        ),
        sa.ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        sa.ForeignKeyConstraint(["recording_id"], ["conversation_recordings.id"]),
        sa.CheckConstraint(
            "(owner_person_id IS NULL) <> (owner_visitor_id IS NULL)", name="one_owner"
        ),
        sa.CheckConstraint("source_revision >= 1 AND generation >= 1", name="positive_source"),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_hash"),
        sa.CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER conversation_processing_continuations_append_only "
            "BEFORE UPDATE OR DELETE ON conversation_processing_continuations "
            "FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )
    )


def downgrade() -> None:
    raise RuntimeError("Processing continuation history is append-only and forward-only.")
