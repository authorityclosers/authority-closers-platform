"""Append-only receipts for scoped Studio draft authoring."""

import sqlalchemy as sa
from alembic import op

revision = "20260908_0022"
down_revision = "20260908_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_authoring_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(16), nullable=False, server_default="tenant"),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), sa.ForeignKey("audit_events.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_catalog_authoring_commands_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "tenant_id"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_catalog_authoring_commands_version_scope",
        ),
        sa.CheckConstraint("program_scope = 'tenant'", name="tenant_scope_only"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key_digest",
            name="uq_catalog_authoring_commands_actor_key",
        ),
        sa.CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_fingerprint) = 64",
            name="digest_lengths",
        ),
        sa.CheckConstraint(
            "operation IN ('module_add', 'module_update', 'activity_add', 'activity_update')",
            name="operation_supported",
        ),
    )
    op.create_index(
        "ix_catalog_authoring_commands_version",
        "catalog_authoring_commands",
        ["tenant_id", "program_version_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text("""
            CREATE FUNCTION ac_guard_catalog_authoring_command_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'catalog authoring command history is immutable'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$
        """)
        )
        op.execute(
            sa.text("""
            CREATE TRIGGER trg_catalog_authoring_commands_immutable
            BEFORE UPDATE OR DELETE ON catalog_authoring_commands
            FOR EACH ROW EXECUTE FUNCTION ac_guard_catalog_authoring_command_mutation()
        """)
        )


def downgrade() -> None:
    raise RuntimeError("catalog authoring command history is forward-only")
