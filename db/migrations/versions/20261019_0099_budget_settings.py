"""AI budget settings owned in Admin (owner decision via the orchestrator, 19 Oct 2026).

The owner sets each environment's AI budget ceiling and its period (lifetime,
monthly or daily, India time) in Admin; any Admin moves the cap up to the
ceiling. Until the first row exists, the release approval's sealed amount is the
ceiling. The table is append-only by the app: every change is a new revision for
its budget scope. New, empty tables may be rolled back; once any row exists,
history requires forward recovery.

Chain: after 20261019_0098 (report settings).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0099"
down_revision = "20261019_0098"
branch_labels = None
depends_on = None

TABLE = "conversation_budget_settings"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ceiling_paise", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("period_cap_paise", sa.Integer(), nullable=True),
        sa.Column("set_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_id", "revision", name="uq_budget_setting_revision"),
        sa.CheckConstraint("revision >= 1", name="revision"),
        sa.CheckConstraint("ceiling_paise >= 0", name="ceiling"),
        sa.CheckConstraint("period IN ('lifetime', 'monthly', 'daily')", name="period"),
        sa.CheckConstraint(
            "(period = 'lifetime') = (period_cap_paise IS NULL)"
            " AND (period_cap_paise IS NULL OR period_cap_paise BETWEEN 0 AND ceiling_paise)",
            name="period_cap",
        ),
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if op.get_bind().scalar(sa.select(sa.exists().select_from(sa.table(TABLE)))):
        raise RuntimeError("Budget settings history requires forward recovery.")
    op.drop_table(TABLE)
