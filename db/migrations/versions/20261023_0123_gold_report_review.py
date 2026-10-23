"""Gold review of every Report item (owner, 23 Oct 2026).

- ``conversation_gold_assignments.mode`` also allows 'report': the coaching lead reviews
  every item of a call's Report (``review_schema``), agreeing, disagreeing or fixing it.
- ``conversation_gold_assignments.items``: how many items the call's Report had when it
  was assigned (null for the other modes). Nullable, no default: the table is not
  rewritten.

A rollback is possible while no assignment uses either; after that, the history requires
forward recovery.

Chain: after 20261022_0122 (lead history call index).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0123"
down_revision = "20261022_0122"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        type_="check",
    )
    op.create_check_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        "mode IS NULL OR mode IN ('lines', 'brain4_blind', 'report')",
    )
    op.add_column(
        "conversation_gold_assignments",
        sa.Column("items", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "gold_items",
        "conversation_gold_assignments",
        "items IS NULL OR items BETWEEN 0 AND 500",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE conversation_gold_assignments IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("conversation_gold_assignments", sa.column("mode"), sa.column("items"))
    used = sa.exists().where(sa.or_(rows.c.mode == "report", rows.c["items"].is_not(None)))
    if op.get_bind().scalar(sa.select(used)):
        raise RuntimeError("Gold report review history requires forward recovery.")
    op.drop_constraint(
        "gold_items",
        "conversation_gold_assignments",
        type_="check",
    )
    op.drop_column("conversation_gold_assignments", "items")
    op.drop_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        type_="check",
    )
    # Written as PostgreSQL stores 0118's check after a dump and restore (element casts inside
    # ARRAY[...]), so the rollback gives back the exact schema the migration gate compares.
    op.create_check_constraint(
        "gold_mode",
        "conversation_gold_assignments",
        "mode IS NULL OR (mode)::text = ANY (ARRAY[('lines'::character varying)::text,"
        " ('brain4_blind'::character varying)::text])",
    )
