"""Tasks added by AI apps (owner order, 25 Oct 2026; design: docs/product/ai-writes.md).

- ``lead_desk_tasks.source`` also allows 'assistant': a task a seller sent from ChatGPT,
  Claude, an API key or the CLI. The lead's history says which ("via ChatGPT").

Only the check changes; no row is rewritten.

Rollback: allowed while no task has that source; otherwise that history requires forward
recovery.

Chain: after 20261025_0131 (the AI-write ledger).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0132"
down_revision = "20261025_0131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("lead_desk_task_source", "lead_desk_tasks", type_="check")
    op.create_check_constraint(
        "lead_desk_task_source",
        "lead_desk_tasks",
        "source IN ('seller', 'after_call', 'note', 'message', 'commitment', 'report',"
        " 'meeting', 'adopted', 'rule', 'assistant')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE lead_desk_tasks IN ACCESS EXCLUSIVE MODE"))
    tasks = sa.table("lead_desk_tasks", sa.column("source"))
    if op.get_bind().scalar(sa.select(sa.exists().where(tasks.c.source == "assistant"))):
        raise RuntimeError("AI app task history requires forward recovery.")
    op.drop_constraint("lead_desk_task_source", "lead_desk_tasks", type_="check")
    # Written as PostgreSQL stores 0129's check after a dump and restore (element casts
    # inside ARRAY[...]), so the rollback gives back the exact schema the gate compares.
    op.create_check_constraint(
        "lead_desk_task_source",
        "lead_desk_tasks",
        "(source)::text = ANY (ARRAY[('seller'::character varying)::text,"
        " ('after_call'::character varying)::text, ('note'::character varying)::text,"
        " ('message'::character varying)::text, ('commitment'::character varying)::text,"
        " ('report'::character varying)::text, ('meeting'::character varying)::text,"
        " ('adopted'::character varying)::text, ('rule'::character varying)::text])",
    )
