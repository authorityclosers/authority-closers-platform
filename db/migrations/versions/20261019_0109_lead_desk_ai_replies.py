"""AI replies to leads on WhatsApp, Messenger and Instagram (owner, 19 Oct 2026).

- New table ``lead_desk_ai_replies``: one row per AI draft, AI reply sent, or hand-off
  to a person (and why), with the model, tokens and cost for Admin; at most one
  automatic try per message. The draft is the customer's conversation and is emptied
  when the lead leaves Lead Desk.
- ``lead_desk_whatsapp_messages`` and ``lead_desk_social_messages`` accept the
  automation ``ai_reply`` (their ``auto`` checks gain one value; nothing else changes).

A new, empty table may be rolled back (the checks go back to their earlier values only
if no message is marked ``ai_reply``); once any row exists, that history requires
forward recovery.

Chain: after 20261019_0108 (ad spend).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0109"
down_revision = "20261019_0108"
branch_labels = None
depends_on = None

_WA_BEFORE = "auto IS NULL OR auto IN ('first_reply', 'out_of_hours')"
_WA_AFTER = "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'ai_reply')"
_SOCIAL_BEFORE = "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'comment_reply')"
_SOCIAL_AFTER = (
    "auto IS NULL OR auto IN ('first_reply', 'out_of_hours', 'comment_reply', 'ai_reply')"
)


def upgrade() -> None:
    op.create_table(
        "lead_desk_ai_replies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(24), nullable=True),
        sa.Column("draft", sa.String(1000), nullable=True),
        sa.Column("sent_message_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_inr", sa.Numeric(12, 4), nullable=True),
        sa.Column("usage_ref", sa.String(64), nullable=True),
        sa.Column("requested_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_ai_reply_tenant"),
        sa.CheckConstraint("channel IN ('whatsapp', 'messenger', 'instagram')", name="channel"),
        sa.CheckConstraint("mode IN ('suggest', 'auto')", name="mode"),
        sa.CheckConstraint(
            "outcome IN ('drafted', 'sent', 'handoff', 'opted_out', 'failed', 'paused')",
            name="outcome",
        ),
        sa.CheckConstraint(
            "input_tokens IS NULL OR (input_tokens >= 0 AND output_tokens >= 0)", name="tokens"
        ),
    )
    op.create_index(
        "ix_lead_desk_ai_reply_lead", "lead_desk_ai_replies", ["tenant_id", "lead_id", "created_at"]
    )
    op.create_index(
        "ix_lead_desk_ai_reply_recent", "lead_desk_ai_replies", ["tenant_id", "created_at"]
    )
    op.create_index(
        "uq_lead_desk_ai_reply_auto",
        "lead_desk_ai_replies",
        ["channel", "message_id"],
        unique=True,
        postgresql_where=sa.text("mode = 'auto' AND message_id IS NOT NULL"),
    )
    op.drop_constraint("ck_lead_desk_whatsapp_messages_auto", "lead_desk_whatsapp_messages")
    op.create_check_constraint("auto", "lead_desk_whatsapp_messages", _WA_AFTER)
    op.drop_constraint("ck_lead_desk_social_messages_auto", "lead_desk_social_messages")
    op.create_check_constraint("auto", "lead_desk_social_messages", _SOCIAL_AFTER)


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_ai_replies, lead_desk_whatsapp_messages,"
            " lead_desk_social_messages IN ACCESS EXCLUSIVE MODE"
        )
    )
    bind = op.get_bind()
    replies = sa.table("lead_desk_ai_replies", sa.column("id"))
    if bind.scalar(sa.select(sa.exists().where(replies.c.id.is_not(None)))):
        raise RuntimeError("AI reply history requires forward recovery.")
    for name in ("lead_desk_whatsapp_messages", "lead_desk_social_messages"):
        messages = sa.table(name, sa.column("auto"))
        if bind.scalar(sa.select(sa.exists().where(messages.c.auto == "ai_reply"))):
            raise RuntimeError("AI reply history requires forward recovery.")
    op.drop_constraint("ck_lead_desk_social_messages_auto", "lead_desk_social_messages")
    op.create_check_constraint("auto", "lead_desk_social_messages", _SOCIAL_BEFORE)
    op.drop_constraint("ck_lead_desk_whatsapp_messages_auto", "lead_desk_whatsapp_messages")
    op.create_check_constraint("auto", "lead_desk_whatsapp_messages", _WA_BEFORE)
    op.drop_index("uq_lead_desk_ai_reply_auto", table_name="lead_desk_ai_replies")
    op.drop_index("ix_lead_desk_ai_reply_recent", table_name="lead_desk_ai_replies")
    op.drop_index("ix_lead_desk_ai_reply_lead", table_name="lead_desk_ai_replies")
    op.drop_table("lead_desk_ai_replies")
