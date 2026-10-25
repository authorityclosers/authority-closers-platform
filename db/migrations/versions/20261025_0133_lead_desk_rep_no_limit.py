"""A seller's open-lead limit may be "No limit" (owner, 25 Oct 2026: "leads you see are capped
to 50 and all leads go beyond that, what and why? … fix this").

- ``lead_desk_reps.max_open`` becomes nullable: NULL is No limit. Its check allows NULL or 1 to
  1000, as before for a number.

No row is rewritten.

Rollback: allowed while no seller has No limit; otherwise that choice requires forward
recovery.

Chain: after 20261025_0132 (tasks from AI apps).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0133"
down_revision = "20261025_0132"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("lead_desk_rep_cap", "lead_desk_reps", type_="check")
    op.alter_column("lead_desk_reps", "max_open", existing_type=sa.Integer(), nullable=True)
    op.create_check_constraint(
        "lead_desk_rep_cap",
        "lead_desk_reps",
        "max_open IS NULL OR max_open BETWEEN 1 AND 1000",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no choice.
    op.execute(sa.text("LOCK TABLE lead_desk_reps IN ACCESS EXCLUSIVE MODE"))
    reps = sa.table("lead_desk_reps", sa.column("max_open"))
    if op.get_bind().scalar(sa.select(sa.exists().where(reps.c.max_open.is_(None)))):
        raise RuntimeError("Seller limit history requires forward recovery.")
    op.drop_constraint("lead_desk_rep_cap", "lead_desk_reps", type_="check")
    op.alter_column("lead_desk_reps", "max_open", existing_type=sa.Integer(), nullable=False)
    op.create_check_constraint("lead_desk_rep_cap", "lead_desk_reps", "max_open BETWEEN 1 AND 1000")
