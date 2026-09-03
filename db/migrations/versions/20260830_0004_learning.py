"""Create the durable G1 learning state, evidence, and command ledger."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0004"
down_revision: str | None = "20260830_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GLOBAL_CATALOG_OWNER = "00000000000000000000000000000000"


def _catalog_columns(*, module_nullable: bool = False) -> tuple[sa.Column[object], ...]:
    return (
        sa.Column("program_id", sa.Uuid(), nullable=False),
        sa.Column("program_scope", sa.String(length=16), nullable=False),
        sa.Column("program_owner_key", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=module_nullable),
    )


def _catalog_scope_checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint("program_scope IN ('global', 'tenant')", name="program_scope_supported"),
        sa.CheckConstraint(
            f"(program_scope = 'global' AND program_owner_key = '{GLOBAL_CATALOG_OWNER}') "
            "OR (program_scope = 'tenant' AND program_owner_key = tenant_id)",
            name="program_scope_owner_match",
        ),
    )


def _activity_scope_constraints(table: str) -> tuple[sa.ForeignKeyConstraint, ...]:
    return (
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
            name=f"fk_{table}_enrollment_full_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "activity_id",
                "module_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "activities.id",
                "activities.module_id",
                "activities.program_version_id",
                "activities.program_id",
                "activities.scope",
                "activities.owner_key",
            ],
            name=f"fk_{table}_activity_full_scope",
        ),
    )


def _install_postgresql_append_only_guards() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    statements = (
        """
        CREATE FUNCTION learning_reject_fact_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'learning facts are append-only'
                USING ERRCODE = '55000';
        END;
        $$
        """,
        """
        CREATE TRIGGER trg_video_watch_intervals_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON video_watch_intervals
        FOR EACH STATEMENT EXECUTE FUNCTION learning_reject_fact_mutation()
        """,
        """
        CREATE TRIGGER trg_learning_evidence_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON learning_evidence
        FOR EACH STATEMENT EXECUTE FUNCTION learning_reject_fact_mutation()
        """,
        """
        CREATE TRIGGER trg_evidence_submissions_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON evidence_submissions
        FOR EACH STATEMENT EXECUTE FUNCTION learning_reject_fact_mutation()
        """,
        """
        CREATE TRIGGER trg_evidence_corrections_append_only
        BEFORE UPDATE OR DELETE OR TRUNCATE ON evidence_corrections
        FOR EACH STATEMENT EXECUTE FUNCTION learning_reject_fact_mutation()
        """,
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE video_watch_intervals FROM PUBLIC",
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE learning_evidence FROM PUBLIC",
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE evidence_submissions FROM PUBLIC",
        "REVOKE UPDATE, DELETE, TRUNCATE ON TABLE evidence_corrections FROM PUBLIC",
    )
    for statement in statements:
        op.execute(sa.text(statement))


def upgrade() -> None:
    op.create_table(
        "playback_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("content_version", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("session_token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("coverage_threshold", sa.Float(), server_default="0.90", nullable=False),
        sa.Column("minimum_watch_interval_seconds", sa.Float(), nullable=False),
        sa.Column("max_event_seconds", sa.Float(), nullable=False),
        sa.Column("max_heartbeat_gap_seconds", sa.Float(), nullable=False),
        sa.Column("minimum_heartbeats_for_completion", sa.Integer(), nullable=False),
        sa.Column("clock_grace_seconds", sa.Float(), nullable=False),
        sa.Column("max_rewind_seconds", sa.Float(), nullable=False),
        sa.Column(
            "status", sa.String(length=32), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_sequence", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_position_seconds", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_playback_sessions"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_playback_sessions_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_playback_sessions_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_playback_sessions_subject_program_version",
        ),
        *_activity_scope_constraints("playback_sessions"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_playback_sessions_tenant_id_id"),
        sa.UniqueConstraint("session_token_hash", name="uq_playback_sessions_token_hash"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_playback_sessions_learning_scope_id",
        ),
        sa.CheckConstraint("status IN ('active', 'closed')", name="status"),
        sa.CheckConstraint("duration_seconds > 0", name="duration_positive"),
        sa.CheckConstraint(
            "coverage_threshold > 0 AND coverage_threshold <= 1", name="coverage_threshold_range"
        ),
        sa.CheckConstraint("expires_at > started_at", name="expiry_after_start"),
        sa.CheckConstraint("revision >= 0", name="revision_nonnegative"),
        sa.CheckConstraint("last_sequence >= 0", name="last_sequence_nonnegative"),
        sa.CheckConstraint("last_position_seconds >= 0", name="last_position_nonnegative"),
        sa.CheckConstraint(
            "minimum_watch_interval_seconds >= 0",
            name="minimum_watch_interval_nonnegative",
        ),
        sa.CheckConstraint("max_event_seconds > 0", name="max_event_positive"),
        sa.CheckConstraint("max_heartbeat_gap_seconds > 0", name="max_heartbeat_gap_positive"),
        sa.CheckConstraint(
            "minimum_heartbeats_for_completion >= 2",
            name="minimum_heartbeats_at_least_two",
        ),
        sa.CheckConstraint("clock_grace_seconds >= 0", name="clock_grace_nonnegative"),
        sa.CheckConstraint("max_rewind_seconds >= 0", name="max_rewind_nonnegative"),
        sa.CheckConstraint(
            "length(session_token_hash) = 32",
            name="session_token_hash_sha256",
        ),
        sa.CheckConstraint("length(policy_version) > 0", name="policy_version_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_playback_sessions_tenant_person", "playback_sessions", ["tenant_id", "person_id"]
    )
    op.create_index(
        "ix_playback_sessions_learning_scope",
        "playback_sessions",
        ["tenant_id", "enrollment_id", "program_version_id", "activity_id"],
    )
    op.create_index(
        "ix_playback_sessions_activity_status", "playback_sessions", ["activity_id", "status"]
    )

    op.create_table(
        "video_watch_intervals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("playback_session_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="watch", nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_video_watch_intervals"),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "playback_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_video_watch_intervals_session_scope",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_video_watch_intervals_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_video_watch_intervals_learning_scope_id",
        ),
        sa.UniqueConstraint(
            "playback_session_id", "event_id", name="uq_video_watch_intervals_session_event"
        ),
        sa.UniqueConstraint(
            "playback_session_id", "sequence", name="uq_video_watch_intervals_session_sequence"
        ),
        sa.CheckConstraint("kind IN ('watch', 'seek')", name="kind"),
        sa.CheckConstraint("sequence > 0", name="sequence_positive"),
        sa.CheckConstraint("start_seconds >= 0", name="start_nonnegative"),
        sa.CheckConstraint("end_seconds >= start_seconds", name="end_after_start"),
        sa.CheckConstraint(
            "kind = 'seek' OR end_seconds > start_seconds", name="watch_interval_positive"
        ),
        sa.CheckConstraint("length(trim(event_id)) > 0", name="event_id_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_video_watch_intervals_session_start",
        "video_watch_intervals",
        ["playback_session_id", "start_seconds"],
    )
    op.create_index(
        "ix_video_watch_intervals_tenant_person",
        "video_watch_intervals",
        ["tenant_id", "person_id"],
    )

    op.create_table(
        "learning_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=32), nullable=False),
        sa.Column("activity_version", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("playback_session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_evidence"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_evidence_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_evidence_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_learning_evidence_subject_program_version",
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
                "module_id",
                "activity_id",
                "playback_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_learning_evidence_playback_session_scope",
        ),
        *_activity_scope_constraints("learning_evidence"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_learning_evidence_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_learning_evidence_request",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_learning_evidence_learning_scope_id",
        ),
        sa.CheckConstraint(
            "evidence_type IN ("
            "'video_watch', 'reflection', 'implementation', 'review', 'improvement'"
            ")",
            name="evidence_type",
        ),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        sa.CheckConstraint("length(trim(activity_version)) > 0", name="activity_version_nonblank"),
        sa.CheckConstraint("length(trim(policy_version)) > 0", name="policy_version_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_learning_evidence_tenant_person_activity",
        "learning_evidence",
        ["tenant_id", "person_id", "activity_id"],
    )
    op.create_index(
        "ix_learning_evidence_learning_scope",
        "learning_evidence",
        ["tenant_id", "enrollment_id", "activity_id"],
    )
    op.create_index(
        "ix_learning_evidence_playback_session", "learning_evidence", ["playback_session_id"]
    )

    op.create_table(
        "evidence_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_reviewer_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_submissions"),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_evidence_submissions_evidence_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submitted_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_submitter_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "assigned_reviewer_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_submissions_reviewer_membership",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evidence_submissions_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_evidence_submissions_request",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_evidence_submissions_learning_scope_id",
        ),
        sa.CheckConstraint("status IN ('recorded', 'awaiting_review')", name="status"),
        sa.CheckConstraint(
            "(status = 'recorded' AND assigned_reviewer_id IS NULL) "
            "OR (status = 'awaiting_review' AND assigned_reviewer_id IS NOT NULL)",
            name="review_assignment_matches_status",
        ),
        sa.CheckConstraint(
            "assigned_reviewer_id IS NULL OR assigned_reviewer_id <> person_id",
            name="reviewer_not_learner",
        ),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_evidence_submissions_tenant_person_activity",
        "evidence_submissions",
        ["tenant_id", "person_id", "activity_id"],
    )
    op.create_index(
        "ix_evidence_submissions_learning_scope",
        "evidence_submissions",
        ["tenant_id", "enrollment_id", "activity_id"],
    )
    op.create_index(
        "ix_evidence_submissions_reviewer",
        "evidence_submissions",
        ["tenant_id", "assigned_reviewer_id"],
    )

    op.create_table(
        "evidence_corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_person_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("correction_sequence", sa.Integer(), nullable=False),
        sa.Column("supersedes_correction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_corrections"),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "submission_id",
            ],
            [
                "evidence_submissions.tenant_id",
                "evidence_submissions.enrollment_id",
                "evidence_submissions.person_id",
                "evidence_submissions.program_version_id",
                "evidence_submissions.program_id",
                "evidence_submissions.program_scope",
                "evidence_submissions.program_owner_key",
                "evidence_submissions.module_id",
                "evidence_submissions.activity_id",
                "evidence_submissions.id",
            ],
            name="fk_evidence_corrections_submission_scope",
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
                "module_id",
                "activity_id",
                "evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_evidence_corrections_evidence_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewer_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_evidence_corrections_reviewer_membership",
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
                "module_id",
                "activity_id",
                "supersedes_correction_id",
            ],
            [
                "evidence_corrections.tenant_id",
                "evidence_corrections.enrollment_id",
                "evidence_corrections.person_id",
                "evidence_corrections.program_version_id",
                "evidence_corrections.program_id",
                "evidence_corrections.program_scope",
                "evidence_corrections.program_owner_key",
                "evidence_corrections.module_id",
                "evidence_corrections.activity_id",
                "evidence_corrections.id",
            ],
            name="fk_evidence_corrections_supersedes_scope",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_evidence_corrections_tenant_id_id"),
        sa.UniqueConstraint(
            "submission_id",
            "correction_sequence",
            name="uq_evidence_corrections_submission_sequence",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "idempotency_key",
            name="uq_evidence_corrections_request",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_evidence_corrections_learning_scope_id",
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected', 'needs_revision')", name="decision"
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="reason_nonblank"),
        sa.CheckConstraint("reviewer_person_id <> person_id", name="reviewer_not_learner"),
        sa.CheckConstraint("correction_sequence > 0", name="correction_sequence_positive"),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_evidence_corrections_submission_created",
        "evidence_corrections",
        ["submission_id", "created_at"],
    )
    op.create_index(
        "ix_evidence_corrections_tenant_person", "evidence_corrections", ["tenant_id", "person_id"]
    )

    op.create_table(
        "activity_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), server_default="available", nullable=False),
        sa.Column("activity_version", sa.String(length=128), server_default="v1", nullable=False),
        sa.Column("policy_version", sa.String(length=128), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("awaiting_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_evidence_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_progress"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_activity_progress_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_activity_progress_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_activity_progress_subject_program_version",
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
                "module_id",
                "activity_id",
                "completion_evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_activity_progress_completion_evidence_scope",
        ),
        *_activity_scope_constraints("activity_progress"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_activity_progress_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            name="uq_activity_progress_learning_scope",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_activity_progress_learning_scope_id",
        ),
        sa.CheckConstraint(
            "state IN ('locked', 'available', 'in_progress', 'awaiting_review', 'completed')",
            name="state",
        ),
        sa.CheckConstraint("revision >= 0", name="revision_nonnegative"),
        sa.CheckConstraint(
            "completed_at IS NULL OR state = 'completed'", name="completed_timestamp_consistent"
        ),
        sa.CheckConstraint(
            "state <> 'completed' OR completion_evidence_id IS NOT NULL",
            name="completed_requires_evidence",
        ),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_activity_progress_tenant_person", "activity_progress", ["tenant_id", "person_id"]
    )
    op.create_index(
        "ix_activity_progress_learning_scope",
        "activity_progress",
        ["tenant_id", "enrollment_id", "activity_id"],
    )
    op.create_index(
        "ix_activity_progress_activity_state", "activity_progress", ["activity_id", "state"]
    )

    op.create_table(
        "activity_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="saved", nullable=False),
        sa.Column("last_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("last_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "saved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_activity_drafts"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_activity_drafts_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_activity_drafts_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_activity_drafts_subject_program_version",
        ),
        *_activity_scope_constraints("activity_drafts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_activity_drafts_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            name="uq_activity_drafts_learning_scope",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "module_id",
            "activity_id",
            "id",
            name="uq_activity_drafts_learning_scope_id",
        ),
        sa.CheckConstraint("revision >= 0", name="revision_nonnegative"),
        sa.CheckConstraint("status IN ('saved')", name="status"),
        sa.CheckConstraint(
            "last_idempotency_key IS NULL OR length(trim(last_idempotency_key)) > 0",
            name="idempotency_key_nonblank",
        ),
        sa.CheckConstraint(
            "last_request_fingerprint IS NULL OR length(last_request_fingerprint) = 64",
            name="request_fingerprint_sha256",
        ),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_activity_drafts_tenant_person", "activity_drafts", ["tenant_id", "person_id"]
    )
    op.create_index(
        "ix_activity_drafts_learning_scope",
        "activity_drafts",
        ["tenant_id", "enrollment_id", "activity_id"],
    )

    op.create_table(
        "learning_progress_projections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(module_nullable=True),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("denominator", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column("projection_version", sa.String(length=128), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learning_progress_projections"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_progress_projections_membership_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_progress_projections_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_learning_progress_projections_subject_program_version",
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
            name="fk_learning_progress_projections_enrollment_full_scope",
        ),
        sa.ForeignKeyConstraint(
            ["program_version_id", "program_id", "program_scope", "program_owner_key"],
            [
                "program_versions.id",
                "program_versions.program_id",
                "program_versions.scope",
                "program_versions.owner_key",
            ],
            name="fk_learning_progress_projections_program_version_scope",
        ),
        sa.ForeignKeyConstraint(
            [
                "module_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
            ],
            [
                "modules.id",
                "modules.program_version_id",
                "modules.program_id",
                "modules.scope",
                "modules.owner_key",
            ],
            name="fk_learning_progress_projections_module_scope",
        ),
        sa.UniqueConstraint(
            "tenant_id", "id", name="uq_learning_progress_projections_tenant_id_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "enrollment_id",
            "person_id",
            "program_version_id",
            "program_id",
            "program_scope",
            "program_owner_key",
            "scope_type",
            "scope_id",
            name="uq_learning_progress_projections_scope",
        ),
        sa.CheckConstraint("scope_type IN ('module', 'course')", name="scope_type"),
        sa.CheckConstraint(
            "(scope_type = 'module' AND module_id IS NOT NULL AND scope_id = module_id) "
            "OR (scope_type = 'course' AND module_id IS NULL AND scope_id = program_id)",
            name="scope_identity_consistent",
        ),
        sa.CheckConstraint("denominator >= 0", name="denominator_nonnegative"),
        sa.CheckConstraint(
            "completed_count >= 0 AND completed_count <= denominator", name="completed_count_range"
        ),
        sa.CheckConstraint("percentage >= 0 AND percentage <= 1", name="percentage_range"),
        sa.CheckConstraint(
            "abs(percentage - CASE WHEN denominator = 0 THEN 0.0 "
            "ELSE (1.0 * completed_count / denominator) END) <= 0.000000001",
            name="percentage_deterministic",
        ),
        sa.CheckConstraint("projection_version <> ''", name="projection_version_nonblank"),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_learning_progress_projections_tenant_person",
        "learning_progress_projections",
        ["tenant_id", "person_id"],
    )

    op.create_table(
        "learning_command_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("enrollment_id", sa.Uuid(), nullable=False),
        sa.Column("program_version_id", sa.Uuid(), nullable=False),
        *_catalog_columns(),
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("result_progress_id", sa.Uuid(), nullable=True),
        sa.Column("result_draft_id", sa.Uuid(), nullable=True),
        sa.Column("result_session_id", sa.Uuid(), nullable=True),
        sa.Column("result_interval_id", sa.Uuid(), nullable=True),
        sa.Column("result_evidence_id", sa.Uuid(), nullable=True),
        sa.Column("result_submission_id", sa.Uuid(), nullable=True),
        sa.Column("result_correction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_learning_command_idempotency"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_command_idempotency_actor_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_learning_command_idempotency_subject_membership",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "enrollment_id"],
            ["enrollments.tenant_id", "enrollments.id"],
            name="fk_learning_command_idempotency_enrollment_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id", "program_version_id"],
            ["enrollments.tenant_id", "enrollments.person_id", "enrollments.program_version_id"],
            name="fk_learning_command_idempotency_subject_program_version",
        ),
        *_activity_scope_constraints("learning_command_idempotency"),
        sa.ForeignKeyConstraint(
            [
                "tenant_id",
                "enrollment_id",
                "person_id",
                "program_version_id",
                "program_id",
                "program_scope",
                "program_owner_key",
                "module_id",
                "activity_id",
                "result_progress_id",
            ],
            [
                "activity_progress.tenant_id",
                "activity_progress.enrollment_id",
                "activity_progress.person_id",
                "activity_progress.program_version_id",
                "activity_progress.program_id",
                "activity_progress.program_scope",
                "activity_progress.program_owner_key",
                "activity_progress.module_id",
                "activity_progress.activity_id",
                "activity_progress.id",
            ],
            name="fk_learning_command_idempotency_progress",
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
                "module_id",
                "activity_id",
                "result_draft_id",
            ],
            [
                "activity_drafts.tenant_id",
                "activity_drafts.enrollment_id",
                "activity_drafts.person_id",
                "activity_drafts.program_version_id",
                "activity_drafts.program_id",
                "activity_drafts.program_scope",
                "activity_drafts.program_owner_key",
                "activity_drafts.module_id",
                "activity_drafts.activity_id",
                "activity_drafts.id",
            ],
            name="fk_learning_command_idempotency_draft",
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
                "module_id",
                "activity_id",
                "result_session_id",
            ],
            [
                "playback_sessions.tenant_id",
                "playback_sessions.enrollment_id",
                "playback_sessions.person_id",
                "playback_sessions.program_version_id",
                "playback_sessions.program_id",
                "playback_sessions.program_scope",
                "playback_sessions.program_owner_key",
                "playback_sessions.module_id",
                "playback_sessions.activity_id",
                "playback_sessions.id",
            ],
            name="fk_learning_command_idempotency_session",
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
                "module_id",
                "activity_id",
                "result_interval_id",
            ],
            [
                "video_watch_intervals.tenant_id",
                "video_watch_intervals.enrollment_id",
                "video_watch_intervals.person_id",
                "video_watch_intervals.program_version_id",
                "video_watch_intervals.program_id",
                "video_watch_intervals.program_scope",
                "video_watch_intervals.program_owner_key",
                "video_watch_intervals.module_id",
                "video_watch_intervals.activity_id",
                "video_watch_intervals.id",
            ],
            name="fk_learning_command_idempotency_interval",
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
                "module_id",
                "activity_id",
                "result_evidence_id",
            ],
            [
                "learning_evidence.tenant_id",
                "learning_evidence.enrollment_id",
                "learning_evidence.person_id",
                "learning_evidence.program_version_id",
                "learning_evidence.program_id",
                "learning_evidence.program_scope",
                "learning_evidence.program_owner_key",
                "learning_evidence.module_id",
                "learning_evidence.activity_id",
                "learning_evidence.id",
            ],
            name="fk_learning_command_idempotency_evidence",
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
                "module_id",
                "activity_id",
                "result_submission_id",
            ],
            [
                "evidence_submissions.tenant_id",
                "evidence_submissions.enrollment_id",
                "evidence_submissions.person_id",
                "evidence_submissions.program_version_id",
                "evidence_submissions.program_id",
                "evidence_submissions.program_scope",
                "evidence_submissions.program_owner_key",
                "evidence_submissions.module_id",
                "evidence_submissions.activity_id",
                "evidence_submissions.id",
            ],
            name="fk_learning_command_idempotency_submission",
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
                "module_id",
                "activity_id",
                "result_correction_id",
            ],
            [
                "evidence_corrections.tenant_id",
                "evidence_corrections.enrollment_id",
                "evidence_corrections.person_id",
                "evidence_corrections.program_version_id",
                "evidence_corrections.program_id",
                "evidence_corrections.program_scope",
                "evidence_corrections.program_owner_key",
                "evidence_corrections.module_id",
                "evidence_corrections.activity_id",
                "evidence_corrections.id",
            ],
            name="fk_learning_command_idempotency_correction",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_learning_command_idempotency_tenant_id_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_person_id",
            "operation",
            "idempotency_key",
            name="uq_learning_command_idempotency_scope_key",
        ),
        sa.CheckConstraint(
            "operation IN ("
            "'activity_start', 'activity_transition', 'draft_save', 'playback_start', "
            "'playback_event', 'playback_close', 'evidence_submit', 'evidence_review'"
            ")",
            name="operation_allowed",
        ),
        sa.CheckConstraint("status IN ('pending', 'completed')", name="status"),
        sa.CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key_nonblank"),
        sa.CheckConstraint("length(request_digest) = 64", name="request_digest_sha256"),
        sa.CheckConstraint(
            "(status = 'pending' AND completed_at IS NULL) "
            "OR (status = 'completed' AND completed_at IS NOT NULL)",
            name="completion_timestamp_consistent",
        ),
        *_catalog_scope_checks(),
    )
    op.create_index(
        "ix_learning_command_idempotency_scope",
        "learning_command_idempotency",
        ["tenant_id", "person_id", "enrollment_id", "program_version_id"],
    )
    _install_postgresql_append_only_guards()


def downgrade() -> None:
    raise RuntimeError("learning migrations are forward-only")
