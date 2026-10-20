"""Lead stages per business, and lead stages to every ad platform (20 Oct 2026).

Every business tracks its leads its own way. An organisation now keeps its own list of
lead stages, from an industry profile or its own words, and Sales Xray tells each ad
platform the organisation connects (Meta first) which stage each lead reached.

- ``lead_desk_journey_versions``: one row per saved stage list, never changed after;
  the newest is the list in use. Stages are data (label, desk kind, meaning); nothing
  is named after a customer.
- ``lead_desk_leads.step``: the business's own stage a seller picked for the lead
  (null: the business's stage for the lead's desk stage).
- ``lead_desk_events`` gains the kind ``stage``: a lead moved to a stage without a
  call (for example "Site visit done").
- ``lead_desk_conversions`` and ``lead_desk_conversion_attempts``: the ad-platform
  outbox, one frozen event per lead, platform, destination and event name, and one
  append-only row per send. The Meta-only tables from 0104 stay as they are, as
  history; the sender copies an organisation's Meta rows over in code.

Rollback: allowed while no stage list, no ``stage`` event, no lead with a step and no
outbox row exists; otherwise that history requires forward recovery.

Chain: after 20261019_0110 (AI replies' Admin settings).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0111"
down_revision = "20261019_0110"
branch_labels = None
depends_on = None

PROVIDERS = "provider IN ('meta', 'google_ads', 'linkedin', 'tiktok', 'microsoft_ads')"


def _stored_any(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL's stored text for ``column IN (values)`` on a varchar column."""
    items = ", ".join(f"('{value}'::character varying)::text" for value in values)
    return f"({column})::text = ANY (ARRAY[{items}])"


def upgrade() -> None:
    op.create_table(
        "lead_desk_journey_versions",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("industry", sa.String(40), nullable=True),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("note", sa.String(200), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "version"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_journey_version_tenant"
        ),
        sa.CheckConstraint("version >= 1", name="lead_desk_journey_version_number"),
    )
    op.add_column("lead_desk_leads", sa.Column("step", sa.String(40), nullable=True))
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        "kind IN ('captured', 'repeat', 'assigned', 'reassigned', 'call', 'result', "
        "'note', 'edited', 'message', 'scheduled', 'stage')",
    )
    op.create_table(
        "lead_desk_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("destination", sa.String(64), nullable=False),
        sa.Column("stage_key", sa.String(40), nullable=False),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("test", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_conversion_tenant"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'rejected', 'dead_letter', 'dropped')",
            name="lead_desk_conversion_status",
        ),
        sa.CheckConstraint(PROVIDERS, name="lead_desk_conversion_provider"),
        sa.CheckConstraint(
            "length(trim(destination)) > 0", name="lead_desk_conversion_destination"
        ),
        sa.CheckConstraint("length(trim(event_name)) > 0", name="lead_desk_conversion_event_name"),
        sa.CheckConstraint(
            "(payload IS NULL) = (erased_at IS NOT NULL)", name="lead_desk_conversion_erasure"
        ),
        sa.CheckConstraint(
            "(status = 'delivered') = (delivered_at IS NOT NULL)",
            name="lead_desk_conversion_delivered",
        ),
        sa.CheckConstraint("attempts >= 0", name="lead_desk_conversion_attempts"),
        sa.CheckConstraint("length(payload_sha256) = 64", name="lead_desk_conversion_digest"),
        sa.CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="lead_desk_conversion_http_status",
        ),
    )
    # One event per lead, platform, destination and event name: a platform counts a
    # stage once per lead.
    op.create_index(
        "uq_lead_desk_conversion_event",
        "lead_desk_conversions",
        ["tenant_id", "provider", "destination", "lead_id", "event_name"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_conversion_due",
        "lead_desk_conversions",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_lead_desk_conversion_recent",
        "lead_desk_conversions",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "lead_desk_conversion_attempts",
        sa.Column("conversion_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("trace_id", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("conversion_id", "attempt"),
        sa.ForeignKeyConstraint(
            ["conversion_id"],
            ["lead_desk_conversions.id"],
            name="fk_lead_desk_conversion_attempt_conversion",
        ),
        sa.CheckConstraint("attempt >= 1", name="lead_desk_conversion_attempt_number"),
        sa.CheckConstraint(
            "duration_ms >= 0 AND finished_at >= started_at",
            name="lead_desk_conversion_attempt_timing",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="lead_desk_conversion_attempt_http_status",
        ),
        sa.CheckConstraint(
            "http_status IS NOT NULL OR error_code IS NOT NULL",
            name="lead_desk_conversion_attempt_outcome",
        ),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_leads, lead_desk_events, lead_desk_journey_versions,"
            " lead_desk_conversion_attempts, lead_desk_conversions IN ACCESS EXCLUSIVE MODE"
        )
    )
    versions = sa.table("lead_desk_journey_versions", sa.column("version"))
    events = sa.table("lead_desk_events", sa.column("kind"))
    leads = sa.table("lead_desk_leads", sa.column("step"))
    outbox = sa.table("lead_desk_conversions", sa.column("id"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(versions.c.version.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(events.c.kind == "stage")))
        or bind.scalar(sa.select(sa.exists().where(leads.c.step.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(outbox.c.id.is_not(None))))
    ):
        raise RuntimeError("Lead stage history requires forward recovery.")
    op.drop_table("lead_desk_conversion_attempts")
    op.drop_index("ix_lead_desk_conversion_recent", table_name="lead_desk_conversions")
    op.drop_index("ix_lead_desk_conversion_due", table_name="lead_desk_conversions")
    op.drop_index("uq_lead_desk_conversion_event", table_name="lead_desk_conversions")
    op.drop_table("lead_desk_conversions")
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        # Stored form, as the staging baseline holds it (see the schema gate's byte comparison).
        _stored_any(
            "kind",
            (
                "captured",
                "repeat",
                "assigned",
                "reassigned",
                "call",
                "result",
                "note",
                "edited",
                "message",
                "scheduled",
            ),
        ),
    )
    op.drop_column("lead_desk_leads", "step")
    op.drop_table("lead_desk_journey_versions")
