"""Gold review checkpoints and the blind Brain 4.0 mode (orchestrator, 21 Oct 2026).

- ``conversation_gold_assignments.mode``: how the reviewer judges the call. 'lines' is
  the 29-line review of the AI's report; 'brain4_blind' asks for the 18 Brain 4.0
  ratings before Brain 4.0's own are shown (AC-SVAL-01 section 8.1). Null (every
  assignment before this migration) is 'lines'; no default, so the table is not
  rewritten.
- ``conversation_gold_assignments.checkpoint``: the gold checkpoint that chose the call
  (``profiles/gold_checkpoint.json``), so its daily and total limits can be counted;
  null for the assignments made before checkpoints.

A rollback is possible while no assignment uses either column; after that, the history
requires forward recovery.

Chain: after 20261021_0117 (Brain 4.0 shadow reads).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261021_0118"
down_revision = "20261021_0117"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversation_gold_assignments",
        sa.Column("mode", sa.String(16), nullable=True),
    )
    op.add_column(
        "conversation_gold_assignments",
        sa.Column("checkpoint", sa.String(64), nullable=True),
    )
    op.create_check_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        "mode IS NULL OR mode IN ('lines', 'brain4_blind')",
    )
    op.create_check_constraint(
        "gold_checkpoint",
        "conversation_gold_assignments",
        "checkpoint IS NULL OR length(checkpoint) BETWEEN 1 AND 64",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE conversation_gold_assignments IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("conversation_gold_assignments", sa.column("mode"), sa.column("checkpoint"))
    used = sa.exists().where(sa.or_(rows.c.mode.is_not(None), rows.c.checkpoint.is_not(None)))
    if op.get_bind().scalar(sa.select(used)):
        raise RuntimeError("Gold checkpoint history requires forward recovery.")
    op.drop_constraint(
        "gold_checkpoint",
        "conversation_gold_assignments",
        type_="check",
    )
    op.drop_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        type_="check",
    )
    op.drop_column("conversation_gold_assignments", "checkpoint")
    op.drop_column("conversation_gold_assignments", "mode")
