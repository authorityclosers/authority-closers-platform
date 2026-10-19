"""Lead stages back to Meta: Conversions API for CRM (19 Oct 2026).

An organisation that runs Meta lead ads picks one of its Meta datasets in the Sales
Xray CRM; each stage its Meta leads reach goes to that dataset, so its ads learn
which leads become customers. Settings live in the organisation's Lead Desk
settings, as data; nothing is named after a customer.

Two new tables, nothing else changes:

- ``lead_desk_meta_conversions``: one frozen event per lead, dataset and stage name,
  built from Lead Desk's own history. The payload holds Meta's lead id and hashed
  identifiers only, and is emptied after 90 days or when the event is dropped; ids,
  digests and results stay. Lead Desk's events remain the record of a lead's stage.
- ``lead_desk_meta_conversion_attempts``: one append-only row per send (the delivery
  log).

New, empty tables may be rolled back; once an event exists, that history requires
forward recovery.

Chain: after 20261019_0103 (developer platform).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0104"
down_revision = "20261019_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_meta_conversions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("event_name", sa.String(50), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("fbtrace_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_meta_conversion_tenant"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'delivered', 'rejected', 'dead_letter', 'dropped')",
            name="status",
        ),
        sa.CheckConstraint(
            "stage IN ('new', 'not_connected', 'follow_up', 'interested', 'won', 'lost')",
            name="stage",
        ),
        sa.CheckConstraint("dataset_id ~ '^[0-9]{5,20}$'", name="dataset"),
        sa.CheckConstraint("length(trim(event_name)) > 0", name="event_name"),
        sa.CheckConstraint("(payload IS NULL) = (erased_at IS NOT NULL)", name="erasure"),
        sa.CheckConstraint("(status = 'delivered') = (delivered_at IS NOT NULL)", name="delivered"),
        sa.CheckConstraint("attempts >= 0", name="attempts"),
        sa.CheckConstraint("length(payload_sha256) = 64", name="digest"),
        sa.CheckConstraint(
            "last_http_status IS NULL OR last_http_status BETWEEN 100 AND 599",
            name="http_status",
        ),
    )
    # One event per lead, dataset and stage name: Meta counts a stage once per lead.
    op.create_index(
        "uq_lead_desk_meta_conversion_stage",
        "lead_desk_meta_conversions",
        ["tenant_id", "dataset_id", "lead_id", "event_name"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_meta_conversion_due",
        "lead_desk_meta_conversions",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_lead_desk_meta_conversion_recent",
        "lead_desk_meta_conversions",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "lead_desk_meta_conversion_attempts",
        sa.Column("conversion_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("events_received", sa.Integer(), nullable=True),
        sa.Column("fbtrace_id", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("conversion_id", "attempt"),
        sa.ForeignKeyConstraint(
            ["conversion_id"],
            ["lead_desk_meta_conversions.id"],
            name="fk_lead_desk_meta_conversion_attempt_conversion",
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
            "LOCK TABLE lead_desk_meta_conversion_attempts, lead_desk_meta_conversions"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    events = sa.table("lead_desk_meta_conversions", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(events.c.id.is_not(None)))):
        raise RuntimeError("Meta conversion history requires forward recovery.")
    op.drop_table("lead_desk_meta_conversion_attempts")
    op.drop_index("ix_lead_desk_meta_conversion_recent", table_name="lead_desk_meta_conversions")
    op.drop_index("ix_lead_desk_meta_conversion_due", table_name="lead_desk_meta_conversions")
    op.drop_index("uq_lead_desk_meta_conversion_stage", table_name="lead_desk_meta_conversions")
    op.drop_table("lead_desk_meta_conversions")
