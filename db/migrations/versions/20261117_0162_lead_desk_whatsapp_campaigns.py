"""WhatsApp marketing in the Sales Xray CRM: a file library, drip sequences, broadcasts and
their numbers (owner, 17 Nov 2026: "all of these four, get them all live").

- ``lead_desk_whatsapp_media``: a workspace's files for WhatsApp (a PDF brochure, a picture,
  a short video), uploaded once. The file sits in the environment's private Sales X-Ray
  store; this row keeps its name, type, size, SHA-256 and the id Meta gave it per number
  (Meta keeps an upload for 30 days, so it is sent again after that).
- ``lead_desk_whatsapp_campaigns``: a broadcast (one approved template to a chosen list, at
  a set time, at a set pace) or a sequence (steps on a timer after a lead arrives or enters
  a stage). Live, paused or ended.
- ``lead_desk_whatsapp_campaign_leads``: who a campaign reaches, one row per lead, with the
  step they are on, when the next one is due, why they stopped or were skipped, and the
  proof of their yes to WhatsApp as it stood when they were added.
- ``lead_desk_whatsapp_campaign_messages``: which campaign step sent which message (for the
  campaign's sent, delivered, read, replied and won numbers).
- ``lead_desk_whatsapp_messages.auto`` also allows 'drip' and 'broadcast'. Nothing else of
  0105's tables changes (no column, index or key points at them).

Rollback: possible only while the four tables are empty and no message is a drip or a
broadcast; once any exists, that history requires forward recovery.

Chain: after 20261117_0161 (the bell's "New lead").
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0162"
down_revision = "20261117_0161"
branch_labels = None
depends_on = None

TABLES = (
    "lead_desk_whatsapp_media",
    "lead_desk_whatsapp_campaigns",
    "lead_desk_whatsapp_campaign_leads",
    "lead_desk_whatsapp_campaign_messages",
)


def upgrade() -> None:
    op.create_table(
        "lead_desk_whatsapp_media",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(120), nullable=False),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("meta_ids", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_whatsapp_media_tenant"
        ),
        sa.CheckConstraint("kind IN ('document', 'image', 'video')", name="kind"),
        sa.CheckConstraint("size_bytes > 0", name="size"),
        sa.CheckConstraint("length(trim(label)) > 0", name="label"),
    )
    op.create_index(
        "ix_lead_desk_whatsapp_media_tenant",
        "lead_desk_whatsapp_media",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "lead_desk_whatsapp_campaigns",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("per_minute", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_whatsapp_campaign_tenant"
        ),
        sa.CheckConstraint("kind IN ('broadcast', 'sequence')", name="kind"),
        sa.CheckConstraint("status IN ('live', 'paused', 'ended')", name="status"),
        sa.CheckConstraint("(status = 'ended') = (ended_at IS NOT NULL)", name="ended"),
        sa.CheckConstraint("per_minute BETWEEN 1 AND 600", name="pace"),
        sa.CheckConstraint("length(trim(name)) > 0", name="name"),
    )
    op.create_index(
        "ix_lead_desk_whatsapp_campaign_tenant",
        "lead_desk_whatsapp_campaigns",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "uq_lead_desk_whatsapp_campaign_command",
        "lead_desk_whatsapp_campaigns",
        ["tenant_id", "command_id"],
        unique=True,
    )
    op.create_table(
        "lead_desk_whatsapp_campaign_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stage_at_start", sa.String(16), nullable=True),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("proof", sa.JSON(), nullable=True),
        sa.Column("last_message_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["lead_desk_whatsapp_campaigns.id"],
            name="fk_lead_desk_whatsapp_campaign_lead_campaign",
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'done', 'stopped', 'skipped', 'failed')", name="status"
        ),
        sa.CheckConstraint("(status = 'waiting') = (next_at IS NOT NULL)", name="due"),
        sa.CheckConstraint("step >= 0", name="step"),
    )
    op.create_index(
        "uq_lead_desk_whatsapp_campaign_lead",
        "lead_desk_whatsapp_campaign_leads",
        ["campaign_id", "lead_id"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_whatsapp_campaign_lead_due",
        "lead_desk_whatsapp_campaign_leads",
        ["next_at"],
        postgresql_where=sa.text("status = 'waiting'"),
    )
    op.create_table(
        "lead_desk_whatsapp_campaign_messages",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("message_id"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["lead_desk_whatsapp_campaigns.id"],
            name="fk_lead_desk_whatsapp_campaign_message_campaign",
        ),
        sa.CheckConstraint("step >= 0", name="step"),
    )
    op.create_index(
        "ix_lead_desk_whatsapp_campaign_message_campaign",
        "lead_desk_whatsapp_campaign_messages",
        ["campaign_id", "step"],
    )
    op.drop_constraint(
        op.f("ck_lead_desk_whatsapp_messages_auto"), "lead_desk_whatsapp_messages", type_="check"
    )
    op.create_check_constraint(
        "auto",
        "lead_desk_whatsapp_messages",
        "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'ai_reply', 'drip', 'broadcast')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_whatsapp_media, lead_desk_whatsapp_campaigns,"
            " lead_desk_whatsapp_campaign_leads, lead_desk_whatsapp_campaign_messages,"
            " lead_desk_whatsapp_messages IN ACCESS EXCLUSIVE MODE"
        )
    )
    bind = op.get_bind()
    for table in TABLES:
        key = "message_id" if table.endswith("_messages") else "id"
        rows = sa.table(table, sa.column(key))
        if bind.scalar(sa.select(sa.exists().where(rows.c[key].is_not(None)))):
            raise RuntimeError("WhatsApp campaigns: that history requires forward recovery.")
    messages = sa.table("lead_desk_whatsapp_messages", sa.column("auto"))
    if bind.scalar(sa.select(sa.exists().where(messages.c.auto.in_(("drip", "broadcast"))))):
        raise RuntimeError("WhatsApp campaigns: that history requires forward recovery.")
    op.drop_constraint(
        op.f("ck_lead_desk_whatsapp_messages_auto"), "lead_desk_whatsapp_messages", type_="check"
    )
    op.create_check_constraint(
        "auto",
        "lead_desk_whatsapp_messages",
        "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'ai_reply')",
    )
    op.drop_index(
        "ix_lead_desk_whatsapp_campaign_message_campaign",
        table_name="lead_desk_whatsapp_campaign_messages",
    )
    op.drop_table("lead_desk_whatsapp_campaign_messages")
    op.drop_index(
        "ix_lead_desk_whatsapp_campaign_lead_due", table_name="lead_desk_whatsapp_campaign_leads"
    )
    op.drop_index(
        "uq_lead_desk_whatsapp_campaign_lead", table_name="lead_desk_whatsapp_campaign_leads"
    )
    op.drop_table("lead_desk_whatsapp_campaign_leads")
    op.drop_index(
        "uq_lead_desk_whatsapp_campaign_command", table_name="lead_desk_whatsapp_campaigns"
    )
    op.drop_index(
        "ix_lead_desk_whatsapp_campaign_tenant", table_name="lead_desk_whatsapp_campaigns"
    )
    op.drop_table("lead_desk_whatsapp_campaigns")
    op.drop_index("ix_lead_desk_whatsapp_media_tenant", table_name="lead_desk_whatsapp_media")
    op.drop_table("lead_desk_whatsapp_media")
