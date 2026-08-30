"""Create the explicit enrollment, provenance, and entitlement boundary.

Revision ID: 20260830_0003
Revises: 20260830_0002
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0003"
down_revision: str | None = "20260830_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GLOBAL_OWNER = "00000000000000000000000000000000"


def _catalog_scope_constraints(table: str) -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name=op.f(f"ck_{table}_program_scope_supported"),
        ),
        sa.CheckConstraint(
            f"(program_scope = 'global' AND program_tenant_id IS NULL "
            f"AND program_owner_key = '{GLOBAL_OWNER}') "
            "OR (program_scope = 'tenant' AND program_tenant_id IS NOT NULL "
            "AND program_owner_key = program_tenant_id)",
            name=op.f(f"ck_{table}_program_scope_owner_match"),
        ),
        sa.CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name=op.f(f"ck_{table}_tenant_program_owner_match"),
        ),
    )


def _catalog_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(length=16), nullable=False),
        sa.Column("program_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("program_owner_key", sa.Uuid(), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "enrollment_eligibility_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("age_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("eligibility_passed", sa.Boolean(), nullable=False),
        sa.Column("prerequisites_satisfied", sa.Boolean(), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("evidence", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_enrollment_eligibility_facts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_enrollment_eligibility_facts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollment_eligibility_facts_subject_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollment_eligibility_facts_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_enrollment_eligibility_facts_program_version",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_enrollment_eligibility_facts_program_tenant",
        ),
        sa.CheckConstraint(
            "length(trim(policy_version)) > 0",
            name=op.f("ck_enrollment_eligibility_facts_policy_version_nonblank"),
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > evaluated_at",
            name=op.f("ck_enrollment_eligibility_facts_valid_window"),
        ),
        *_catalog_scope_constraints("enrollment_eligibility_facts"),
    )
    op.create_index(
        "ix_enrollment_eligibility_facts_subject_version",
        "enrollment_eligibility_facts",
        ["tenant_id", "person_id", "program_version_id"],
    )

    op.create_table(
        "enrollments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "enrolled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_enrollments"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_enrollments_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            name="uq_enrollments_subject_program_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_tenant_person_program_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_scoped_full_identity",
        ),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollments_full_identity",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollments_tenant_person_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_enrollments_program_version_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"], ["tenants.id"], name="fk_enrollments_program_tenant_id_tenants"
        ),
        sa.CheckConstraint(
            "source IN ('free_self', 'manual_grant')",
            name=op.f("ck_enrollments_source_allowed"),
        ),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_enrollments_status")),
        *_catalog_scope_constraints("enrollments"),
    )
    op.create_index("ix_enrollments_person_tenant", "enrollments", ["person_id", "tenant_id"])
    op.create_index(
        "ix_enrollments_program_version", "enrollments", ["tenant_id", "program_version_id"]
    )

    op.create_table(
        "command_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("subject_person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("result_enrollment_id", sa.Uuid(), nullable=True),
        sa.Column("result_entitlement_id", sa.Uuid(), nullable=True),
        sa.Column("result_provenance_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_command_idempotency"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_command_idempotency_actor_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "subject_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_command_idempotency_subject_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_command_idempotency_program_version",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "result_enrollment_id",
                "subject_person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_command_idempotency_result_enrollment",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_command_idempotency_program_tenant",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_command_idempotency_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_command_idempotency_scope_key",
        ),
        sa.CheckConstraint(
            "operation IN ('enroll_free', 'grant_manual')",
            name=op.f("ck_command_idempotency_operation_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')", name=op.f("ck_command_idempotency_status")
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name=op.f("ck_command_idempotency_idempotency_key_nonblank"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name=op.f("ck_command_idempotency_request_digest_sha256"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND result_enrollment_id IS NULL "
            "AND result_entitlement_id IS NULL AND result_provenance_id IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_enrollment_id IS NOT NULL "
            "AND result_entitlement_id IS NOT NULL AND result_provenance_id IS NOT NULL "
            "AND completed_at IS NOT NULL)",
            name=op.f("ck_command_idempotency_result_state_complete"),
        ),
        *_catalog_scope_constraints("command_idempotency"),
    )
    op.create_index(
        "ix_command_idempotency_result_enrollment",
        "command_idempotency",
        ["tenant_id", "result_enrollment_id"],
    )

    op.create_table(
        "enrollment_provenance",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("command_idempotency_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "audit_event_name",
            sa.String(length=128),
            server_default=sa.text("'audit.enrollment.created.v1'"),
            nullable=False,
        ),
        sa.Column("policy_inputs", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("controlled_gaps", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_enrollment_provenance"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_enrollment_provenance_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_enrollment_provenance_full_identity",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_enrollment_provenance_enrollment",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_enrollment_provenance_subject_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "command_idempotency_id"],
            ["command_idempotency.tenant_id", "command_idempotency.id"],
            name="fk_enrollment_provenance_command",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_enrollment_provenance_actor_person"
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_enrollment_provenance_program_tenant_id_tenants",
        ),
        sa.CheckConstraint(
            "source IN ('free_self', 'manual_grant')",
            name=op.f("ck_enrollment_provenance_source_allowed"),
        ),
        sa.CheckConstraint(
            "source <> 'free_self' OR actor_person_id = person_id",
            name=op.f("ck_enrollment_provenance_free_source_requires_self"),
        ),
        sa.CheckConstraint(
            "source <> 'manual_grant' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name=op.f("ck_enrollment_provenance_manual_source_requires_reason"),
        ),
        *_catalog_scope_constraints("enrollment_provenance"),
    )
    op.create_index(
        "ix_enrollment_provenance_enrollment",
        "enrollment_provenance",
        ["tenant_id", "enrollment_id"],
    )
    op.create_index(
        "ix_enrollment_provenance_subject", "enrollment_provenance", ["tenant_id", "person_id"]
    )

    op.create_table(
        "entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("provenance_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_entitlements"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_entitlements_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_entitlements_full_identity",
        ),
        sa.UniqueConstraint("tenant_id", "enrollment_id", name="uq_entitlements_enrollment"),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_entitlements_subject_program_version",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_entitlements_enrollment",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_entitlements_subject_program_enrollment",
        ),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "provenance_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollment_provenance.tenant_id",
                "enrollment_provenance.id",
                "enrollment_provenance.person_id",
                "enrollment_provenance.program_version_id",
                "enrollment_provenance.program_id",
                "enrollment_provenance.program_scope",
                "enrollment_provenance.program_owner_key",
            ],
            name="fk_entitlements_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"], ["tenants.id"], name="fk_entitlements_program_tenant_id_tenants"
        ),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_entitlements_status")),
        *_catalog_scope_constraints("entitlements"),
    )
    op.create_index("ix_entitlements_subject", "entitlements", ["tenant_id", "person_id"])
    op.create_index(
        "ix_entitlements_program_version", "entitlements", ["tenant_id", "program_version_id"]
    )

    op.create_foreign_key(
        "fk_command_idempotency_result_entitlement",
        "command_idempotency",
        "entitlements",
        [
            "tenant_id",
            "result_entitlement_id",
            "subject_person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
        ],
        [
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
        ],
    )
    op.create_foreign_key(
        "fk_command_idempotency_result_provenance",
        "command_idempotency",
        "enrollment_provenance",
        [
            "tenant_id",
            "result_provenance_id",
            "subject_person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
        ],
        [
            "tenant_id",
            "id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
        ],
    )
    op.create_index(
        "ix_command_idempotency_result_entitlement",
        "command_idempotency",
        ["tenant_id", "result_entitlement_id"],
    )
    op.create_index(
        "ix_command_idempotency_result_provenance",
        "command_idempotency",
        ["tenant_id", "result_provenance_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION ac_reject_enrollment_provenance_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'enrollment provenance is append-only'
                    USING ERRCODE = 'integrity_constraint_violation';
            END;
            $$
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_enrollment_provenance_immutable
            BEFORE UPDATE OR DELETE ON enrollment_provenance
            FOR EACH ROW EXECUTE FUNCTION ac_reject_enrollment_provenance_mutation()
            """
        )


def downgrade() -> None:
    raise RuntimeError("enrollment migrations are forward-only")
