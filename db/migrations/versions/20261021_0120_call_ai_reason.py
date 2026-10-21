"""Why a call stopped before a paid stage (owner, 21 Oct 2026: short calls).

- ``call_ai_decisions.reason``: 'level' (the seller's AI on calls level), 'short_call'
  (under a minute) or 'no_conversation' (under 20 seconds, or under 8 seconds of talk from
  the quieter of the two main speakers). Null on upgrades and on rows written before this
  migration; no default, so the table is not rewritten.

A rollback is possible while no row has a reason; after that, the history requires
forward recovery.

Chain: after 20261021_0119 (AI on calls).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0120"
down_revision = "20261021_0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_ai_decisions", sa.Column("reason", sa.String(32), nullable=True))
    op.create_check_constraint(
        "call_ai_decision_reason",
        "call_ai_decisions",
        "reason IS NULL OR reason IN ('level', 'short_call', 'no_conversation')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE call_ai_decisions IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("call_ai_decisions", sa.column("reason"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.reason.is_not(None)))):
        raise RuntimeError("AI on calls reason history requires forward recovery.")
    op.drop_constraint("call_ai_decision_reason", "call_ai_decisions", type_="check")
    op.drop_column("call_ai_decisions", "reason")
