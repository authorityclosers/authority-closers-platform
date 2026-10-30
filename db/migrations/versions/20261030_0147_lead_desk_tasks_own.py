"""A task of your own, with no lead (owner order, 30 Oct 2026, fix 4: Add Task with an
"optional linked lead"; the orchestrator assigned 0147, after 0146).

- ``lead_desk_tasks.lead_id`` may be empty: a task with no lead is its creator's own, on
  their list, and reminds them. A task on a lead is as before.
- A task with no lead always has an owner (``lead_desk_task_lead_or_owner``).

Additive only: no row changes, every existing task keeps its lead, no default is added.

Rollback: allowed while every task has a lead; otherwise that history requires forward
recovery.

Chain: after 20261030_0146 (lead pipeline).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0147"
down_revision = "20261030_0146"
branch_labels = None
depends_on = None

TABLE = "lead_desk_tasks"
CHECK = "ck_lead_desk_tasks_lead_desk_task_lead_or_owner"


def upgrade() -> None:
    op.alter_column(TABLE, "lead_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f(CHECK), TABLE, "lead_id IS NOT NULL OR owner_person_id IS NOT NULL"
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    tasks = sa.table(TABLE, sa.column("lead_id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(tasks.c.lead_id.is_(None)))):
        raise RuntimeError("Tasks without a lead: that history requires forward recovery.")
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.alter_column(TABLE, "lead_id", existing_type=sa.Uuid(), nullable=False)
