"""Private Sales Xray recording, checkpoints, review and ledger persistence.

DDL is frozen here, independent of runtime model imports. Content rows are
separately erasable; command receipts retain append-only audit references.
"""

import sqlalchemy as sa
from alembic import op

revision = "20260913_0030"
down_revision = "20260910_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("""
CREATE TABLE conversation_budget_accounts (
	scope_id UUID NOT NULL,
	snapshot JSON NOT NULL,
	revision INTEGER NOT NULL,
	CONSTRAINT pk_conversation_budget_accounts
        PRIMARY KEY (scope_id),
	CONSTRAINT ck_conversation_budget_accounts_positive_revision
        CHECK (revision >= 1)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_review_cursors (
	tenant_id UUID NOT NULL,
	feed_id VARCHAR(128) NOT NULL,
	sequence INTEGER NOT NULL,
	event_hash VARCHAR(64) NOT NULL,
	CONSTRAINT pk_conversation_review_cursors
        PRIMARY KEY (tenant_id, feed_id),
	CONSTRAINT ck_conversation_review_cursors_sequence_nonnegative
        CHECK (sequence >= 0),
	CONSTRAINT fk_conversation_review_cursors_tenant_id_tenants
        FOREIGN KEY(tenant_id)
        REFERENCES tenants (id)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_minute_accounts (
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	snapshot JSON NOT NULL,
	revision INTEGER NOT NULL,
	CONSTRAINT pk_conversation_minute_accounts
        PRIMARY KEY (tenant_id, person_id),
	CONSTRAINT fk_conversation_minute_accounts_tenant_id_memberships
        FOREIGN KEY(tenant_id, person_id)
        REFERENCES memberships (tenant_id, person_id),
	CONSTRAINT ck_conversation_minute_accounts_positive_revision
        CHECK (revision >= 1)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_permissions (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	provider VARCHAR(32) NOT NULL,
	permission_reference VARCHAR(256) NOT NULL,
	retention_reference VARCHAR(256) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
	retention_until TIMESTAMP WITH TIME ZONE NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_permissions
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_permissions_tenant_id_memberships
        FOREIGN KEY(tenant_id, person_id)
        REFERENCES memberships (tenant_id, person_id),
	CONSTRAINT uq_conversation_permissions_id
        UNIQUE (id, tenant_id, person_id),
	CONSTRAINT ck_conversation_permissions_local_provider_only
        CHECK (provider = 'local'),
	CONSTRAINT ck_conversation_permissions_bounded_retention
        CHECK (retention_until > created_at)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_recordings (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	permission_id UUID NOT NULL,
	request_key VARCHAR(128) NOT NULL,
	intent_sha256 VARCHAR(64) NOT NULL,
	source_sha256 VARCHAR(64) NOT NULL,
	source_bytes INTEGER NOT NULL,
	content_type VARCHAR(32) NOT NULL,
	source_revision INTEGER NOT NULL,
	generation INTEGER NOT NULL,
	state VARCHAR(24) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	deleted_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_recordings
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_recordings_tenant_id_memberships
        FOREIGN KEY(tenant_id, person_id)
        REFERENCES memberships (tenant_id, person_id),
	CONSTRAINT uq_conversation_recordings_id
        UNIQUE (id, tenant_id, person_id),
	CONSTRAINT uq_conversation_recordings_tenant_id
        UNIQUE (tenant_id, person_id, request_key),
	CONSTRAINT fk_conversation_recordings_permission_id_conversation_p_468e
        FOREIGN KEY(permission_id, tenant_id, person_id)
        REFERENCES conversation_permissions (id, tenant_id, person_id),
	CONSTRAINT ck_conversation_recordings_bounded_source
        CHECK (source_bytes > 0 AND source_bytes <= 134217728),
	CONSTRAINT ck_conversation_recordings_state
        CHECK (state IN ('awaiting_upload','ready','deleting','deleted')),
	CONSTRAINT ck_conversation_recordings_positive_revision
        CHECK (source_revision >= 1 AND generation >= 1)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_checkpoints (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	cache_key VARCHAR(64) NOT NULL,
	manifest_sha256 VARCHAR(64) NOT NULL,
	payload_sha256 VARCHAR(64) NOT NULL,
	stage VARCHAR(2) NOT NULL,
	feature_blob_id UUID,
	manifest JSON,
	payload JSON,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	erased_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_checkpoints
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_checkpoints_recording_id_conversation_r_c343
        FOREIGN KEY(recording_id, tenant_id, person_id)
        REFERENCES conversation_recordings (id, tenant_id, person_id),
	CONSTRAINT uq_conversation_checkpoints_recording_id
        UNIQUE (recording_id, cache_key),
	CONSTRAINT ck_conversation_checkpoints_stage
        CHECK (stage IN ('C0','C1','C2','C3','C4','C5','C6'))
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_commands (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	key VARCHAR(128) NOT NULL,
	action VARCHAR(64) NOT NULL,
	intent_sha256 VARCHAR(64) NOT NULL,
	result_id UUID,
	audit_event_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	CONSTRAINT pk_conversation_commands
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_commands_tenant_id_memberships
        FOREIGN KEY(tenant_id, person_id)
        REFERENCES memberships (tenant_id, person_id),
	CONSTRAINT uq_conversation_commands_tenant_id
        UNIQUE (tenant_id, person_id, key),
	CONSTRAINT fk_conversation_commands_audit_event_id_audit_events
        FOREIGN KEY(audit_event_id)
        REFERENCES audit_events (id)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_quotes (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	budget_scope_id UUID NOT NULL,
	quote JSON NOT NULL,
	execution_permission JSON NOT NULL,
	revoked_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_quotes
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_quotes_recording_id_conversation_recordings
        FOREIGN KEY(recording_id, tenant_id, person_id)
        REFERENCES conversation_recordings (id, tenant_id, person_id),
	CONSTRAINT fk_conversation_quotes_budget_scope_id_conversation_bud_7d0d
        FOREIGN KEY(budget_scope_id)
        REFERENCES conversation_budget_accounts (scope_id)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_runs (
	id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	recording_id UUID NOT NULL,
	request_key VARCHAR(128) NOT NULL,
	intent_sha256 VARCHAR(64) NOT NULL,
	recipe_revision VARCHAR(128) NOT NULL,
	generation INTEGER NOT NULL,
	state VARCHAR(24) NOT NULL,
	job_id UUID NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	completed_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_runs
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_runs_recording_id_conversation_recordings
        FOREIGN KEY(recording_id, tenant_id, person_id)
        REFERENCES conversation_recordings (id, tenant_id, person_id),
	CONSTRAINT uq_conversation_runs_id
        UNIQUE (id, tenant_id, person_id),
	CONSTRAINT uq_conversation_runs_tenant_id
        UNIQUE (tenant_id, person_id, request_key),
	CONSTRAINT ck_conversation_runs_state
        CHECK (state IN ('queued','running','completed','cancelled','failed')),
	CONSTRAINT ck_conversation_runs_positive_generation
        CHECK (generation >= 1),
	CONSTRAINT fk_conversation_runs_job_id_jobs
        FOREIGN KEY(job_id)
        REFERENCES jobs (id)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE TABLE conversation_reviews (
	id UUID NOT NULL,
	run_id UUID NOT NULL,
	tenant_id UUID NOT NULL,
	person_id UUID NOT NULL,
	reviewer_id UUID NOT NULL,
	lane VARCHAR(16) NOT NULL,
	proposal_hash VARCHAR(64) NOT NULL,
	proposal JSON,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	erased_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_conversation_reviews
        PRIMARY KEY (id),
	CONSTRAINT fk_conversation_reviews_run_id_conversation_runs
        FOREIGN KEY(run_id, tenant_id, person_id)
        REFERENCES conversation_runs (id, tenant_id, person_id),
	CONSTRAINT uq_conversation_reviews_tenant_id
        UNIQUE (tenant_id, proposal_hash),
	CONSTRAINT ck_conversation_reviews_lane
        CHECK (lane IN ('sales','signal')),
	CONSTRAINT fk_conversation_reviews_reviewer_id_persons
        FOREIGN KEY(reviewer_id)
        REFERENCES persons (id)
)
    """)
    )
    op.execute(
        sa.text("""
CREATE FUNCTION prevent_conversation_command_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'conversation commands are append-only'; END; $$;
CREATE TRIGGER conversation_commands_append_only BEFORE UPDATE OR DELETE ON conversation_commands
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
    """)
    )

    op.execute(
        sa.text("""
CREATE TABLE conversation_quote_acceptances (
    quote_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    person_id UUID NOT NULL,
    session_id UUID NOT NULL,
    quote_fingerprint VARCHAR(64) NOT NULL,
    privacy_revision VARCHAR(128) NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT pk_conversation_quote_acceptances
        PRIMARY KEY (quote_id),
    CONSTRAINT fk_conversation_quote_acceptances_quote_id_conversation_quotes

        FOREIGN KEY (quote_id)
        REFERENCES conversation_quotes(id),
    CONSTRAINT fk_conversation_quote_acceptances_tenant_id_memberships

        FOREIGN KEY (tenant_id, person_id)
        REFERENCES memberships(tenant_id, person_id),
    CONSTRAINT fk_conversation_quote_acceptances_session_id_sessions

        FOREIGN KEY (session_id)
        REFERENCES sessions(id)
);
CREATE TRIGGER conversation_quote_acceptances_append_only
BEFORE UPDATE OR DELETE ON conversation_quote_acceptances
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
CREATE FUNCTION preserve_conversation_quote() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'conversation quote history is immutable'; END IF;
    IF (to_jsonb(OLD) - 'revoked_at') IS DISTINCT FROM (to_jsonb(NEW) - 'revoked_at')
       OR (OLD.revoked_at IS NOT NULL AND OLD.revoked_at IS DISTINCT FROM NEW.revoked_at)
    THEN RAISE EXCEPTION 'conversation quote history is immutable'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_quotes_immutable BEFORE UPDATE OR DELETE ON conversation_quotes
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_quote();
CREATE FUNCTION preserve_conversation_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'checkpoint history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['payload','manifest','erased_at']) IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['payload','manifest','erased_at'])
       OR OLD.erased_at IS NOT NULL OR NEW.erased_at IS NULL
       OR (NEW.payload IS NOT NULL AND NEW.payload::jsonb <> 'null'::jsonb)
       OR (NEW.manifest IS NOT NULL AND NEW.manifest::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'checkpoint history only permits content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_checkpoints_immutable
BEFORE UPDATE OR DELETE ON conversation_checkpoints
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_checkpoint();
    """)
    )

    op.create_table(
        "conversation_provider_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_conversation_provider_configurations"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_conversation_provider_configurations_tenant_id_memberships",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_conversation_provider_configurations_session_id_sessions",
        ),
        sa.UniqueConstraint(
            "tenant_id", "revision", name="uq_conversation_provider_configurations_tenant_id"
        ),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_conversation_provider_configurations_positive_revision")
        ),
    )
    op.execute(
        sa.text("""
CREATE TRIGGER conversation_provider_configurations_append_only
BEFORE UPDATE OR DELETE ON conversation_provider_configurations
FOR EACH ROW EXECUTE FUNCTION prevent_conversation_command_mutation();
""")
    )

    op.execute(
        sa.text("""
CREATE TABLE conversation_report_drafts (
    id UUID NOT NULL, tenant_id UUID NOT NULL, person_id UUID NOT NULL,
    recording_id UUID NOT NULL, run_id UUID NOT NULL, source_revision INTEGER NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL, report_sha256 VARCHAR(64) NOT NULL,
    transcript_sha256 VARCHAR(64) NOT NULL, profile_sha256 VARCHAR(64) NOT NULL,
    evidence_receipt_sha256 VARCHAR(64) NOT NULL, payload JSON, transcript JSON,
    evidence_receipt JSON, created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    erased_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_conversation_report_drafts PRIMARY KEY(id),
    CONSTRAINT fk_conversation_report_drafts_recording_id_conversation_62f8
        FOREIGN KEY(recording_id, tenant_id, person_id)
        REFERENCES conversation_recordings(id, tenant_id, person_id),
    CONSTRAINT fk_conversation_report_drafts_run_id_conversation_runs
        FOREIGN KEY(run_id, tenant_id, person_id)
        REFERENCES conversation_runs(id, tenant_id, person_id),
    CONSTRAINT uq_conversation_report_drafts_run_id UNIQUE(run_id, report_sha256),
    CONSTRAINT ck_conversation_report_drafts_positive_source_revision CHECK(source_revision >= 1)
);
CREATE FUNCTION preserve_conversation_report_draft() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'report draft history is immutable'; END IF;
    IF (to_jsonb(OLD) - ARRAY['payload','transcript','evidence_receipt','erased_at'])
       IS DISTINCT FROM
       (to_jsonb(NEW) - ARRAY['payload','transcript','evidence_receipt','erased_at'])
       OR OLD.erased_at IS NOT NULL OR NEW.erased_at IS NULL
       OR (NEW.payload IS NOT NULL AND NEW.payload::jsonb <> 'null'::jsonb)
       OR (NEW.transcript IS NOT NULL AND NEW.transcript::jsonb <> 'null'::jsonb)
       OR (NEW.evidence_receipt IS NOT NULL AND NEW.evidence_receipt::jsonb <> 'null'::jsonb)
    THEN RAISE EXCEPTION 'report draft history only permits content erasure'; END IF;
    RETURN NEW;
END; $$;
CREATE TRIGGER conversation_report_drafts_immutable
BEFORE UPDATE OR DELETE ON conversation_report_drafts
FOR EACH ROW EXECUTE FUNCTION preserve_conversation_report_draft();
""")
    )


def downgrade() -> None:
    raise RuntimeError("Conversation audit history is forward-only; use the verified restore path")
