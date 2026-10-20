"""AI spend caps per environment (owner, 20 Oct 2026: "stop the leakage of credits").

- New table ``ai_spend_settings``: revisions of this environment's AI spend caps (the
  background switch, the daily and monthly caps, the backfill cap and the per-feature
  caps), newest wins; written only from Admin, each save audited with old and new.
  Until a revision is saved, the code's defaults for the environment apply.

A rollback is possible while no settings were saved; after that, the history requires
forward recovery.

Chain: after 20261020_0111 (lead stages per business).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261020_0112"
down_revision = "20261020_0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_spend_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("revision", name="uq_ai_spend_settings_revision"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE ai_spend_settings IN ACCESS EXCLUSIVE MODE"))
    bind = op.get_bind()
    saved = sa.table("ai_spend_settings", sa.column("id"))
    if bind.scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("AI spend settings history requires forward recovery.")
    op.drop_table("ai_spend_settings")
