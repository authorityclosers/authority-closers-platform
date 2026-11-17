"""The bell's "New lead: <name>" (owner, 17 Nov 2026: a new lead must grab attention at once,
so the hot lead is called as fast as possible; lead_desk.bell.NEW).

- ``notifications.kind`` also allows 'lead_new': a lead that came in by itself, for the
  workspace's owners, admins and, while no one has it, managers.

No table or column is added; only the check on the kind changes.

Rollback: allowed while no lead_new notification exists; otherwise that history requires
forward recovery.

Chain: after 20261117_0160 (import memory).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0161"
down_revision = "20261117_0160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "kind IN ('report_ready', 'analysis_paused', 'invite_received', 'bug_solved',"
        " 'lead_assigned', 'lead_new')",
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what holds no history.
    op.execute(sa.text("LOCK TABLE notifications IN ACCESS EXCLUSIVE MODE"))
    notifications = sa.table("notifications", sa.column("kind"))
    if op.get_bind().scalar(sa.select(sa.exists().where(notifications.c.kind == "lead_new"))):
        raise RuntimeError("New lead notification history requires forward recovery.")
    # Written as PostgreSQL stores 0142's check after a dump and restore (element casts
    # inside ARRAY[...]), so the rollback gives back the exact schema the gate compares.
    op.drop_constraint(op.f("ck_notifications_kind"), "notifications", type_="check")
    op.create_check_constraint(
        "kind",
        "notifications",
        "(kind)::text = ANY (ARRAY[('report_ready'::character varying)::text,"
        " ('analysis_paused'::character varying)::text,"
        " ('invite_received'::character varying)::text,"
        " ('bug_solved'::character varying)::text,"
        " ('lead_assigned'::character varying)::text])",
    )
