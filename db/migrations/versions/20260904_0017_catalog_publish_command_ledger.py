"""Add the replay-safe Academy Studio publication command ledger."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260904_0017"
down_revision: str | None = "20260903_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_publish_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key_digest", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'completed')",
            name=op.f("ck_catalog_publish_commands_state_supported"),
        ),
        sa.CheckConstraint(
            "length(idempotency_key_digest) = 64 AND length(request_fingerprint) = 64",
            name=op.f("ck_catalog_publish_commands_digest_lengths"),
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND response_payload IS NULL "
            "AND audit_event_id IS NULL AND completed_at IS NULL) OR "
            "(state = 'completed' AND response_payload IS NOT NULL "
            "AND audit_event_id IS NOT NULL AND completed_at IS NOT NULL)",
            name=op.f("ck_catalog_publish_commands_completion_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_catalog_publish_commands_tenant_id_tenants"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name=op.f("fk_catalog_publish_commands_actor_person_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id"],
            ["program_versions.id"],
            name=op.f("fk_catalog_publish_commands_program_version_id_program_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_catalog_publish_commands_audit_event_id_audit_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_publish_commands")),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "idempotency_key_digest",
            name=op.f("uq_catalog_publish_commands_actor_key"),
        ),
    )
    op.create_index(
        "ix_catalog_publish_commands_version",
        "catalog_publish_commands",
        ["tenant_id", "program_version_id"],
        unique=False,
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE FUNCTION ac_guard_catalog_publish_command_mutation()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF TG_OP = 'INSERT' THEN
                        IF NEW.state = 'pending'
                           AND NEW.response_payload IS NULL
                           AND NEW.audit_event_id IS NULL
                           AND NEW.completed_at IS NULL THEN
                            RETURN NEW;
                        END IF;
                        RAISE EXCEPTION 'catalog publication commands must be reserved as pending'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'catalog publication command history cannot be deleted'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    IF OLD.state = 'pending'
                       AND NEW.state = 'completed'
                       AND NEW.response_payload IS NOT NULL
                       AND NEW.audit_event_id IS NOT NULL
                       AND NEW.completed_at IS NOT NULL
                       AND NEW.id IS NOT DISTINCT FROM OLD.id
                       AND NEW.tenant_id IS NOT DISTINCT FROM OLD.tenant_id
                       AND NEW.actor_person_id IS NOT DISTINCT FROM OLD.actor_person_id
                       AND NEW.program_version_id IS NOT DISTINCT FROM OLD.program_version_id
                       AND NEW.idempotency_key_digest IS NOT DISTINCT FROM
                           OLD.idempotency_key_digest
                       AND NEW.request_fingerprint IS NOT DISTINCT FROM OLD.request_fingerprint
                       AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at THEN
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'catalog publication command history is immutable'
                        USING ERRCODE = 'integrity_constraint_violation';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_catalog_publish_commands_immutable
                BEFORE INSERT OR UPDATE OR DELETE ON catalog_publish_commands
                FOR EACH ROW EXECUTE FUNCTION ac_guard_catalog_publish_command_mutation()
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError("catalog publication command ledger is forward-only")
