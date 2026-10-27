"""The bell's "<name> is your lead now" (owner, 27 Oct 2026: a light notice when a lead is
assigned, and the bell as the full activity list; the orchestrator assigned 0142, after
0141).

- ``notifications.kind`` also allows 'lead_assigned': a lead the lead rules or a manager gave
  a seller, for that seller.

No table or column is added; only the check on the kind changes.

Rollback: allowed while no lead_assigned notification exists; otherwise that history
requires forward recovery.

Chain: after 20261027_0141 (Google connections).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0142"
down_revision = "20261027_0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "kind IN ('report_ready', 'analysis_paused', 'invite_received', 'bug_solved',"
        " 'lead_assigned')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE notifications IN ACCESS EXCLUSIVE MODE"))
    notifications = sa.table("notifications", sa.column("kind"))
    if op.get_bind().scalar(sa.select(sa.exists().where(notifications.c.kind == "lead_assigned"))):
        raise RuntimeError("Lead assigned notification history requires forward recovery.")
    # Written as PostgreSQL stores the earlier check after a dump and restore (element
    # casts inside ARRAY[...]), so the rollback gives back the exact schema the gate
    # compares, as 0138 does.
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "(kind)::text = ANY (ARRAY[('report_ready'::character varying)::text,"
        " ('analysis_paused'::character varying)::text,"
        " ('invite_received'::character varying)::text,"
        " ('bug_solved'::character varying)::text])",
    )
