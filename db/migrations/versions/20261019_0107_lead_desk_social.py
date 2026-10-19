"""Messenger and Instagram in the Sales Xray CRM (19 Oct 2026).

Each organisation connects its own Facebook Pages (with their linked Instagram
professional accounts) to AC's Messaging app. Settings are data per Page; nothing is
named after a customer.

Two new tables, nothing else changes:

- ``lead_desk_social_accounts``: an organisation's connected Pages, with the Page token
  sealed to the Page, the linked Instagram account, and the Page's channels, auto
  replies and comment rules. At most one active connection per Page.
- ``lead_desk_social_messages``: each lead's Messenger and Instagram conversation, in
  and out, once per Meta message id, and the comments a rule matched (each gets one
  private reply at most). The words are the customer's own data and are emptied when
  the lead leaves Lead Desk or the person takes a message back.

New, empty tables may be rolled back; once any row exists, that history requires
forward recovery.

Chain: after 20261019_0106 (admin staff keys).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0107"
down_revision = "20261019_0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_social_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("page_id", sa.String(32), nullable=False),
        sa.Column("page_name", sa.String(200), nullable=False),
        sa.Column("ig_user_id", sa.String(32), nullable=True),
        sa.Column("ig_username", sa.String(100), nullable=True),
        sa.Column("token", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("connected_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_social_account_tenant"
        ),
        sa.CheckConstraint("status IN ('active', 'disconnected')", name="status"),
        sa.CheckConstraint(
            "(status = 'disconnected') = (disconnected_at IS NOT NULL)", name="disconnected"
        ),
        sa.CheckConstraint("ig_username IS NULL OR ig_user_id IS NOT NULL", name="instagram"),
        sa.CheckConstraint(
            "page_id ~ '^[0-9]{5,32}$' AND (ig_user_id IS NULL OR ig_user_id ~ '^[0-9]{5,32}$')",
            name="ids",
        ),
    )
    op.create_index(
        "uq_lead_desk_social_account_page",
        "lead_desk_social_accounts",
        ["page_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_lead_desk_social_account_tenant", "lead_desk_social_accounts", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_lead_desk_social_account_instagram", "lead_desk_social_accounts", ["ig_user_id"]
    )
    op.create_table(
        "lead_desk_social_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("user_id", sa.String(40), nullable=False),
        sa.Column("user_name", sa.String(200), nullable=True),
        sa.Column("direction", sa.String(3), nullable=False),
        sa.Column("mid", sa.String(200), nullable=True),
        sa.Column("comment_id", sa.String(80), nullable=True),
        sa.Column("post_id", sa.String(100), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.String(4096), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("error_title", sa.String(200), nullable=True),
        sa.Column("sent_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("auto", sa.String(16), nullable=True),
        sa.Column("tag", sa.String(16), nullable=True),
        sa.Column("reply_state", sa.String(16), nullable=True),
        sa.Column("rule", sa.Integer(), nullable=True),
        sa.Column("meta_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["lead_desk_social_accounts.id"],
            name="fk_lead_desk_social_message_account",
        ),
        sa.CheckConstraint("channel IN ('messenger', 'instagram')", name="channel"),
        sa.CheckConstraint("direction IN ('in', 'out')", name="direction"),
        sa.CheckConstraint(
            "status IN ('queued', 'sent', 'delivered', 'read', 'failed', 'received')",
            name="status",
        ),
        sa.CheckConstraint("(direction = 'in') = (status = 'received')", name="received"),
        sa.CheckConstraint(
            "kind IN ('text', 'image', 'audio', 'video', 'file', 'sticker', 'share',"
            " 'story_reply', 'story_mention', 'postback', 'comment', 'unsupported')",
            name="kind",
        ),
        sa.CheckConstraint(
            "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'comment_reply')",
            name="auto",
        ),
        sa.CheckConstraint("tag IS NULL OR tag IN ('HUMAN_AGENT')", name="tag"),
        sa.CheckConstraint(
            "reply_state IS NULL OR reply_state IN ('pending', 'replied', 'failed', 'skipped')",
            name="reply_state",
        ),
        sa.CheckConstraint(
            "(kind = 'comment') = (direction = 'in' AND comment_id IS NOT NULL AND mid IS NULL)",
            name="comment",
        ),
    )
    op.create_index(
        "uq_lead_desk_social_message_mid",
        "lead_desk_social_messages",
        ["mid"],
        unique=True,
        postgresql_where=sa.text("mid IS NOT NULL"),
    )
    op.create_index(
        "uq_lead_desk_social_comment",
        "lead_desk_social_messages",
        ["comment_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'comment'"),
    )
    op.create_index(
        "uq_lead_desk_social_comment_reply",
        "lead_desk_social_messages",
        ["comment_id"],
        unique=True,
        postgresql_where=sa.text("auto = 'comment_reply'"),
    )
    op.create_index(
        "ix_lead_desk_social_message_lead",
        "lead_desk_social_messages",
        ["tenant_id", "lead_id", "created_at"],
    )
    op.create_index(
        "ix_lead_desk_social_message_chat",
        "lead_desk_social_messages",
        ["account_id", "channel", "user_id", "created_at"],
    )
    op.create_index(
        "ix_lead_desk_social_message_pending",
        "lead_desk_social_messages",
        ["reply_state", "created_at"],
        postgresql_where=sa.text("reply_state = 'pending'"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_social_messages, lead_desk_social_accounts"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    bind = op.get_bind()
    for name in ("lead_desk_social_accounts", "lead_desk_social_messages"):
        table = sa.table(name, sa.column("id"))
        if bind.scalar(sa.select(sa.exists().where(table.c.id.is_not(None)))):
            raise RuntimeError("Messenger and Instagram history requires forward recovery.")
    for index in (
        "ix_lead_desk_social_message_pending",
        "ix_lead_desk_social_message_chat",
        "ix_lead_desk_social_message_lead",
        "uq_lead_desk_social_comment_reply",
        "uq_lead_desk_social_comment",
        "uq_lead_desk_social_message_mid",
    ):
        op.drop_index(index, table_name="lead_desk_social_messages")
    op.drop_table("lead_desk_social_messages")
    for index in (
        "ix_lead_desk_social_account_instagram",
        "ix_lead_desk_social_account_tenant",
        "uq_lead_desk_social_account_page",
    ):
        op.drop_index(index, table_name="lead_desk_social_accounts")
    op.drop_table("lead_desk_social_accounts")
