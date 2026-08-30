"""Create immutable course-completion snapshots, certificates, and events.

Revision ID: 20260830_0005
Revises: 20260830_0004
"""

# ruff: noqa: S608 -- DDL interpolates only dialect-quoted connection schema identifiers.

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0005"
down_revision: str | None = "20260830_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GLOBAL_OWNER = "00000000000000000000000000000000"


def _scope_constraints(table: str) -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "program_scope IN ('global', 'tenant')",
            name=op.f(f"ck_{table}_scope_supported"),
        ),
        sa.CheckConstraint(
            f"(program_scope = 'global' AND program_tenant_id IS NULL "
            f"AND program_owner_key = '{GLOBAL_OWNER}') "
            "OR (program_scope = 'tenant' AND program_tenant_id IS NOT NULL "
            "AND program_owner_key = program_tenant_id)",
            name=op.f(f"ck_{table}_scope_owner"),
        ),
        sa.CheckConstraint(
            "program_scope = 'global' OR program_tenant_id = tenant_id",
            name=op.f(f"ck_{table}_tenant_owner"),
        ),
    )


def _event_digest_constraint() -> sa.CheckConstraint:
    """Use PostgreSQL regex where available and a portable shape check elsewhere."""

    expression = (
        "request_digest ~ '^[0-9a-f]{64}$'"
        if op.get_bind().dialect.name == "postgresql"
        else "length(request_digest) = 64"
    )
    return sa.CheckConstraint(
        expression,
        name=op.f("ck_certificate_events_request_digest_sha256"),
    )


def _active_postgresql_schema() -> tuple[str, str]:
    """Return the connection's trusted default schema and a quoted identifier."""

    bind = op.get_bind()
    schema = bind.dialect.default_schema_name
    if not isinstance(schema, str) or not schema:
        raise RuntimeError("PostgreSQL migrations require a resolved default schema")
    return schema, bind.dialect.identifier_preparer.quote_schema(schema)


def _identity_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(length=16), nullable=False),
        sa.Column("program_tenant_id", sa.Uuid(), nullable=True),
        sa.Column("program_owner_key", sa.Uuid(), nullable=False),
    )


def _identity_target(prefix: str) -> list[str]:
    return [
        f"{prefix}.enrollment_id",
        f"{prefix}.program_version_id",
        f"{prefix}.program_id",
        f"{prefix}.program_scope",
        f"{prefix}.program_owner_key",
    ]


