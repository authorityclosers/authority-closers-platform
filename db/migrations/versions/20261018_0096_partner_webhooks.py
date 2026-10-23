"""Partner webhooks: signed ``analysis.completed`` events with quote facts (18 Oct 2026).

Sales X-Ray sends a partner (first: Wise Life) one signed event per finished
call analysis, at the HTTPS address registered for that workspace. Four new
tables, nothing else changes:

- ``partner_webhook_endpoints``: where a workspace's events go. The URL and
  secret are never changed in place: a change disables the row and adds a new
  one (``supersedes_endpoint_id``). Secrets are not stored, only the name of
  the environment variable that holds one (``secret_ref``). At most one active
  endpoint per workspace (v1).
- ``partner_quote_facts``: one row per finished paid extraction attempt
  (complete or failed), at most two per report and profile. Erasing the call
  empties the payload and stamps ``erased_at``.
- ``partner_webhook_events``: one frozen event per endpoint and report, so a
  retry sends the same bytes. Erasing the call empties the payload.
- ``partner_webhook_attempts``: one append-only row per delivery attempt
  (status code and a content-free error code only).

New, empty tables may be rolled back; once any endpoint or quote facts row
exists, that history requires forward recovery.

Chain: after 20261017_0095 (lead desk alerts).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261018_0096"
down_revision = "20261017_0095"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "partner_webhook_endpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret_ref", sa.String(100), nullable=False),
        sa.Column("secret_ref_next", sa.String(100), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("facts_profile", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("events_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_endpoint_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partner_webhook_endpoint_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_endpoint_id"],
            ["partner_webhook_endpoints.id"],
            name="fk_partner_webhook_endpoint_supersedes",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="status"),
        sa.CheckConstraint(
            "(status = 'disabled') = (disabled_at IS NOT NULL)",
            name="disabled",
        ),
        sa.CheckConstraint(
            "url ~ '^(https://|http://(127\\.0\\.0\\.1|localhost)(:[0-9]{1,5})?(/|$))'",
            name="url",
        ),
        sa.CheckConstraint(
            "secret_ref ~ '^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$'"
            " AND (secret_ref_next IS NULL"
            " OR (secret_ref_next ~ '^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$'"
            " AND secret_ref_next <> secret_ref))",
            name="secret_ref",
        ),
        sa.CheckConstraint(
            "facts_profile IS NULL OR length(facts_profile) BETWEEN 1 AND 64",
            name="profile",
        ),
        sa.CheckConstraint(
            "length(trim(created_by)) > 0 AND length(trim(reason)) > 0",
            name="provenance",
        ),
    )
    op.create_index(
        "uq_partner_webhook_endpoint_active",
        "partner_webhook_endpoints",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_partner_webhook_endpoint_tenant",
        "partner_webhook_endpoints",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "partner_quote_facts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("report_draft_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("transcript_revision", sa.String(256), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=False),
        sa.Column("prompt_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partner_quote_facts_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["conversation_recordings.id"],
            name="fk_partner_quote_facts_recording",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["conversation_runs.id"], name="fk_partner_quote_facts_run"
        ),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_partner_quote_facts_report_draft",
        ),
        sa.UniqueConstraint(
            "report_draft_id", "profile", "attempt", name="uq_partner_quote_facts_attempt"
        ),
        sa.CheckConstraint("status IN ('complete', 'failed')", name="status"),
        sa.CheckConstraint("attempt BETWEEN 1 AND 2", name="attempt"),
        sa.CheckConstraint(
            "(payload IS NOT NULL) = (status = 'complete' AND erased_at IS NULL)",
            name="payload",
        ),
        sa.CheckConstraint(
            "(payload_sha256 IS NOT NULL) = (status = 'complete')",
            name="payload_digest",
        ),
        sa.CheckConstraint("(error_code IS NOT NULL) = (status = 'failed')", name="error"),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(prompt_sha256) = 64"
            " AND (payload_sha256 IS NULL OR length(payload_sha256) = 64)",
            name="digests",
        ),
    )
    op.create_index(
        "ix_partner_quote_facts_recording",
        "partner_quote_facts",
        ["recording_id", "created_at"],
    )
    op.create_table(
        "partner_webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("report_draft_id", sa.Uuid(), nullable=False),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("analysis_revision", sa.Integer(), nullable=False),
        sa.Column("supersedes_event_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("replayed_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["partner_webhook_endpoints.id"],
            name="fk_partner_webhook_event_endpoint",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partner_webhook_event_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["recording_id"],
            ["conversation_recordings.id"],
            name="fk_partner_webhook_event_recording",
        ),
        sa.ForeignKeyConstraint(
            ["report_draft_id"],
            ["conversation_report_drafts.id"],
            name="fk_partner_webhook_event_report_draft",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "submission_id"],
            [
                "conversation_guest_submissions.tenant_id",
                "conversation_guest_submissions.submission_id",
            ],
            name="fk_partner_webhook_event_submission",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id"],
            ["partner_webhook_events.id"],
            name="fk_partner_webhook_event_supersedes",
        ),
        sa.UniqueConstraint(
            "endpoint_id", "report_draft_id", name="uq_partner_webhook_event_draft"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'dead_letter', 'dropped')",
            name="status",
        ),
        sa.CheckConstraint("event_type IN ('analysis.completed')", name="event_type"),
        sa.CheckConstraint("(payload IS NULL) = (erased_at IS NOT NULL)", name="erasure"),
        sa.CheckConstraint(
            "erased_at IS NULL OR status IN ('delivered', 'dropped')",
            name="erased_status",
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="delivered",
        ),
        sa.CheckConstraint("analysis_revision >= 1", name="revision"),
        sa.CheckConstraint(
            "attempts >= 0 AND replayed_attempts >= 0 AND replayed_attempts <= attempts",
            name="attempts",
        ),
        sa.CheckConstraint("length(payload_sha256) = 64", name="digest"),
        sa.CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
    )
    op.create_index(
        "ix_partner_webhook_event_due",
        "partner_webhook_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_partner_webhook_event_recording",
        "partner_webhook_events",
        ["tenant_id", "recording_id", "created_at"],
    )
    op.create_table(
        "partner_webhook_attempts",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "attempt"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["partner_webhook_events.id"], name="fk_partner_webhook_attempt_event"
        ),
        sa.CheckConstraint("attempt >= 1", name="number"),
        sa.CheckConstraint("duration_ms >= 0 AND finished_at >= started_at", name="timing"),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
        sa.CheckConstraint(
            "http_status IS NOT NULL OR error_code IS NOT NULL",
            name="outcome",
        ),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE partner_webhook_attempts, partner_webhook_events, partner_quote_facts,"
            " partner_webhook_endpoints IN ACCESS EXCLUSIVE MODE"
        )
    )
    endpoints = sa.table("partner_webhook_endpoints", sa.column("id"))
    facts = sa.table("partner_quote_facts", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(endpoints.c.id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(facts.c.id.is_not(None)))
    ):
        raise RuntimeError("Partner webhook history requires forward recovery.")
    op.drop_table("partner_webhook_attempts")
    op.drop_index("ix_partner_webhook_event_recording", table_name="partner_webhook_events")
    op.drop_index("ix_partner_webhook_event_due", table_name="partner_webhook_events")
    op.drop_table("partner_webhook_events")
    op.drop_index("ix_partner_quote_facts_recording", table_name="partner_quote_facts")
    op.drop_table("partner_quote_facts")
    op.drop_index("ix_partner_webhook_endpoint_tenant", table_name="partner_webhook_endpoints")
    op.drop_index("uq_partner_webhook_endpoint_active", table_name="partner_webhook_endpoints")
    op.drop_table("partner_webhook_endpoints")
