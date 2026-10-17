"""Lead Desk: ready messages, booked calls and phone alerts (UX study, 17 Oct 2026).

- ``lead_desk_events`` gains two kinds: ``message`` (the seller opened WhatsApp
  or SMS with a ready message; only the template's key is kept) and
  ``scheduled`` (the next call was set from the list, without a call).
- ``lead_desk_leads`` gains ``alerted_assigned_at`` and ``alerted_due_at``: the
  phone alert already sent for this assignment and for this due time.
- New ``lead_desk_devices``: a seller's phone that gets lead alerts, keyed by
  its FCM registration token (stored with its SHA-256 for lookups).

Rollback: allowed while no message or scheduled event and no device exists;
otherwise that history requires forward recovery.

Chain: after 20261016_0094 (gold reviews).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261017_0095"
down_revision = "20261016_0094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        "kind IN ('captured', 'repeat', 'assigned', 'reassigned', 'call', 'result', "
        "'note', 'edited', 'message', 'scheduled')",
    )
    op.add_column(
        "lead_desk_leads",
        sa.Column("alerted_assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lead_desk_leads",
        sa.Column("alerted_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "lead_desk_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("token", sa.String(4096), nullable=False),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("app_version", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_device_member",
        ),
        sa.UniqueConstraint("tenant_id", "token_sha256", name="uq_lead_desk_device_token"),
        sa.CheckConstraint("platform IN ('android')", name="lead_desk_device_platform"),
        sa.CheckConstraint("length(token_sha256) = 64", name="lead_desk_device_digest"),
    )
    op.create_index("ix_lead_desk_device_person", "lead_desk_devices", ["tenant_id", "person_id"])


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(sa.text("LOCK TABLE lead_desk_events, lead_desk_devices IN ACCESS EXCLUSIVE MODE"))
    events = sa.table("lead_desk_events", sa.column("kind"))
    devices = sa.table("lead_desk_devices", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(
        sa.select(sa.exists().where(events.c.kind.in_(("message", "scheduled"))))
    ) or bind.scalar(sa.select(sa.exists().where(devices.c.id.is_not(None)))):
        raise RuntimeError("Lead Desk message and alert history requires forward recovery.")
    op.drop_index("ix_lead_desk_device_person", table_name="lead_desk_devices")
    op.drop_table("lead_desk_devices")
    op.drop_column("lead_desk_leads", "alerted_due_at")
    op.drop_column("lead_desk_leads", "alerted_assigned_at")
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        # Same list as 0093, written the way PostgreSQL deparses it after pg_restore: a fresh
        # `kind IN (...)` is deparsed differently from the restored staging baseline.
        "(kind)::text = ANY (ARRAY["
        "('captured'::character varying)::text, ('repeat'::character varying)::text, "
        "('assigned'::character varying)::text, ('reassigned'::character varying)::text, "
        "('call'::character varying)::text, ('result'::character varying)::text, "
        "('note'::character varying)::text, ('edited'::character varying)::text"
        "])",
    )
