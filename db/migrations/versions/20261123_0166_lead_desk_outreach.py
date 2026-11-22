"""The outreach log (v1.95, owner 22 Nov 2026: "every person we contact is a lead, every
message we send them is tracked, so we never feel spammy"; spec
boards/sx-redesign/review/v195-outreach-log-spec.md §2).

- New table ``lead_desk_outreach_senders``: the workspace's registered tools and automations
  (sx-engage, the tester auto-replies, the owner's own WhatsApp and Gmail on the Mac), each
  bound to one organisation API key and, for a person's own tool, to the person it speaks
  for (a CHECK keeps the two together).
- New table ``lead_desk_touch_overrides``: a manager's one-time "send anyway" for one lead
  and one channel, with the reason, used by one touch within 30 minutes.
- New table ``lead_desk_touches``: one outbound touch, from Sales X-Ray or an outside
  sender: who, which channel and provider, our own short summary (never the lead's words),
  delivery state, the reply that answered it, whether it counted toward the limits and the
  guard's verdict when it went. Idempotent by the provider's message id, else by the
  sender's own reference, else by the in-app command.
- New table ``lead_desk_touch_replies``: replies an outside sender reports (the lead's own
  words are kept only when the workspace turns that on).

Every link to a lead, person, sender, touch or override is a composite (tenant_id, id) key,
so no row can point across workspaces. The timeline line itself stays in
``lead_desk_events``: no existing table or CHECK changes.

Locks: additive only (four new tables). The foreign keys briefly lock ``lead_desk_leads``,
``memberships``, ``tenants``, ``persons`` and ``integration_api_keys`` against writes;
``lock_timeout`` bounds the wait, so a long transaction fails this migration (retry it)
instead of stalling every lead write.

Rollback: possible only while all four tables are empty; once a touch exists, it requires
forward recovery (the 0088+ restore-drill policy).

Chain: after 20261122_0165 (lead tags).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261123_0166"
down_revision = "20261122_0165"
branch_labels = None
depends_on = None

CHANNELS = (
    "channel IN ('whatsapp', 'sms', 'email', 'call', 'messenger', 'instagram', 'in_person',"
    " 'other')"
)
TABLES = (
    "lead_desk_touch_replies",
    "lead_desk_touches",
    "lead_desk_touch_overrides",
    "lead_desk_outreach_senders",
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "lead_desk_outreach_senders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("api_key_id", sa.Uuid(), nullable=True),
        sa.Column("channels", sa.JSON(), nullable=False),
        sa.Column("lead_defaults", sa.JSON(), nullable=False),
        sa.Column("guard_mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_outreach_sender_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_outreach_sender_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_outreach_sender_person",
        ),
        sa.ForeignKeyConstraint(
            ["api_key_id"], ["integration_api_keys.id"], name="fk_lead_desk_outreach_sender_key"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_person_id"], ["persons.id"], name="fk_lead_desk_outreach_sender_creator"
        ),
        sa.CheckConstraint("key ~ '^[a-z0-9][a-z0-9-]{1,39}$'", name="key"),
        sa.CheckConstraint("length(trim(label)) > 0", name="label"),
        sa.CheckConstraint("kind IN ('automation', 'person_tool')", name="kind"),
        # A person's own tool speaks for exactly one person; an automation for nobody.
        sa.CheckConstraint(
            "(kind = 'person_tool') = (person_id IS NOT NULL)",
            name="person",
        ),
        sa.CheckConstraint("guard_mode IN ('report', 'hold')", name="guard_mode"),
        sa.CheckConstraint("status IN ('active', 'paused')", name="status"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )
    op.create_index(
        "uq_lead_desk_outreach_sender_key",
        "lead_desk_outreach_senders",
        ["tenant_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_outreach_sender_api_key",
        "lead_desk_outreach_senders",
        ["tenant_id", "api_key_id"],
    )

    op.create_table(
        "lead_desk_touch_overrides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("granted_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("asked_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason_key", sa.String(16), nullable=False),
        sa.Column("reason_text", sa.String(200), nullable=True),
        sa.Column("verdict", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by_touch_id", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_touch_override_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_touch_override_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "granted_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_touch_override_granted_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asked_by_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_touch_override_asked_by",
        ),
        sa.CheckConstraint(CHANNELS, name="channel"),
        sa.CheckConstraint(
            "reason_key IN ('lead_asked', 'time_sensitive', 'wrong_count', 'other')",
            name="reason",
        ),
        sa.CheckConstraint(
            "reason_key <> 'other' OR length(trim(coalesce(reason_text, ''))) > 0",
            name="other_words",
        ),
        # Used by exactly one touch, once.
        sa.CheckConstraint(
            "(used_at IS NULL) = (used_by_touch_id IS NULL)",
            name="used",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry"),
    )
    op.create_index(
        "uq_lead_desk_touch_override_command",
        "lead_desk_touch_overrides",
        ["tenant_id", "command_id"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_touch_override_open",
        "lead_desk_touch_overrides",
        ["tenant_id", "lead_id", "channel", "expires_at"],
        postgresql_where=sa.text("used_at IS NULL"),
    )

    op.create_table(
        "lead_desk_touches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("content_kind", sa.String(12), nullable=False),
        sa.Column("initiated", sa.String(8), nullable=False),
        sa.Column("sender_type", sa.String(12), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("sender_id", sa.Uuid(), nullable=True),
        sa.Column("automation", sa.String(40), nullable=True),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("via", sa.String(12), nullable=False),
        sa.Column("provider", sa.String(16), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("provider_chat_id", sa.String(80), nullable=True),
        sa.Column("client_ref", sa.String(120), nullable=True),
        sa.Column("summary", sa.String(280), nullable=True),
        sa.Column("template_name", sa.String(512), nullable=True),
        sa.Column("attachment", sa.JSON(), nullable=True),
        sa.Column("quote_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("guard", sa.JSON(), nullable=False),
        sa.Column("override_id", sa.Uuid(), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("whatsapp_message_id", sa.Uuid(), nullable=True),
        sa.Column("social_message_id", sa.Uuid(), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reply_ref", sa.JSON(), nullable=True),
        sa.Column("request_sha256", sa.String(64), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_touch_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_touch_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_touch_person",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sender_id"],
            ["lead_desk_outreach_senders.tenant_id", "lead_desk_outreach_senders.id"],
            name="fk_lead_desk_touch_sender",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "override_id"],
            ["lead_desk_touch_overrides.tenant_id", "lead_desk_touch_overrides.id"],
            name="fk_lead_desk_touch_override",
        ),
        sa.CheckConstraint(CHANNELS, name="channel"),
        sa.CheckConstraint(
            "content_kind IN ('text', 'template', 'file', 'quote', 'link', 'call', 'voice')",
            name="content_kind",
        ),
        sa.CheckConstraint("initiated IN ('outreach', 'reply')", name="initiated"),
        sa.CheckConstraint("sender_type IN ('person', 'automation')", name="sender_type"),
        # A person's touch names them; an automation's never does.
        sa.CheckConstraint("(sender_type = 'person') = (person_id IS NOT NULL)", name="person"),
        sa.CheckConstraint(
            "via IN ('app_link', 'cloud', 'api', 'phone', 'manual', 'pulse')",
            name="via",
        ),
        sa.CheckConstraint(
            "provider IS NULL OR provider IN ('meta_cloud', 'wa_linked', 'gmail', 'smtp',"
            " 'pulse', 'phone', 'other')",
            name="provider",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'opened', 'sent', 'delivered', 'read', 'failed', 'expired')",
            name="status",
        ),
        # A reservation (queued) always ends by itself.
        sa.CheckConstraint("(status = 'queued') = (expires_at IS NOT NULL)", name="reservation"),
    )
    op.create_index(
        "ix_lead_desk_touch_lead", "lead_desk_touches", ["tenant_id", "lead_id", "sent_at"]
    )
    op.create_index(
        "ix_lead_desk_touch_person",
        "lead_desk_touches",
        ["tenant_id", "person_id", "sent_at"],
        postgresql_where=sa.text("person_id IS NOT NULL"),
    )
    op.create_index(
        "ix_lead_desk_touch_sender",
        "lead_desk_touches",
        ["tenant_id", "sender_id", "sent_at"],
        postgresql_where=sa.text("sender_id IS NOT NULL"),
    )
    op.create_index("ix_lead_desk_touch_recent", "lead_desk_touches", ["tenant_id", "sent_at"])
    op.create_index(
        "ix_lead_desk_touch_open",
        "lead_desk_touches",
        ["tenant_id", "lead_id", "channel", "sent_at"],
        postgresql_where=sa.text("replied_at IS NULL AND status <> 'failed'"),
    )
    op.create_index(
        "ix_lead_desk_touch_reserved",
        "lead_desk_touches",
        ["expires_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    # The idempotency keys: the provider's message id (a linked WhatsApp's ids are unique only
    # inside a chat), the sender's own reference, the in-app command, and one touch per
    # timeline line and per Sales X-Ray message row.
    op.create_index(
        "uq_lead_desk_touch_provider",
        "lead_desk_touches",
        [
            "tenant_id",
            "provider",
            sa.text("coalesce(provider_chat_id, '')"),
            "provider_message_id",
        ],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_touch_client_ref",
        "lead_desk_touches",
        ["tenant_id", "sender_id", "client_ref"],
        unique=True,
        postgresql_where=sa.text("client_ref IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_touch_command",
        "lead_desk_touches",
        ["tenant_id", "command_id"],
        unique=True,
        postgresql_where=sa.text("command_id IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_touch_event",
        "lead_desk_touches",
        ["event_id"],
        unique=True,
        postgresql_where=sa.text("event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_touch_wa",
        "lead_desk_touches",
        ["whatsapp_message_id"],
        unique=True,
        postgresql_where=sa.text("whatsapp_message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_touch_social",
        "lead_desk_touches",
        ["social_message_id"],
        unique=True,
        postgresql_where=sa.text("social_message_id IS NOT NULL"),
    )

    op.create_table(
        "lead_desk_touch_replies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("touch_id", sa.Uuid(), nullable=True),
        sa.Column("sender_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(12), nullable=False),
        sa.Column("provider", sa.String(16), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("provider_chat_id", sa.String(80), nullable=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("excerpt", sa.String(280), nullable=True),
        sa.Column("opt_out", sa.Boolean(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_touch_reply_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "touch_id"],
            ["lead_desk_touches.tenant_id", "lead_desk_touches.id"],
            name="fk_lead_desk_touch_reply_touch",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "sender_id"],
            ["lead_desk_outreach_senders.tenant_id", "lead_desk_outreach_senders.id"],
            name="fk_lead_desk_touch_reply_sender",
        ),
        sa.CheckConstraint(CHANNELS, name="channel"),
        sa.CheckConstraint(
            "provider IS NULL OR provider IN ('meta_cloud', 'wa_linked', 'gmail', 'smtp',"
            " 'pulse', 'phone', 'other')",
            name="provider",
        ),
        sa.CheckConstraint(
            "kind IN ('text', 'image', 'video', 'audio', 'document', 'sticker', 'reaction',"
            " 'other')",
            name="kind",
        ),
    )
    op.create_index(
        "ix_lead_desk_touch_reply_lead",
        "lead_desk_touch_replies",
        ["tenant_id", "lead_id", "received_at"],
    )
    op.create_index(
        "uq_lead_desk_touch_reply_provider",
        "lead_desk_touch_replies",
        [
            "tenant_id",
            "provider",
            sa.text("coalesce(provider_chat_id, '')"),
            "provider_message_id",
        ],
        unique=True,
        postgresql_where=sa.text("provider_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE lead_desk_touch_replies IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE lead_desk_touches IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE lead_desk_touch_overrides IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE lead_desk_outreach_senders IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    for table in TABLES:
        rows = sa.table(table, sa.column("id"))
        if bind.scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
            raise RuntimeError("Outreach log: that history requires forward recovery.")
    op.drop_index("uq_lead_desk_touch_reply_provider", table_name="lead_desk_touch_replies")
    op.drop_index("ix_lead_desk_touch_reply_lead", table_name="lead_desk_touch_replies")
    op.drop_table("lead_desk_touch_replies")
    op.drop_index("uq_lead_desk_touch_social", table_name="lead_desk_touches")
    op.drop_index("uq_lead_desk_touch_wa", table_name="lead_desk_touches")
    op.drop_index("uq_lead_desk_touch_event", table_name="lead_desk_touches")
    op.drop_index("uq_lead_desk_touch_command", table_name="lead_desk_touches")
    op.drop_index("uq_lead_desk_touch_client_ref", table_name="lead_desk_touches")
    op.drop_index("uq_lead_desk_touch_provider", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_reserved", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_open", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_recent", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_sender", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_person", table_name="lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_lead", table_name="lead_desk_touches")
    op.drop_table("lead_desk_touches")
    op.drop_index("ix_lead_desk_touch_override_open", table_name="lead_desk_touch_overrides")
    op.drop_index("uq_lead_desk_touch_override_command", table_name="lead_desk_touch_overrides")
    op.drop_table("lead_desk_touch_overrides")
    op.drop_index("ix_lead_desk_outreach_sender_api_key", table_name="lead_desk_outreach_senders")
    op.drop_index("uq_lead_desk_outreach_sender_key", table_name="lead_desk_outreach_senders")
    op.drop_table("lead_desk_outreach_senders")
