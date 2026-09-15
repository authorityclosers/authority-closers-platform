"""Append-only source-owned retained C5 recovery proof and report versions.

Recovery content follows the recording retention/erasure boundary.  The
version identity, source hashes and lineage stay available for audit while
report/proof/input content is cleared by the recording erasure operation.

Revision ID: 20260915_0043
Revises: 20260915_0042
"""

import sqlalchemy as sa
from alembic import op

revision = "20260915_0043"
down_revision = "20260915_0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_retained_c5_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("c2_checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("c2_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("c3_checkpoint_id", sa.Uuid(), nullable=False),
        sa.Column("c3_manifest_sha256", sa.String(64), nullable=False),
        sa.Column("c4_checkpoint_ids", sa.JSON(), nullable=False),
        sa.Column("c4_manifest_sha256s", sa.JSON(), nullable=False),
        sa.Column("c5_input_sha256", sa.String(64), nullable=False),
        sa.Column("c5_input", sa.JSON(), nullable=True),
        sa.Column("original_quote", sa.JSON(), nullable=True),
        sa.Column("original_attempt", sa.JSON(), nullable=True),
        sa.Column("original_receipt", sa.JSON(), nullable=True),
        sa.Column("original_raw_sha256", sa.String(64), nullable=False),
        sa.Column("raw_blob_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("failure_code", sa.String(128), nullable=True),
        sa.Column("correction", sa.JSON(), nullable=True),
        sa.Column("correction_payload_sha256", sa.String(64), nullable=True),
        sa.Column(
            "review_origin",
            sa.String(64),
            nullable=False,
            server_default="Codex automated proposal",
        ),
        sa.Column("human_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dipak_adjudicated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("official_score", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("proof", sa.JSON(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_retained_c5_versions")),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name=op.f("fk_conversation_retained_c5_versions_tenant_id_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["recording_id", "tenant_id", "person_id"],
            [
                "conversation_recordings.id",
                "conversation_recordings.tenant_id",
                "conversation_recordings.person_id",
            ],
            name=op.f("fk_conversation_retained_c5_versions_recording_id_conversation_recordings"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "person_id"],
            ["conversation_runs.id", "conversation_runs.tenant_id", "conversation_runs.person_id"],
            name=op.f("fk_conversation_retained_c5_versions_run_id_conversation_runs"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["conversation_inference_tasks.run_id"],
            name=op.f("fk_conversation_retained_c5_versions_task_id_conversation_inference_tasks"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_conversation_retained_c5_versions_job_id_jobs")
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["conversation_quotes.id"],
            name=op.f("fk_conversation_retained_c5_versions_quote_id_conversation_quotes"),
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["conversation_permissions.id"],
            name=op.f("fk_conversation_retained_c5_versions_permission_id_conversation_permissions"),
        ),
        sa.UniqueConstraint(
            "run_id", "version", name=op.f("uq_conversation_retained_c5_versions_run_id")
        ),
        sa.UniqueConstraint(
            "run_id",
            "fingerprint",
            name=op.f("uq_conversation_retained_c5_versions_run_id_fingerprint"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_conversation_retained_c5_versions_positive_version")
        ),
        sa.CheckConstraint(
            "generation >= 1", name=op.f("ck_conversation_retained_c5_versions_positive_generation")
        ),
        sa.CheckConstraint(
            "validation_state IN ('needs_correction','revalidated','corrected')",
            name=op.f("ck_conversation_retained_c5_versions_validation_state"),
        ),
        sa.CheckConstraint(
            "review_origin = 'Codex automated proposal'",
            name=op.f("ck_conversation_retained_c5_versions_review_origin"),
        ),
        sa.CheckConstraint(
            "human_approved = false",
            name=op.f("ck_conversation_retained_c5_versions_never_human_approved"),
        ),
        sa.CheckConstraint(
            "dipak_adjudicated = false",
            name=op.f("ck_conversation_retained_c5_versions_never_dipak_adjudicated"),
        ),
        sa.CheckConstraint(
            "official_score = false",
            name=op.f("ck_conversation_retained_c5_versions_never_official_score"),
        ),
        sa.CheckConstraint(
            "(erased_at IS NOT NULL) OR "
            "(validation_state = 'needs_correction' AND payload IS NULL) OR "
            "(validation_state IN ('revalidated','corrected') AND payload IS NOT NULL)",
            name=op.f("ck_conversation_retained_c5_versions_payload_matches_state"),
        ),
        sa.Index(
            "ix_conversation_retained_c5_versions_recording",
            "recording_id",
            "created_at",
        ),
    )
    op.execute(
        sa.text(
            """
CREATE FUNCTION preserve_conversation_retained_c5_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'retained C5 recovery history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['c5_input','original_quote','original_attempt',
        'original_receipt','correction','proof','payload','erased_at']) IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['c5_input','original_quote','original_attempt',
        'original_receipt','correction','proof','payload','erased_at'])
       OR OLD.erased_at IS NOT NULL OR NEW.erased_at IS NULL
       OR (NEW.c5_input IS NOT NULL AND NEW.c5_input::jsonb <> 'null'::jsonb)
       OR (NEW.original_quote IS NOT NULL AND NEW.original_quote::jsonb <> 'null'::jsonb)
       OR (NEW.original_attempt IS NOT NULL AND NEW.original_attempt::jsonb <> 'null'::jsonb)
       OR (NEW.original_receipt IS NOT NULL AND NEW.original_receipt::jsonb <> 'null'::jsonb)
       OR (NEW.correction IS NOT NULL AND NEW.correction::jsonb <> 'null'::jsonb)
       OR (NEW.proof IS NOT NULL AND NEW.proof::jsonb <> 'null'::jsonb)
       OR (NEW.payload IS NOT NULL AND NEW.payload::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'retained C5 recovery history only permits content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_retained_c5_versions_immutable
BEFORE UPDATE OR DELETE ON conversation_retained_c5_versions
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_retained_c5_version();
"""
        )
    )


def downgrade() -> None:
    raise RuntimeError("Retained C5 recovery history is append-only and forward-only.")