def upgrade() -> None:
    op.create_table(
        "completion_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        *_identity_columns(),
        sa.Column("predicate_version", sa.String(length=64), nullable=False),
        sa.Column("required_activity_count", sa.Integer(), nullable=False),
        sa.Column("completed_activity_count", sa.Integer(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False),
        sa.Column("required_activity_ids", sa.JSON(), nullable=False),
        sa.Column("completed_activity_ids", sa.JSON(), nullable=False),
        sa.Column("module_results", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("supersedes_snapshot_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_completion_snapshots"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_completion_snapshots_full_identity",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_completion_snapshots_scoped_membership",
        ),
        sa.ForeignKeyConstraint(
            [
                "enrollment_id",
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.id",
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_completion_snapshots_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_completion_snapshots_program_version_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "supersedes_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_completion_snapshots_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_completion_snapshots_program_tenant_id_tenants",
        ),
        sa.CheckConstraint(
            "required_activity_count >= 0",
            name=op.f("ck_completion_snapshots_required_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "completed_activity_count >= 0",
            name=op.f("ck_completion_snapshots_completed_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "completed_activity_count <= required_activity_count",
            name=op.f("ck_completion_snapshots_completed_count_within_denominator"),
        ),
        sa.CheckConstraint(
            "NOT is_complete OR completed_activity_count = required_activity_count",
            name=op.f("ck_completion_snapshots_complete_count_matches"),
        ),
        sa.CheckConstraint(
            "NOT is_complete OR required_activity_count > 0",
            name=op.f("ck_completion_snapshots_complete_requires_activity"),
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64",
            name=op.f("ck_completion_snapshots_snapshot_hash_sha256"),
        ),
        *_scope_constraints("completion_snapshots"),
    )
    op.create_index(
        "ix_completion_snapshots_subject_version",
        "completion_snapshots",
        ["tenant_id", "person_id", "program_version_id"],
    )

    op.create_table(
        "course_completion_certificates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        *_identity_columns(),
        sa.Column(
            "certificate_type",
            sa.String(length=64),
            server_default=sa.text("'course-completion'"),
            nullable=False,
        ),
        sa.Column("original_completion_snapshot_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "issued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_course_completion_certificates"),
        sa.UniqueConstraint(
            "id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_course_completion_certificates_full_identity",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_id",
            "program_version_id",
            "program_scope",
            "program_owner_key",
            "certificate_type",
            name="uq_course_completion_certificates_subject_version_type",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_course_completion_certificates_scoped_membership",
        ),
        sa.ForeignKeyConstraint(
            [
                "enrollment_id",
                "tenant_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "enrollments.id",
                "enrollments.tenant_id",
                "enrollments.person_id",
                "enrollments.program_version_id",
                "enrollments.program_id",
                "enrollments.program_scope",
                "enrollments.program_owner_key",
            ],
            name="fk_course_completion_certificates_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_course_completion_certificates_program_version_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "original_completion_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_course_completion_certificates_original_snapshot",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_course_completion_certificates_program_tenant_id_tenants",
        ),
        sa.CheckConstraint(
            "certificate_type = 'course-completion'",
            name=op.f("ck_course_completion_certificates_type"),
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR length(trim(idempotency_key)) > 0",
            name=op.f("ck_course_completion_certificates_idempotency_nonblank"),
        ),
        *_scope_constraints("course_completion_certificates"),
    )
    op.create_index(
        "ix_course_completion_certificates_subject",
        "course_completion_certificates",
        ["tenant_id", "person_id"],
    )

    op.create_table(
        "certificate_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("certificate_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        *_identity_columns(),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("completion_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_event_id", sa.Uuid(), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_events"),
        sa.UniqueConstraint(
            "id",
            "certificate_id",
            "tenant_id",
            "person_id",
            "enrollment_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            name="uq_certificate_events_full_identity",
        ),
        sa.UniqueConstraint(
            "certificate_id", "sequence_no", name="uq_certificate_events_certificate_sequence_no"
        ),
        sa.UniqueConstraint(
            "certificate_id",
            "idempotency_key",
            name="uq_certificate_events_certificate_idempotency",
        ),
        sa.ForeignKeyConstraint(
            [
                "certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "course_completion_certificates.id",
                "course_completion_certificates.tenant_id",
                "course_completion_certificates.person_id",
                "course_completion_certificates.enrollment_id",
                "course_completion_certificates.program_version_id",
                "course_completion_certificates.program_id",
                "course_completion_certificates.program_scope",
                "course_completion_certificates.program_owner_key",
            ],
            name="fk_certificate_events_certificate_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "completion_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_certificate_events_snapshot_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "supersedes_event_id",
                "certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "certificate_events.id",
                "certificate_events.certificate_id",
                "certificate_events.tenant_id",
                "certificate_events.person_id",
                "certificate_events.enrollment_id",
                "certificate_events.program_version_id",
                "certificate_events.program_id",
                "certificate_events.program_scope",
                "certificate_events.program_owner_key",
            ],
            name="fk_certificate_events_supersedes",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_certificate_events_actor_person"
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_certificate_events_program_tenant_id_tenants",
        ),
        sa.CheckConstraint(
            "event_type IN ('issued', 'corrected', 'revoked')",
            name=op.f("ck_certificate_events_type"),
        ),
        sa.CheckConstraint(
            "event_type <> 'issued' OR completion_snapshot_id IS NOT NULL",
            name=op.f("ck_certificate_events_issue_has_snapshot"),
        ),
        sa.CheckConstraint(
            "event_type <> 'corrected' OR completion_snapshot_id IS NOT NULL",
            name=op.f("ck_certificate_events_correction_has_snapshot"),
        ),
        sa.CheckConstraint(
            "event_type = 'issued' OR actor_person_id IS NOT NULL",
            name=op.f("ck_certificate_events_change_has_actor"),
        ),
        sa.CheckConstraint(
            "event_type = 'issued' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name=op.f("ck_certificate_events_change_has_reason"),
        ),
        sa.CheckConstraint(
            "idempotency_key IS NULL OR length(trim(idempotency_key)) > 0",
            name=op.f("ck_certificate_events_idempotency_nonblank"),
        ),
        sa.CheckConstraint(
            "sequence_no >= 1", name=op.f("ck_certificate_events_sequence_positive")
        ),
        _event_digest_constraint(),
        *_scope_constraints("certificate_events"),
    )
    op.create_index(
        "ix_certificate_events_certificate_sequence",
        "certificate_events",
        ["certificate_id", "sequence_no"],
    )

    op.create_table(
        "certificate_command_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        *_identity_columns(),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("result_certificate_id", sa.Uuid(), nullable=True),
        sa.Column("result_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("result_event_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_certificate_command_idempotency"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_certificate_command_idempotency_actor_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_certificate_command_idempotency_subject_membership",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_certificate_command_idempotency_program_version",
        ),
        sa.ForeignKeyConstraint(
            [
                "result_certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "course_completion_certificates.id",
                "course_completion_certificates.tenant_id",
                "course_completion_certificates.person_id",
                "course_completion_certificates.enrollment_id",
                "course_completion_certificates.program_version_id",
                "course_completion_certificates.program_id",
                "course_completion_certificates.program_scope",
                "course_completion_certificates.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_certificate",
        ),
        sa.ForeignKeyConstraint(
            [
                "result_snapshot_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "completion_snapshots.id",
                "completion_snapshots.tenant_id",
                "completion_snapshots.person_id",
                "completion_snapshots.enrollment_id",
                "completion_snapshots.program_version_id",
                "completion_snapshots.program_id",
                "completion_snapshots.program_scope",
                "completion_snapshots.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_snapshot",
        ),
        sa.ForeignKeyConstraint(
            [
                "result_event_id",
                "result_certificate_id",
                "tenant_id",
                "person_id",
                "enrollment_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "certificate_events.id",
                "certificate_events.certificate_id",
                "certificate_events.tenant_id",
                "certificate_events.person_id",
                "certificate_events.enrollment_id",
                "certificate_events.program_version_id",
                "certificate_events.program_id",
                "certificate_events.program_scope",
                "certificate_events.program_owner_key",
            ],
            name="fk_certificate_command_idempotency_result_event",
        ),
        sa.ForeignKeyConstraint(
            ["program_tenant_id"],
            ["tenants.id"],
            name="fk_certificate_command_idempotency_program_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_certificate_command_idempotency_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_certificate_command_idempotency_scope_key",
        ),
        sa.CheckConstraint(
            "operation IN ('certificate_issue', 'certificate_correct', 'certificate_revoke')",
            name=op.f("ck_certificate_command_idempotency_operation_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed')",
            name=op.f("ck_certificate_command_idempotency_status"),
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) > 0",
            name=op.f("ck_certificate_command_idempotency_idempotency_key_nonblank"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 64",
            name=op.f("ck_certificate_command_idempotency_request_digest_sha256"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND result_certificate_id IS NULL "
            "AND result_snapshot_id IS NULL AND result_event_id IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'completed' AND result_certificate_id IS NOT NULL "
            "AND result_event_id IS NOT NULL AND completed_at IS NOT NULL "
            "AND ((operation = 'certificate_revoke' AND result_snapshot_id IS NULL) "
            "OR (operation IN ('certificate_issue', 'certificate_correct') "
            "AND result_snapshot_id IS NOT NULL)))",
            name=op.f("ck_certificate_command_idempotency_result_state_complete"),
        ),
        *_scope_constraints("certificate_command_idempotency"),
    )
    op.create_index(
        "ix_certificate_command_idempotency_result",
        "certificate_command_idempotency",
        ["tenant_id", "result_certificate_id", "result_event_id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        _, quoted_schema = _active_postgresql_schema()
        canonical_function = f"{quoted_schema}.ac_canonical_jsonb"
        reject_function = f"{quoted_schema}.ac_reject_certificate_record_mutation"
        guard_function = f"{quoted_schema}.ac_guard_certificate_event_chain"
        issued_function = f"{quoted_schema}.ac_require_certificate_issued_event"
        digest_error = "certificate event request_digest does not match canonical event contents"
        issued_error = "certificate must have an issued event in the same transaction"

        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {canonical_function}(value jsonb)
                RETURNS text
                LANGUAGE plpgsql
                IMMUTABLE
                STRICT
                PARALLEL SAFE
                SET search_path = pg_catalog
                AS $$
                DECLARE
                    kind text;
                    canonical text;
                BEGIN
                    kind := pg_catalog.jsonb_typeof(value);
                    IF kind = 'null' THEN
                        RETURN 'null';
                    ELSIF kind = 'boolean' OR kind = 'number' THEN
                        RETURN value::text;
                    ELSIF kind = 'string' THEN
                        RETURN pg_catalog.to_jsonb(value #>> '{{}}')::text;
                    ELSIF kind = 'array' THEN
                        SELECT COALESCE(
                            '[' || pg_catalog.string_agg(
                                {canonical_function}(item.value),
                                ',' ORDER BY item.position
                            ) || ']',
                            '[]'
                        )
                        INTO canonical
                        FROM pg_catalog.jsonb_array_elements(value)
                            WITH ORDINALITY AS item(value, position);
                        RETURN canonical;
                    ELSIF kind = 'object' THEN
                        SELECT COALESCE(
                            '{{' || pg_catalog.string_agg(
                                pg_catalog.to_jsonb(entry.key)::text || ':' ||
                                    {canonical_function}(entry.value),
                                ',' ORDER BY entry.key COLLATE "C"
                            ) || '}}',
                            '{{}}'
                        )
                        INTO canonical
                        FROM pg_catalog.jsonb_each(value) AS entry(key, value);
                        RETURN canonical;
                    END IF;
                    RAISE EXCEPTION 'unsupported JSON kind for certificate digest: %', kind
                        USING ERRCODE = 'integrity_constraint_violation';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {reject_function}()
                RETURNS trigger
                LANGUAGE plpgsql
                SET search_path = pg_catalog
                AS $$
                BEGIN
                    RAISE EXCEPTION 'certificate records are immutable; append an event instead'
                        USING ERRCODE = 'integrity_constraint_violation';
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {guard_function}()
                RETURNS trigger
                LANGUAGE plpgsql
                SET search_path = pg_catalog, {quoted_schema}, pg_temp
                AS $$
                DECLARE
                    predecessor {quoted_schema}.certificate_events%ROWTYPE;
                    canonical_payload text;
                    expected_digest text;
                BEGIN
                    -- Serialize every append for a certificate, including direct
                    -- SQL, so two writers cannot observe the same predecessor.
                    PERFORM 1
                    FROM {quoted_schema}.course_completion_certificates
                    WHERE id = NEW.certificate_id
                    FOR UPDATE;

                    SELECT * INTO predecessor
                    FROM {quoted_schema}.certificate_events
                    WHERE certificate_id = NEW.certificate_id
                    ORDER BY sequence_no DESC
                    LIMIT 1
                    FOR UPDATE;

                    IF NOT FOUND THEN
                        IF NEW.event_type <> 'issued'
                           OR NEW.supersedes_event_id IS NOT NULL
                           OR NEW.sequence_no <> 1 THEN
                            RAISE EXCEPTION 'certificate chain must start with one issued event'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                    ELSE
                        IF NEW.event_type = 'issued'
                           OR NEW.supersedes_event_id IS NULL
                           OR NEW.supersedes_event_id <> predecessor.id
                           OR NEW.sequence_no <> predecessor.sequence_no + 1 THEN
                            RAISE EXCEPTION
                                'certificate event must append the exact current predecessor'
                                USING ERRCODE = 'integrity_constraint_violation';
                        END IF;
                    END IF;

                    canonical_payload := {canonical_function}(
                        pg_catalog.jsonb_build_object(
                            'certificate_id', NEW.certificate_id::text,
                            'tenant_id', NEW.tenant_id::text,
                            'person_id', NEW.person_id::text,
                            'enrollment_id', NEW.enrollment_id::text,
                            'program_id', NEW.program_id::text,
                            'program_version_id', NEW.program_version_id::text,
                            'program_scope', NEW.program_scope,
                            'program_tenant_id', NEW.program_tenant_id::text,
                            'program_owner_key', NEW.program_owner_key::text,
                            'event_type', NEW.event_type,
                            'completion_snapshot_id', NEW.completion_snapshot_id::text,
                            'supersedes_event_id', NEW.supersedes_event_id::text,
                            'actor_person_id', NEW.actor_person_id::text,
                            'reason', NEW.reason,
                            'provenance', NEW.provenance::jsonb,
                            'idempotency_key', NEW.idempotency_key
                        )
                    );
                    expected_digest := pg_catalog.encode(
                        pg_catalog.sha256(pg_catalog.convert_to(canonical_payload, 'UTF8')),
                        'hex'
                    );
                    IF NEW.request_digest IS DISTINCT FROM expected_digest THEN
                        RAISE EXCEPTION '{digest_error}'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {issued_function}()
                RETURNS trigger
                LANGUAGE plpgsql
                SET search_path = pg_catalog, {quoted_schema}, pg_temp
                AS $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM {quoted_schema}.certificate_events
                        WHERE certificate_id = NEW.id
                          AND event_type = 'issued'
                    ) THEN
                        RAISE EXCEPTION '{issued_error}'
                            USING ERRCODE = 'integrity_constraint_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_certificate_events_chain
                BEFORE INSERT ON {quoted_schema}.certificate_events
                FOR EACH ROW EXECUTE FUNCTION {guard_function}()
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE CONSTRAINT TRIGGER trg_certificate_requires_issued_event
                AFTER INSERT ON {quoted_schema}.course_completion_certificates
                DEFERRABLE INITIALLY DEFERRED
                FOR EACH ROW EXECUTE FUNCTION {issued_function}()
                """
            )
        )
        for table in (
            "completion_snapshots",
            "course_completion_certificates",
            "certificate_events",
        ):
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER trg_{table}_immutable
                    BEFORE UPDATE OR DELETE ON {quoted_schema}.{table}
                    FOR EACH ROW EXECUTE FUNCTION {reject_function}()
                    """
                )
            )


def downgrade() -> None:
    raise RuntimeError("certificate migrations are forward-only")
