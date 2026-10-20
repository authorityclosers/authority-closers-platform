"""AI replies: Admin's switch, model and cap, and the runner (orchestrator, 19 Oct 2026).

Owner rules: every AI provider and model is chosen in Admin (the key stays in Infisical,
read only by the AI replies runner), lead messages go to the provider only while Admin
has this environment's switch on, and the cap is a one-click dial.

- New table ``lead_desk_ai_settings``: revisions of this environment's AI replies
  settings (the switch, provider and model, cap and period), newest wins; written only
  from Admin, each save audited.
- ``lead_desk_ai_replies``: ``outcome`` accepts ``queued`` (for the runner) and
  ``waiting`` (for budget); new column ``settled_at`` (when the runner or the API
  finished acting on the row). Rows from before have none, and none of them waits on
  anything: AI replies were never switched on, and the API leaves any reply older
  than a day alone (``runner.LATE``).
- "Try it" (Settings, owners and admins): a reply drafted for a sample message the
  business types, never sent. ``mode`` accepts ``try``; such a row has no lead
  (``lead_id`` may be empty, but only for ``try``) and keeps the sample (new column
  ``sample``) until the sweep empties it after a day.

A rollback is possible while nothing uses the new parts (no settings saved, no reply
queued or waiting); after that, the history requires forward recovery.

Chain: after 20261019_0109 (AI replies).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0110"
down_revision = "20261019_0109"
branch_labels = None
depends_on = None


def _stored_any(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL's stored text for ``column IN (values)`` on a varchar column."""
    items = ", ".join(f"('{value}'::character varying)::text" for value in values)
    return f"({column})::text = ANY (ARRAY[{items}])"


# Downgrade restores the constraint in PostgreSQL's stored form, as the staging baseline holds it
# (a restored dump keeps that text; a fresh IN (...) parse stores another), so the schema gate's
# byte comparison matches. Same meaning as the original IN list.
_OUTCOME_BEFORE = _stored_any(
    "outcome", ("drafted", "sent", "handoff", "opted_out", "failed", "paused")
)
_OUTCOME_AFTER = (
    "outcome IN ('queued', 'drafted', 'sent', 'handoff', 'opted_out', 'failed', 'paused',"
    " 'waiting')"
)
_MODE_BEFORE = _stored_any("mode", ("suggest", "auto"))
_MODE_AFTER = "mode IN ('suggest', 'auto', 'try')"
_LEAD = "mode = 'try' OR lead_id IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "lead_desk_ai_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision", name="uq_lead_desk_ai_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )
    op.drop_constraint("ck_lead_desk_ai_replies_outcome", "lead_desk_ai_replies")
    op.create_check_constraint("outcome", "lead_desk_ai_replies", _OUTCOME_AFTER)
    op.add_column(
        "lead_desk_ai_replies",
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint("ck_lead_desk_ai_replies_mode", "lead_desk_ai_replies")
    op.create_check_constraint("mode", "lead_desk_ai_replies", _MODE_AFTER)
    op.add_column("lead_desk_ai_replies", sa.Column("sample", sa.String(500), nullable=True))
    op.alter_column("lead_desk_ai_replies", "lead_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint("lead", "lead_desk_ai_replies", _LEAD)


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(
        sa.text("LOCK TABLE lead_desk_ai_settings, lead_desk_ai_replies IN ACCESS EXCLUSIVE MODE")
    )
    bind = op.get_bind()
    saved = sa.table("lead_desk_ai_settings", sa.column("id"))
    replies = sa.table("lead_desk_ai_replies", sa.column("outcome"), sa.column("mode"))
    if (
        bind.scalar(sa.select(sa.exists().where(saved.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(replies.c.outcome.in_(("queued", "waiting")))))
        or bind.scalar(sa.select(sa.exists().where(replies.c.mode == "try")))
    ):
        raise RuntimeError("AI replies settings history requires forward recovery.")
    op.drop_constraint("ck_lead_desk_ai_replies_lead", "lead_desk_ai_replies")
    op.alter_column("lead_desk_ai_replies", "lead_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("lead_desk_ai_replies", "sample")
    op.drop_constraint("ck_lead_desk_ai_replies_mode", "lead_desk_ai_replies")
    op.create_check_constraint("mode", "lead_desk_ai_replies", _MODE_BEFORE)
    op.drop_column("lead_desk_ai_replies", "settled_at")
    op.drop_constraint("ck_lead_desk_ai_replies_outcome", "lead_desk_ai_replies")
    op.create_check_constraint("outcome", "lead_desk_ai_replies", _OUTCOME_BEFORE)
    op.drop_table("lead_desk_ai_settings")
