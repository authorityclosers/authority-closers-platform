"""Create durable operations, provider inbox, and audit evidence tables.

Revision ID: 20260830_0006
Revises: 20260830_0005

This migration is intentionally forward-only. Recovery and audit history are
not safely reconstructed by a destructive downgrade.
"""

# ruff: noqa: S608 -- DDL interpolates only dialect-quoted connection schema identifiers.

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0006"
down_revision: str | None = "20260830_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _active_postgresql_schema() -> tuple[str, str]:
    """Return the connection's trusted default schema and a quoted identifier."""

    bind = op.get_bind()
    schema = bind.dialect.default_schema_name
    if not isinstance(schema, str) or not schema:
        raise RuntimeError("PostgreSQL migrations require a resolved default schema")
    return schema, bind.dialect.identifier_preparer.quote_schema(schema)


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=200), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "publish_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_reason", sa.String(length=500), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_by", sa.Uuid(), nullable=True),
        sa.Column("reconciliation_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_outbox_events_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["reconciled_by"],
            ["persons.id"],
            name="fk_outbox_events_reconciled_by_persons",
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('pending', 'held', 'published', 'dead_letter')",
            name=op.f("ck_outbox_events_status"),
        ),
        sa.CheckConstraint(
            "length(trim(event_type)) > 0",
            name=op.f("ck_outbox_events_event_type_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(aggregate_type)) > 0",
            name=op.f("ck_outbox_events_aggregate_type_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(dedupe_key)) > 0",
            name=op.f("ck_outbox_events_dedupe_key_nonblank"),
        ),
        sa.CheckConstraint(
            "publish_attempts >= 0",
            name=op.f("ck_outbox_events_publish_attempts_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'held' AND held_at IS NOT NULL AND hold_reason IS NOT NULL "
            "AND length(trim(hold_reason)) > 0) OR "
            "(status <> 'held' AND held_at IS NULL AND hold_reason IS NULL)",
            name=op.f("ck_outbox_events_held_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL) OR "
            "(status <> 'published' AND published_at IS NULL)",
            name=op.f("ck_outbox_events_published_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL "
            "AND last_error IS NOT NULL AND length(trim(last_error)) > 0) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name=op.f("ck_outbox_events_dead_letter_state_consistent"),
        ),
        sa.CheckConstraint(
            "(reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(reconciled_at IS NOT NULL AND reconciled_by IS NOT NULL "
            "AND reconciliation_reason IS NOT NULL "
            "AND length(trim(reconciliation_reason)) > 0)",
            name=op.f("ck_outbox_events_reconciliation_state_consistent"),
        ),
    )
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_outbox_events_aggregate",
        "outbox_events",
        ["aggregate_type", "aggregate_id"],
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=128), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "external_side_effect",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "recovery_generation",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("5"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("provider_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_receipt", sa.JSON(), nullable=True),
        sa.Column("provider_receipt_digest", sa.String(length=64), nullable=True),
        sa.Column("receipt_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_ambiguous_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("held_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hold_reason", sa.String(length=500), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_by", sa.Uuid(), nullable=True),
        sa.Column("reconciliation_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_jobs_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["reconciled_by"],
            ["persons.id"],
            name="fk_jobs_reconciled_by_persons",
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_jobs_dedupe_key"),
        sa.CheckConstraint(
            "status IN ('queued', 'leased', 'retry_wait', 'held', 'succeeded', 'dead_letter')",
            name=op.f("ck_jobs_status"),
        ),
        sa.CheckConstraint(
            "length(trim(kind)) > 0",
            name=op.f("ck_jobs_kind_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(dedupe_key)) > 0",
            name=op.f("ck_jobs_dedupe_key_nonblank"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name=op.f("ck_jobs_attempt_bounds"),
        ),
        sa.CheckConstraint(
            "(status = 'leased' AND lease_token IS NOT NULL AND leased_until IS NOT NULL) OR "
            "(status <> 'leased' AND lease_token IS NULL AND leased_until IS NULL)",
            name=op.f("ck_jobs_lease_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'held' AND held_at IS NOT NULL AND hold_reason IS NOT NULL "
            "AND length(trim(hold_reason)) > 0) OR "
            "(status <> 'held' AND held_at IS NULL AND hold_reason IS NULL)",
            name=op.f("ck_jobs_held_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL "
            "AND last_error IS NOT NULL AND length(trim(last_error)) > 0) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name=op.f("ck_jobs_dead_letter_state_consistent"),
        ),
        sa.CheckConstraint(
            "(reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(reconciled_at IS NOT NULL AND reconciled_by IS NOT NULL "
            "AND reconciliation_reason IS NOT NULL "
            "AND length(trim(reconciliation_reason)) > 0)",
            name=op.f("ck_jobs_reconciliation_state_consistent"),
        ),
        sa.CheckConstraint(
            "(provider_receipt IS NULL AND provider_receipt_digest IS NULL "
            "AND receipt_recorded_at IS NULL) OR "
            "(provider_receipt IS NOT NULL AND provider_receipt_digest IS NOT NULL "
            "AND receipt_recorded_at IS NOT NULL)",
            name=op.f("ck_jobs_provider_receipt_state_consistent"),
        ),
        sa.CheckConstraint(
            "(dispatch_started_at IS NULL AND provider_idempotency_key IS NULL) OR "
            "(dispatch_started_at IS NOT NULL AND provider_idempotency_key IS NOT NULL)",
            name=op.f("ck_jobs_dispatch_state_consistent"),
        ),
        sa.CheckConstraint(
            "delivery_ambiguous_at IS NULL OR dispatch_started_at IS NOT NULL",
            name=op.f("ck_jobs_ambiguous_delivery_requires_dispatch"),
        ),
        sa.CheckConstraint(
            "(external_side_effect AND recovery_generation >= 1) OR "
            "(NOT external_side_effect AND recovery_generation = 0)",
            name=op.f("ck_jobs_recovery_generation_consistent"),
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR NOT external_side_effect OR provider_receipt IS NOT NULL",
            name=op.f("ck_jobs_external_success_requires_receipt"),
        ),
    )
    op.create_index(
        "ix_jobs_claimable",
        "jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index("ix_jobs_tenant_status", "jobs", ["tenant_id", "status"])

    recovery_state = op.create_table(
        "operations_recovery_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'held'"),
            nullable=False,
        ),
        sa.Column(
            "marked_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "hold_reason",
            sa.String(length=500),
            server_default=sa.text("'initial_activation_requires_reconciliation'"),
            nullable=False,
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_by", sa.Uuid(), nullable=True),
        sa.Column("reconciliation_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_operations_recovery_state"),
        sa.ForeignKeyConstraint(
            ["reconciled_by"],
            ["persons.id"],
            name="fk_operations_recovery_state_reconciled_by_persons",
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_operations_recovery_state_singleton")),
        sa.CheckConstraint(
            "generation >= 1",
            name=op.f("ck_operations_recovery_state_generation_positive"),
        ),
        sa.CheckConstraint(
            "status IN ('held', 'ready')",
            name=op.f("ck_operations_recovery_state_status"),
        ),
        sa.CheckConstraint(
            "status <> 'held' OR (marked_at IS NOT NULL AND hold_reason IS NOT NULL)",
            name=op.f("ck_operations_recovery_state_held_evidence_required"),
        ),
        sa.CheckConstraint(
            "(status = 'held' AND reconciled_at IS NULL AND reconciled_by IS NULL "
            "AND reconciliation_reason IS NULL) OR "
            "(status = 'ready' AND reconciled_at IS NOT NULL "
            "AND reconciled_by IS NOT NULL AND reconciliation_reason IS NOT NULL)",
            name=op.f("ck_operations_recovery_state_reconciliation_state_consistent"),
        ),
    )
    op.bulk_insert(
        recovery_state,
        [
            {
                "id": 1,
                "generation": 1,
                "status": "held",
                "hold_reason": "initial_activation_requires_reconciliation",
            }
        ],
    )

    op.create_table(
        "provider_inbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=160), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=100), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("verified_body_digest", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'received'"),
            nullable=False,
        ),
        sa.Column("processing_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "max_processing_attempts",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column("processing_lease_token", sa.Uuid(), nullable=True),
        sa.Column("processing_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_inbox"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_provider_inbox_tenant_id_tenants",
        ),
        sa.UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_provider_inbox_provider_event",
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0",
            name=op.f("ck_provider_inbox_provider_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(external_event_id)) > 0",
            name=op.f("ck_provider_inbox_external_event_id_nonblank"),
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processing', 'retry_wait', 'processed', 'dead_letter')",
            name=op.f("ck_provider_inbox_status"),
        ),
        sa.CheckConstraint(
            "length(payload_digest) = 64",
            name=op.f("ck_provider_inbox_payload_digest_length"),
        ),
        sa.CheckConstraint(
            "processing_attempts >= 0 AND max_processing_attempts >= 1 "
            "AND processing_attempts <= max_processing_attempts",
            name=op.f("ck_provider_inbox_processing_attempt_bounds"),
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND processing_lease_token IS NOT NULL "
            "AND processing_lease_until IS NOT NULL) OR "
            "(status <> 'processing' AND processing_lease_token IS NULL "
            "AND processing_lease_until IS NULL)",
            name=op.f("ck_provider_inbox_processing_lease_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'processed' AND processed_at IS NOT NULL) OR "
            "(status <> 'processed' AND processed_at IS NULL)",
            name=op.f("ck_provider_inbox_processed_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'dead_letter' AND dead_lettered_at IS NOT NULL) OR "
            "(status <> 'dead_letter' AND dead_lettered_at IS NULL)",
            name=op.f("ck_provider_inbox_dead_letter_state_consistent"),
        ),
        sa.CheckConstraint(
            "(status IN ('retry_wait', 'dead_letter') AND last_error IS NOT NULL) OR "
            "(status NOT IN ('retry_wait', 'dead_letter') AND last_error IS NULL)",
            name=op.f("ck_provider_inbox_failure_state_consistent"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('retry_wait', 'dead_letter') OR "
            "(last_error IS NOT NULL AND length(trim(last_error)) > 0)",
            name=op.f("ck_provider_inbox_failure_evidence_nonblank"),
        ),
        sa.CheckConstraint(
            "verified_body_digest IS NULL OR length(verified_body_digest) = 64",
            name=op.f("ck_provider_inbox_verified_body_digest_length"),
        ),
    )
    op.create_index(
        "ix_provider_inbox_status_available",
        "provider_inbox",
        ["status", "available_at"],
    )
    op.create_index("ix_provider_inbox_tenant", "provider_inbox", ["tenant_id", "received_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column(
            "actor_type",
            sa.String(length=32),
            server_default=sa.text("'person'"),
            nullable=False,
        ),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_events_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_audit_events_actor_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_audit_events_session_id_sessions",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "sequence_no",
            name="uq_audit_events_tenant_sequence",
        ),
        sa.CheckConstraint(
            "length(trim(action)) > 0",
            name=op.f("ck_audit_events_action_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(actor_type)) > 0",
            name=op.f("ck_audit_events_actor_type_nonblank"),
        ),
        sa.CheckConstraint(
            "length(trim(resource_type)) > 0",
            name=op.f("ck_audit_events_resource_type_nonblank"),
        ),
        sa.CheckConstraint(
            "sequence_no >= 1",
            name=op.f("ck_audit_events_sequence_positive"),
        ),
        sa.CheckConstraint(
            "length(previous_hash) = 64 AND length(event_hash) = 64",
            name=op.f("ck_audit_events_hash_lengths"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(trim(reason)) > 0",
            name=op.f("ck_audit_events_reason_nonblank"),
        ),
        sa.CheckConstraint(
            "request_id IS NULL OR length(trim(request_id)) > 0",
            name=op.f("ck_audit_events_request_id_nonblank"),
        ),
    )
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["tenant_id", "resource_type", "resource_id"],
    )

    op.create_table(
        "audit_chain_heads",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("tenant_id", name="pk_audit_chain_heads"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_audit_chain_heads_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["audit_events.id"],
            name="fk_audit_chain_heads_event_id_audit_events",
        ),
        sa.CheckConstraint(
            "sequence_no >= 1",
            name=op.f("ck_audit_chain_heads_sequence_positive"),
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name=op.f("ck_audit_chain_heads_event_hash_length"),
        ),
    )

    if op.get_bind().dialect.name == "postgresql":
        _schema, quoted_schema = _active_postgresql_schema()
        op.execute(sa.text(f"REVOKE CREATE ON SCHEMA {quoted_schema} FROM PUBLIC"))
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {quoted_schema}.reject_audit_evidence_mutation() RETURNS trigger
                LANGUAGE plpgsql AS $$
                BEGIN
                    RAISE EXCEPTION '% is append-only audit evidence', TG_TABLE_NAME;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {quoted_schema}.append_audit_chain_head(
                    p_tenant_id uuid,
                    p_sequence_no integer,
                    p_event_id uuid,
                    p_event_hash text,
                    p_updated_at timestamptz
                ) RETURNS void
                LANGUAGE plpgsql
                SECURITY DEFINER
                SET search_path = pg_catalog, {quoted_schema}, pg_temp
                AS $$
                DECLARE
                    current_sequence integer;
                    current_event_id uuid;
                    current_event_hash text;
                    event_tenant_id uuid;
                    event_sequence integer;
                    event_previous_hash text;
                    event_hash text;
                BEGIN
                    IF p_tenant_id IS NULL OR p_event_id IS NULL OR p_updated_at IS NULL THEN
                        RAISE EXCEPTION 'audit checkpoint arguments must not be null';
                    END IF;
                    IF p_sequence_no < 1 OR p_event_hash !~ '^[0-9a-f]{{64}}$' THEN
                        RAISE EXCEPTION 'audit checkpoint arguments are invalid';
                    END IF;

                    -- Serialize first-row and subsequent appends independently of
                    -- caller behavior, then verify the event before changing the head.
                    PERFORM pg_catalog.pg_advisory_xact_lock(
                        pg_catalog.hashtextextended(p_tenant_id::text, 0)
                    );
                    SELECT ae.tenant_id, ae.sequence_no, ae.previous_hash, ae.event_hash
                    INTO event_tenant_id, event_sequence, event_previous_hash, event_hash
                    FROM {quoted_schema}.audit_events AS ae
                    WHERE ae.id = p_event_id
                    FOR KEY SHARE;
                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'audit checkpoint event does not exist';
                    END IF;
                    IF event_tenant_id <> p_tenant_id
                       OR event_sequence <> p_sequence_no
                       OR event_hash <> p_event_hash THEN
                        RAISE EXCEPTION 'audit checkpoint does not match its event';
                    END IF;

                    SELECT h.sequence_no, h.event_id, h.event_hash
                    INTO current_sequence, current_event_id, current_event_hash
                    FROM {quoted_schema}.audit_chain_heads AS h
                    WHERE h.tenant_id = p_tenant_id
                    FOR UPDATE;
                    IF NOT FOUND THEN
                        IF p_sequence_no <> 1
                           OR event_previous_hash <> pg_catalog.repeat('0', 64) THEN
                            RAISE EXCEPTION 'first audit checkpoint must start at genesis';
                        END IF;
                        INSERT INTO {quoted_schema}.audit_chain_heads
                            (tenant_id, sequence_no, event_id, event_hash, updated_at)
                        VALUES
                            (p_tenant_id, p_sequence_no, p_event_id, p_event_hash, p_updated_at);
                    ELSE
                        IF p_sequence_no <> current_sequence + 1
                           OR event_previous_hash <> current_event_hash THEN
                            RAISE EXCEPTION 'audit checkpoint is not the next verified chain head';
                        END IF;
                        UPDATE {quoted_schema}.audit_chain_heads
                        SET sequence_no = p_sequence_no,
                            event_id = p_event_id,
                            event_hash = p_event_hash,
                            updated_at = p_updated_at
                        WHERE tenant_id = p_tenant_id;
                    END IF;
                END;
                $$
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                REVOKE ALL ON FUNCTION {quoted_schema}.append_audit_chain_head(
                    uuid, integer, uuid, text, timestamptz
                ) FROM PUBLIC;
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ac_runtime') THEN
                        EXECUTE 'GRANT EXECUTE ON FUNCTION {quoted_schema}.append_audit_chain_head'
                            '(uuid, integer, uuid, text, timestamptz) TO ac_runtime';
                    END IF;
                END;
                $$;
                REVOKE ALL ON TABLE {quoted_schema}.audit_chain_heads FROM PUBLIC;
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'ac_runtime') THEN
                        EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE '
                            '{quoted_schema}.audit_chain_heads FROM ac_runtime';
                        EXECUTE 'GRANT SELECT ON TABLE '
                            '{quoted_schema}.audit_chain_heads TO ac_runtime';
                    END IF;
                END;
                $$;
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_audit_events_append_only
                BEFORE UPDATE OR DELETE ON {quoted_schema}.audit_events
                FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.reject_audit_evidence_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_audit_chain_heads_no_delete
                BEFORE DELETE ON {quoted_schema}.audit_chain_heads
                FOR EACH ROW EXECUTE FUNCTION {quoted_schema}.reject_audit_evidence_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_audit_events_no_truncate
                BEFORE TRUNCATE ON {quoted_schema}.audit_events
                FOR EACH STATEMENT EXECUTE FUNCTION {quoted_schema}.reject_audit_evidence_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_audit_chain_heads_no_truncate
                BEFORE TRUNCATE ON {quoted_schema}.audit_chain_heads
                FOR EACH STATEMENT EXECUTE FUNCTION {quoted_schema}.reject_audit_evidence_mutation()
                """
            )
        )


def downgrade() -> None:
    raise RuntimeError("operations and audit migrations are forward-only")
