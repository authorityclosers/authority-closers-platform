"""The app-change ledger also records giving a lead to a teammate (API gap 3, 15 Nov 2026: the
orchestrator's option 2 for the owner's 14 Nov order, "API … ten times stronger"; an
organisation's API key held by an owner or admin may assign leads, one or in bulk, each change
in the ledger with its 7-day undo; docs/product/ai-writes.md, "Amended 15 Nov").

- ``integration_writes.action`` also takes ``assign``.

Additive only: no table, no row changes; every existing row keeps its action.

Rollback: allowed while no ledger row is an assign; otherwise that history requires forward
recovery.

Chain: after 20261115_0155 (Ask Dipak's coaching loop).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261115_0156"
down_revision = "20261115_0155"
branch_labels = None
depends_on = None

TABLE = "integration_writes"
CHECK = "ck_integration_writes_integration_write_action"
BEFORE = (
    "action IN ('note', 'task', 'outcome', 'summary', 'stage', 'create', 'update',"
    " 'import', 'undo')"
)
AFTER = (
    "action IN ('note', 'task', 'outcome', 'summary', 'stage', 'create', 'update',"
    " 'import', 'undo', 'assign')"
)


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(op.f(CHECK), TABLE, AFTER)


def downgrade() -> None:
    # Fence writes before the history check, then narrow only what nothing uses yet.
    op.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table(TABLE, sa.column("action"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.action == "assign"))):
        raise RuntimeError("Assigns in the ledger: that history requires forward recovery.")
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.create_check_constraint(op.f(CHECK), TABLE, BEFORE)
