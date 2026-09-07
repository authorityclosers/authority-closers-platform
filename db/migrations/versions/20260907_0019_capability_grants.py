"""Add immutable explicit platform and scoped Studio capability history."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0019"
down_revision: str | None = "20260904_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("programs") as batch:
        batch.create_unique_constraint("uq_programs_tenant_identity", ["id", "tenant_id"])

    op.create_table(
        "capability_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_person_id", sa.Uuid(), nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("scope_kind", sa.String(16), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("program_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "permission IN ('platform_access_manage', 'platform_tenants_read', "
            "'platform_catalog_read', 'platform_catalog_write', 'platform_catalog_publish', "
            "'catalog_read', 'catalog_write', 'catalog_publish', 'learner_diagnose', "
            "'learning_review')",
            name=op.f("ck_capability_grants_permission_supported"),
        ),
        sa.CheckConstraint(
            "scope_kind IN ('platform', 'tenant', 'program')",
            name=op.f("ck_capability_grants_scope_supported"),
        ),
        sa.CheckConstraint(
            "(scope_kind = 'platform' AND tenant_id IS NULL AND program_id IS NULL) OR "
            "(scope_kind = 'tenant' AND tenant_id IS NOT NULL AND program_id IS NULL) OR "
            "(scope_kind = 'program' AND tenant_id IS NOT NULL AND program_id IS NOT NULL)",
            name=op.f("ck_capability_grants_scope_shape"),
        ),
        sa.CheckConstraint(
            "(scope_kind = 'platform' AND permission IN ('platform_access_manage', "
            "'platform_tenants_read', 'platform_catalog_read', 'platform_catalog_write', "
            "'platform_catalog_publish')) OR "
            "(scope_kind IN ('tenant', 'program') AND permission IN ('catalog_read', "
            "'catalog_write', 'catalog_publish', 'learner_diagnose', 'learning_review'))",
            name=op.f("ck_capability_grants_permission_scope"),
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0 AND length(reason) <= 500",
            name=op.f("ck_capability_grants_reason_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_person_id"],
            ["persons.id"],
            name=op.f("fk_capability_grants_subject_person_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_capability_grants_tenant_id_tenants"),
        ),
        sa.ForeignKeyConstraint(
            ["program_id", "tenant_id"],
            ["programs.id", "programs.tenant_id"],
            name=op.f("fk_capability_grants_program_tenant"),
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_person_id"],
            ["persons.id"],
            name=op.f("fk_capability_grants_granted_by_person_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_capability_grants_audit_event_id_audit_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_grants")),
        sa.UniqueConstraint("audit_event_id", name=op.f("uq_capability_grants_audit_event")),
    )
    op.create_index(
        "ix_capability_grants_subject_scope",
        "capability_grants",
        ["subject_person_id", "scope_kind", "tenant_id"],
    )
    op.create_index(
        "ix_capability_grants_program", "capability_grants", ["tenant_id", "program_id"]
    )
    op.create_table(
        "capability_revocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=False),
        sa.Column("revoked_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("audit_event_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "length(trim(reason)) > 0 AND length(reason) <= 500",
            name=op.f("ck_capability_revocations_reason_bound"),
        ),
        sa.ForeignKeyConstraint(
            ["grant_id"],
            ["capability_grants.id"],
            name=op.f("fk_capability_revocations_grant_id_capability_grants"),
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_person_id"],
            ["persons.id"],
            name=op.f("fk_capability_revocations_revoked_by_person_id_persons"),
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_capability_revocations_audit_event_id_audit_events"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_revocations")),
        sa.UniqueConstraint("grant_id", name=op.f("uq_capability_revocations_grant")),
        sa.UniqueConstraint("audit_event_id", name=op.f("uq_capability_revocations_audit_event")),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION ac_guard_capability_history_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'capability history is immutable; append a new command'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$
            """
        )
        for table in ("capability_grants", "capability_revocations"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_immutable "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION ac_guard_capability_history_mutation()"
            )


def downgrade() -> None:
    raise RuntimeError("capability grant and revocation history is forward-only")
