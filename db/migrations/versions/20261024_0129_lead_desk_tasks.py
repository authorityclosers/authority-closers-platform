"""The work-memory engine's tasks and reminders (owner, 24 Oct 2026: "NOT A VIEW, A WELL
PLANNED ALGORITHM WITH PROPER ENGINE AND WELL TESTED"; design:
docs/product/lead-desk/work-memory-engine.md, sections 2 and 9).

- ``lead_desk_tasks``: what a seller must do for a lead, as it stands now: its kind (call
  back, WhatsApp, email, send a file, meeting, other), when it is due (a meeting also has
  an end and a place), open, done or cancelled, who owns it, how far it moved (snoozes,
  rollovers, the first due), where it came from (the seller, after a call, a note, a
  promise the rules read, an adopted next action) and the command that made it, unique per
  workspace so a retry never makes a second task. Every change to it is a ``task`` event
  in the lead's history.
- ``lead_desk_task_reminders``: the reminder ledger. One row per (task, kind, the due it is
  for): a sender records the row before it sends, so a reminder goes once, a snoozed task
  reminds once for each new due, and two senders never both send.
- ``lead_desk_events`` gains the kinds ``task`` (a task made, moved, snoozed, done, undone,
  cancelled, reassigned or rolled over) and ``email`` (an email sent from the lead).
- ``lead_desk_meetings.task_id``: the task a meeting belongs to, set by the app; nullable
  and without a constraint, so adding it rewrites nothing.

Both tables are new, so their indexes are made with them.

Rollback: allowed while no task, no reminder, and no ``task`` or ``email`` event exists,
and no meeting names a task; otherwise that history requires forward recovery.

Chain: after 20261024_0128 (Lead OS foundation).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_0129"
down_revision = "20261024_0128"
branch_labels = None
depends_on = None

EVENT_VALUES = (
    "captured",
    "repeat",
    "assigned",
    "reassigned",
    "call",
    "result",
    "note",
    "edited",
    "message",
    "scheduled",
    "stage",
    "meeting",
    "suggestion",
)
EVENT_KINDS = ", ".join(f"'{value}'" for value in EVENT_VALUES)


def _stored_any(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL's stored text for ``column IN (values)`` on a varchar column: a check
    a rollback re-creates matches the baseline schema text exactly."""
    items = ", ".join(f"('{value}'::character varying)::text" for value in values)
    return f"({column})::text = ANY (ARRAY[{items}])"


def upgrade() -> None:
    op.create_table(
        "lead_desk_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(300), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("original_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snoozes", sa.Integer(), nullable=False),
        sa.Column("rollovers", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=True),
        sa.Column("remind_before_minutes", sa.Integer(), nullable=True),
        sa.Column("client_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_task_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_task_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "owner_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_task_owner",
        ),
        sa.CheckConstraint("revision >= 1", name="lead_desk_task_revision"),
        sa.CheckConstraint(
            "kind IN ('call_back', 'whatsapp', 'email', 'send_file', 'meeting', 'other')",
            name="lead_desk_task_kind",
        ),
        sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name="lead_desk_task_status"),
        sa.CheckConstraint("(status = 'done') = (done_at IS NOT NULL)", name="lead_desk_task_done"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="lead_desk_task_ends"),
        sa.CheckConstraint("snoozes >= 0 AND rollovers >= 0", name="lead_desk_task_moves"),
        sa.CheckConstraint(
            "remind_before_minutes IS NULL OR remind_before_minutes BETWEEN 0 AND 1440",
            name="lead_desk_task_remind_before",
        ),
        sa.CheckConstraint(
            "source IN ('seller', 'after_call', 'note', 'message', 'commitment', 'report',"
            " 'meeting', 'adopted', 'rule')",
            name="lead_desk_task_source",
        ),
        sa.CheckConstraint("length(trim(title)) > 0", name="lead_desk_task_title"),
    )
    # A retried command never makes a second task.
    op.create_index(
        "uq_lead_desk_task_command",
        "lead_desk_tasks",
        ["tenant_id", "command_id"],
        unique=True,
    )
    # A seller's open tasks by due: Tasks, reminders and the next best action.
    op.create_index(
        "ix_lead_desk_task_open",
        "lead_desk_tasks",
        ["tenant_id", "owner_person_id", "starts_at"],
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_lead_desk_task_lead", "lead_desk_tasks", ["tenant_id", "lead_id", "status"])
    # What changed since: the calendar feed.
    op.create_index("ix_lead_desk_task_updated", "lead_desk_tasks", ["tenant_id", "updated_at"])

    op.create_table(
        "lead_desk_task_reminders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("for_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("send_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deferred", sa.Boolean(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "task_id"],
            ["lead_desk_tasks.tenant_id", "lead_desk_tasks.id"],
            name="fk_lead_desk_task_reminder_task",
        ),
        sa.CheckConstraint(
            "kind IN ('before', 'due', 'overdue')", name="lead_desk_task_reminder_kind"
        ),
    )
    # One reminder per task, kind and due: the sender's claim.
    op.create_index(
        "uq_lead_desk_task_reminder",
        "lead_desk_task_reminders",
        ["task_id", "kind", "for_due_at"],
        unique=True,
    )
    op.create_index(
        "ix_lead_desk_task_reminder_task",
        "lead_desk_task_reminders",
        ["tenant_id", "task_id"],
    )

    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        f"kind IN ({EVENT_KINDS}, 'task', 'email')",
    )
    op.add_column("lead_desk_meetings", sa.Column("task_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_tasks, lead_desk_task_reminders, lead_desk_events,"
            " lead_desk_meetings IN ACCESS EXCLUSIVE MODE"
        )
    )
    tasks = sa.table("lead_desk_tasks", sa.column("id"))
    reminders = sa.table("lead_desk_task_reminders", sa.column("id"))
    events = sa.table("lead_desk_events", sa.column("kind"))
    meetings = sa.table("lead_desk_meetings", sa.column("task_id"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(tasks.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(reminders.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(events.c.kind.in_(("task", "email")))))
        or bind.scalar(sa.select(sa.exists().where(meetings.c.task_id.is_not(None))))
    ):
        raise RuntimeError("Lead desk task history requires forward recovery.")
    op.drop_column("lead_desk_meetings", "task_id")
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        _stored_any("kind", EVENT_VALUES),
    )
    op.drop_index("ix_lead_desk_task_reminder_task", table_name="lead_desk_task_reminders")
    op.drop_index("uq_lead_desk_task_reminder", table_name="lead_desk_task_reminders")
    op.drop_table("lead_desk_task_reminders")
    op.drop_index("ix_lead_desk_task_updated", table_name="lead_desk_tasks")
    op.drop_index("ix_lead_desk_task_lead", table_name="lead_desk_tasks")
    op.drop_index("ix_lead_desk_task_open", table_name="lead_desk_tasks")
    op.drop_index("uq_lead_desk_task_command", table_name="lead_desk_tasks")
    op.drop_table("lead_desk_tasks")
