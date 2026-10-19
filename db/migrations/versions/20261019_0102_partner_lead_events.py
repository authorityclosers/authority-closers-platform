"""Partner lead events and customer hand-overs (19 Oct 2026).

An organisation can send its leads onward, configured per organisation as data:

- its signed webhook (``partner_webhook_endpoints``, 0096; unchanged) can also
  take ``lead.created``, ``lead.stage_changed`` and ``lead.closed``;
- a hand-over recipient: when a person records a lead as won, one customer
  hand-over goes to the partner's service API (bearer key,
  ``Idempotency-Key``). Each win is its own hand-over.

Three new tables, nothing else changes:

- ``partner_handover_recipients``: where an organisation's hand-overs go, the
  name of the secret that holds the key (never the key), and the optional parts
  and form questions an AC admin approved for it. Superseded, never edited; at
  most one active per organisation.
- ``partner_lead_events``: one frozen request per recipient, Lead Desk event and
  type, so a retry sends the same bytes under the same key. A hand-over the
  partner rejects (422) keeps its key, the field paths and problems (never the
  body); a correction names it in ``correction_of``. Bodies are emptied after
  90 days or when the lead is gone; ids, digests and results stay.
- ``partner_lead_attempts``: one append-only row per delivery attempt.

New, empty tables may be rolled back; once a recipient or a lead event exists,
that history requires forward recovery.

Chain: after 20261019_0101 (Review 2.0).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0102"
down_revision = "20261019_0101"
branch_labels = None
depends_on = None

LEAD_EVENT_TYPES = "('lead.handover', 'lead.created', 'lead.stage_changed', 'lead.closed')"


def upgrade() -> None:
    op.create_table(
        "partner_handover_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret_ref", sa.String(100), nullable=False),
        sa.Column("lead_fields", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("events_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supersedes_recipient_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.String(160), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_partner_handover_recipient_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_recipient_id"],
            ["partner_handover_recipients.id"],
            name="fk_partner_handover_recipient_supersedes",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="status"),
        sa.CheckConstraint("(status = 'disabled') = (disabled_at IS NOT NULL)", name="disabled"),
        sa.CheckConstraint(
            "url ~ '^(https://|http://(127\\.0\\.0\\.1|localhost)(:[0-9]{1,5})?/)'"
            " AND url ~ '/api/v1/service/customers/handover$'",
            name="url",
        ),
        sa.CheckConstraint(
            "secret_ref ~ '^AC_PARTNER_WEBHOOK_SECRET__[A-Z0-9_]{1,64}$'", name="secret_ref"
        ),
        sa.CheckConstraint(
            "length(trim(created_by)) > 0 AND length(trim(reason)) > 0", name="provenance"
        ),
    )
    op.create_index(
        "uq_partner_handover_recipient_active",
        "partner_handover_recipients",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "partner_lead_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("endpoint_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_id", sa.Uuid(), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("handover_seq", sa.Integer(), nullable=True),
        sa.Column("correction_of", sa.Uuid(), nullable=True),
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
        sa.Column("result", sa.String(16), nullable=True),
        sa.Column("partner_ref", sa.String(64), nullable=True),
        sa.Column("rejection", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["endpoint_id"],
            ["partner_webhook_endpoints.id"],
            name="fk_partner_lead_event_endpoint",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["partner_handover_recipients.id"],
            name="fk_partner_lead_event_recipient",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_partner_lead_event_tenant"),
        sa.ForeignKeyConstraint(
            ["correction_of"], ["partner_lead_events.id"], name="fk_partner_lead_event_correction"
        ),
        sa.CheckConstraint(f"event_type IN {LEAD_EVENT_TYPES}", name="event_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'rejected', 'dead_letter', 'dropped')",
            name="status",
        ),
        sa.CheckConstraint(
            "(endpoint_id IS NULL) <> (recipient_id IS NULL)"
            " AND (recipient_id IS NOT NULL) = (event_type = 'lead.handover')",
            name="target",
        ),
        sa.CheckConstraint(
            "(event_type = 'lead.handover') = (handover_seq IS NOT NULL)"
            " AND (handover_seq IS NULL OR handover_seq >= 1)"
            " AND (correction_of IS NULL OR event_type = 'lead.handover')",
            name="handover",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('created', 'updated', 'in_review')", name="result"
        ),
        sa.CheckConstraint("(status = 'rejected') = (rejection IS NOT NULL)", name="rejection"),
        sa.CheckConstraint("(payload IS NULL) = (erased_at IS NOT NULL)", name="erasure"),
        sa.CheckConstraint(
            "erased_at IS NULL OR status IN ('delivered', 'rejected', 'dropped', 'dead_letter')",
            name="erased_status",
        ),
        sa.CheckConstraint("(status = 'delivered') = (delivered_at IS NOT NULL)", name="delivered"),
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
    # One original per webhook, Lead Desk event and type, and one per recipient
    # and Lead Desk event; corrections are extra rows.
    op.create_index(
        "uq_partner_lead_event_source",
        "partner_lead_events",
        ["endpoint_id", "source_event_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("endpoint_id IS NOT NULL"),
    )
    op.create_index(
        "uq_partner_lead_event_handover",
        "partner_lead_events",
        ["recipient_id", "source_event_id"],
        unique=True,
        postgresql_where=sa.text("recipient_id IS NOT NULL AND correction_of IS NULL"),
    )
    op.create_index(
        "ix_partner_lead_event_due",
        "partner_lead_events",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_partner_lead_event_lead",
        "partner_lead_events",
        ["tenant_id", "lead_id", "event_type", "occurred_at"],
    )
    op.create_table(
        "partner_lead_attempts",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "attempt"),
        sa.ForeignKeyConstraint(
            ["event_id"], ["partner_lead_events.id"], name="fk_partner_lead_attempt_event"
        ),
        sa.CheckConstraint("attempt >= 1", name="number"),
        sa.CheckConstraint("duration_ms >= 0 AND finished_at >= started_at", name="timing"),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599", name="http_status"
        ),
        sa.CheckConstraint("http_status IS NOT NULL OR error_code IS NOT NULL", name="outcome"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE partner_lead_attempts, partner_lead_events, partner_handover_recipients"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    events = sa.table("partner_lead_events", sa.column("id"))
    recipients = sa.table("partner_handover_recipients", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(events.c.id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(recipients.c.id.is_not(None)))
    ):
        raise RuntimeError("Partner lead event history requires forward recovery.")
    op.drop_table("partner_lead_attempts")
    op.drop_index("ix_partner_lead_event_lead", table_name="partner_lead_events")
    op.drop_index("ix_partner_lead_event_due", table_name="partner_lead_events")
    op.drop_index("uq_partner_lead_event_handover", table_name="partner_lead_events")
    op.drop_index("uq_partner_lead_event_source", table_name="partner_lead_events")
    op.drop_table("partner_lead_events")
    op.drop_index("uq_partner_handover_recipient_active", table_name="partner_handover_recipients")
    op.drop_table("partner_handover_recipients")
