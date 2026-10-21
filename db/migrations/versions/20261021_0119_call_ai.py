"""AI on calls per organisation and seller (owner, 21 Oct 2026). Both tables append-only.

- New table ``call_ai_settings``: revisions of an organisation's levels (a default and
  each person's own: off, data_only, auto or full), newest wins; written only by the
  organisation's owners and admins, each save audited with old and new. Until a
  revision is saved, every call runs in full, as before.
- New table ``call_ai_decisions``: a call the level stopped before a paid stage (the
  plan and the first stage left out, one row per plan) and a person's "Get full
  report" for one call. Ids and levels only.

A rollback is possible while both tables are empty; after that, the history requires
forward recovery.

Chain: after 20261021_0118 (gold checkpoints).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0119"
down_revision = "20261021_0118"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_ai_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_ai_settings_tenant"),
        sa.UniqueConstraint("tenant_id", "revision", name="uq_call_ai_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="call_ai_settings_revision"),
    )
    op.create_table(
        "call_ai_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("recording_id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=True),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(8), nullable=True),
        sa.Column("settings_revision", sa.Integer(), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_call_ai_decision_tenant"),
        sa.ForeignKeyConstraint(
            ["recording_id"], ["conversation_recordings.id"], name="fk_call_ai_decision_recording"
        ),
        sa.UniqueConstraint("plan_id", "decision", name="uq_call_ai_decision_plan"),
        sa.CheckConstraint(
            "level IN ('off', 'data_only', 'auto', 'full')", name="call_ai_decision_level"
        ),
        sa.CheckConstraint("decision IN ('skipped', 'upgraded')", name="call_ai_decision_kind"),
        sa.CheckConstraint(
            "(decision = 'skipped') = (plan_id IS NOT NULL AND stage IN ('C2', 'C4'))",
            name="call_ai_decision_skip",
        ),
        sa.CheckConstraint(
            "decision <> 'upgraded' OR actor_person_id IS NOT NULL",
            name="call_ai_decision_actor",
        ),
    )
    op.create_index("ix_call_ai_decision_call", "call_ai_decisions", ["recording_id", "created_at"])


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE call_ai_settings, call_ai_decisions IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    settings = sa.table("call_ai_settings", sa.column("id"))
    decisions = sa.table("call_ai_decisions", sa.column("id"))
    if bind.scalar(sa.select(sa.exists().where(settings.c.id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(decisions.c.id.is_not(None)))
    ):
        raise RuntimeError("AI on calls history requires forward recovery.")
    op.drop_index("ix_call_ai_decision_call", table_name="call_ai_decisions")
    op.drop_table("call_ai_decisions")
    op.drop_table("call_ai_settings")
