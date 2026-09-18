"""Separate non-login processing leases from browser identity and quota ownership.

Revision ID: 20260914_0037
Revises: 20260914_0036
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_0037"
down_revision = "20260914_0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_memberships_role_supported"), "memberships", type_="check")
    op.create_check_constraint(
        "role_supported",
        "memberships",
        "role IN ('learner', 'support', 'admin', 'owner', 'processing')",
    )
    op.create_table(
        "conversation_processing_principals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("operator_reference", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
        sa.UniqueConstraint("person_id"),
        sa.UniqueConstraint("id", "tenant_id", "person_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"], ["memberships.tenant_id", "memberships.person_id"]
        ),
    )
    op.create_table(
        "conversation_processing_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("usage_id"),
        sa.UniqueConstraint("id", "tenant_id", "person_id"),
        sa.ForeignKeyConstraint(
            ["principal_id", "tenant_id", "person_id"],
            [
                "conversation_processing_principals.id",
                "conversation_processing_principals.tenant_id",
                "conversation_processing_principals.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        sa.CheckConstraint("expires_at > created_at", name="bounded_expiry"),
    )
    op.create_table(
        "conversation_guest_submissions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("processing_lease_id", sa.Uuid(), nullable=False),
        sa.Column("usage_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "submission_id"),
        sa.UniqueConstraint("recording_id"),
        sa.UniqueConstraint("processing_lease_id"),
        sa.UniqueConstraint("usage_id"),
        sa.ForeignKeyConstraint(
            ["recording_id", "tenant_id", "person_id"],
            [
                "conversation_recordings.id",
                "conversation_recordings.tenant_id",
                "conversation_recordings.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["processing_lease_id", "tenant_id", "person_id"],
            [
                "conversation_processing_leases.id",
                "conversation_processing_leases.tenant_id",
                "conversation_processing_leases.person_id",
            ],
        ),
        sa.ForeignKeyConstraint(["usage_id"], ["conversation_acquisition_usage.id"]),
        sa.CheckConstraint("length(source_sha256) = 64", name="source_hash"),
    )
    for table in (
        "conversation_quote_acceptances",
        "conversation_inference_tasks",
        "conversation_processing_plans",
    ):
        op.alter_column(table, "session_id", nullable=True, existing_type=sa.Uuid())
        op.add_column(table, sa.Column("processing_lease_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            None,
            table,
            "conversation_processing_leases",
            ["processing_lease_id"],
            ["id"],
        )
        op.create_check_constraint(
            "one_actor", table, "(session_id IS NULL) <> (processing_lease_id IS NULL)"
        )
    op.execute(
        sa.text(
            "CREATE TRIGGER conversation_guest_submissions_append_only BEFORE UPDATE OR DELETE "
            "ON conversation_guest_submissions FOR EACH ROW "
            "EXECUTE FUNCTION prevent_conversation_command_mutation();"
        )
    )
    op.execute(
        sa.text("""
        CREATE FUNCTION prevent_processing_scope_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'processing authority history is immutable';
            END IF;
            IF (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at')
                OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at)
            THEN
                RAISE EXCEPTION 'processing authority can only be revoked once';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    )
    for table in ("conversation_processing_principals", "conversation_processing_leases"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_processing_scope_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "Guest ownership and processing history are immutable; recovery is forward-only."
    )
