"""WhatsApp in the Sales Xray CRM, and a first-response SLA (19 Oct 2026).

Each organisation connects its own WhatsApp Business number with Meta's Embedded
Signup and pays Meta directly for its messages. Settings are data per organisation;
nothing is named after a customer.

Four new tables, nothing else changes:

- ``lead_desk_whatsapp_numbers``: an organisation's connected numbers, with the
  business token and the two-step PIN Sales Xray set, both sealed to the number. At
  most one active connection per WhatsApp number.
- ``lead_desk_whatsapp_messages``: each lead's conversation, in and out, once per
  Meta message id. The text is the customer's own data and is emptied when the lead
  leaves Lead Desk.
- ``lead_desk_whatsapp_templates``: the account's message templates as Meta last
  said (approved, pending, rejected).
- ``lead_desk_sla_breaches``: a lead that went past the organisation's
  first-response target, once per arrival, and who was alerted.

New, empty tables may be rolled back; once any row exists, that history requires
forward recovery.

Chain: after 20261019_0104 (lead stages back to Meta).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0105"
down_revision = "20261019_0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_whatsapp_numbers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("waba_id", sa.String(32), nullable=False),
        sa.Column("phone_number_id", sa.String(32), nullable=False),
        sa.Column("display_number", sa.String(32), nullable=False),
        sa.Column("verified_name", sa.String(200), nullable=True),
        sa.Column("quality", sa.String(16), nullable=True),
        sa.Column("token", sa.JSON(), nullable=False),
        sa.Column("pin", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("connected_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_whatsapp_number_tenant"
        ),
        sa.CheckConstraint("status IN ('active', 'disconnected')", name="status"),
        sa.CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)", name="disconnected"
        ),
        sa.CheckConstraint(
            "waba_id ~ '^[0-9]{5,32}$' AND phone_number_id ~ '^[0-9]{5,32}$'", name="ids"
        ),
    )
    op.create_index(
        "uq_lead_desk_whatsapp_number_active",
        "lead_desk_whatsapp_numbers",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_lead_desk_whatsapp_number_tenant",
        "lead_desk_whatsapp_numbers",
        ["tenant_id", "status"],
    )
    op.create_table(
        "lead_desk_whatsapp_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("wa_id", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("wamid", sa.String(200), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.String(4096), nullable=True),
        sa.Column("template_name", sa.String(512), nullable=True),
        sa.Column("template_language", sa.String(16), nullable=True),
        sa.Column("media", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_title", sa.String(200), nullable=True),
        sa.Column("sent_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("auto", sa.String(16), nullable=True),
        sa.Column("meta_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["lead_desk_whatsapp_numbers.id"],
            name="fk_lead_desk_whatsapp_message_number",
        ),
        sa.CheckConstraint("direction IN ('in', 'out')", name="direction"),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name="status",
        ),
        sa.CheckConstraint("(direction = 'in') = (status = 'received')", name="received"),
        sa.CheckConstraint(
            "kind IN ('text', 'template', 'image', 'audio', 'video', 'document', 'sticker',"
            " 'location', 'contacts', 'interactive', 'button', 'reaction', 'unsupported')",
            name="kind",
        ),
        sa.CheckConstraint("auto IS NULL OR auto IN ('first_reply', 'out_of_hours')", name="auto"),
        sa.CheckConstraint("wa_id ~ '^[0-9]{6,20}$'", name="wa_id"),
    )
    op.create_index(
        "uq_lead_desk_whatsapp_message_wamid",
        "lead_desk_whatsapp_messages",
        ["wamid"],
        unique=True,
        postgresql_where=sa.text("wamid IS NOT NULL"),
    )
    op.create_index(
        "ix_lead_desk_whatsapp_message_lead",
        "lead_desk_whatsapp_messages",
        ["tenant_id", "lead_id", "created_at"],
    )
    op.create_index(
        "ix_lead_desk_whatsapp_message_chat",
        "lead_desk_whatsapp_messages",
        ["tenant_id", "number_id", "wa_id", "created_at"],
    )
    op.create_table(
        "lead_desk_whatsapp_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("number_id", sa.Uuid(), nullable=False),
        sa.Column("waba_id", sa.String(32), nullable=False),
        sa.Column("meta_id", sa.String(32), nullable=True),
        sa.Column("name", sa.String(512), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("quality", sa.String(16), nullable=True),
        sa.Column("rejected_reason", sa.String(200), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["number_id"],
            ["lead_desk_whatsapp_numbers.id"],
            name="fk_lead_desk_whatsapp_template_number",
        ),
        sa.CheckConstraint(
            "category IN ('MARKETING', 'UTILITY', 'AUTHENTICATION')", name="category"
        ),
        sa.CheckConstraint("length(trim(name)) > 0 AND length(trim(language)) > 0", name="name"),
    )
    op.create_index(
        "uq_lead_desk_whatsapp_template",
        "lead_desk_whatsapp_templates",
        ["tenant_id", "waba_id", "name", "language"],
        unique=True,
    )
    op.create_table(
        "lead_desk_sla_breaches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("breached_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alerted", sa.JSON(), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_sla_breach_tenant"
        ),
        sa.CheckConstraint("kind IN ('first_response')", name="kind"),
        sa.CheckConstraint("due_at >= started_at AND breached_at >= due_at", name="timing"),
    )
    op.create_index(
        "uq_lead_desk_sla_breach",
        "lead_desk_sla_breaches",
        ["tenant_id", "lead_id", "kind", "started_at"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_sla_breach_recent",
        "lead_desk_sla_breaches",
        ["tenant_id", "breached_at"],
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_sla_breaches, lead_desk_whatsapp_templates,"
            " lead_desk_whatsapp_messages, lead_desk_whatsapp_numbers IN ACCESS EXCLUSIVE MODE"
        )
    )
    bind = op.get_bind()
    for name in (
        "lead_desk_whatsapp_numbers",
        "lead_desk_whatsapp_messages",
        "lead_desk_whatsapp_templates",
        "lead_desk_sla_breaches",
    ):
        table = sa.table(name, sa.column("id"))
        if bind.scalar(sa.select(sa.exists().where(table.c.id.is_not(None)))):
            raise RuntimeError("WhatsApp and SLA history requires forward recovery.")
    op.drop_index("ix_lead_desk_sla_breach_recent", table_name="lead_desk_sla_breaches")
    op.drop_index("uq_lead_desk_sla_breach", table_name="lead_desk_sla_breaches")
    op.drop_table("lead_desk_sla_breaches")
    op.drop_index("uq_lead_desk_whatsapp_template", table_name="lead_desk_whatsapp_templates")
    op.drop_table("lead_desk_whatsapp_templates")
    op.drop_index("ix_lead_desk_whatsapp_message_chat", table_name="lead_desk_whatsapp_messages")
    op.drop_index("ix_lead_desk_whatsapp_message_lead", table_name="lead_desk_whatsapp_messages")
    op.drop_index("uq_lead_desk_whatsapp_message_wamid", table_name="lead_desk_whatsapp_messages")
    op.drop_table("lead_desk_whatsapp_messages")
    op.drop_index("ix_lead_desk_whatsapp_number_tenant", table_name="lead_desk_whatsapp_numbers")
    op.drop_index("uq_lead_desk_whatsapp_number_active", table_name="lead_desk_whatsapp_numbers")
    op.drop_table("lead_desk_whatsapp_numbers")
