"""Read marks for Sales Xray Chats (20 Oct 2026).

Unread chats were remembered in each browser, so a chat read on the phone stayed unread
on the computer. The server now keeps how far each person has read each conversation.

- New table ``lead_desk_chat_reads``: one row each time a person reads further into a
  conversation (a lead on one channel and one account: the WhatsApp number or the
  Facebook Page). Rows are only added; the newest ``read_to`` is the mark. Ids and times
  only: no message words, no Meta ids.

A rollback is possible while no mark was saved; after that, the marks require forward
recovery.

Chain: after 20261020_0112 (AI spend caps).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0113"
down_revision = "20261020_0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_chat_reads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("read_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_chat_read_tenant"
        ),
        sa.CheckConstraint("channel IN ('whatsapp', 'messenger', 'instagram')", name="channel"),
        sa.CheckConstraint("read_to <= created_at", name="read_time"),
    )
    op.create_index(
        "ix_lead_desk_chat_read_mark",
        "lead_desk_chat_reads",
        ["tenant_id", "person_id", "channel", "account_id", "lead_id", "read_to"],
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no marks.
    op.execute(sa.text("LOCK TABLE lead_desk_chat_reads IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    marks = sa.table("lead_desk_chat_reads", sa.column("id"))
    if bind.scalar(sa.select(sa.exists().where(marks.c.id.is_not(None)))):
        raise RuntimeError("Chat read marks history requires forward recovery.")
    op.drop_index("ix_lead_desk_chat_read_mark", table_name="lead_desk_chat_reads")
    op.drop_table("lead_desk_chat_reads")
