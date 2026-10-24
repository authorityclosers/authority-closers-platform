"""Lead OS foundation: Junk, a lead's time in its stage, its Lost or Junk reason, and
meetings (owner order 24 Oct 2026; the sales team's nine-stage pipeline spec).

- ``lead_desk_leads.stage`` may be ``junk``: a fake, invalid or unusable lead, closed
  and kept apart from Lost (a real lead who said no), so it never counts in conversion.
- ``lead_desk_leads.stage_at``: when the lead entered its current stage (its age there).
  Null for every lead from before (the schema gate keeps data out of migrations): it is
  set on the lead's next move, and reports read stage ages from the history.
- ``lead_desk_leads.outcome_reason``: why it is Lost or Junk (a reason key), only while
  it is; the history keeps every reason.
- ``lead_desk_events`` gains the kinds ``meeting`` (a meeting booked, moved, held,
  missed or cancelled) and ``suggestion`` (a hint the desk offered, such as "Junk?",
  and what the seller did with it).
- ``lead_desk_meetings``: the meeting as it stands, one scheduled meeting per lead at
  most (a postponed meeting moves, it is never booked twice); its history is the
  ``meeting`` events.

Stage rules (which stage may follow which, what each asks) are data in the stage lists
(``lead_desk_journey_versions.stages``) and need no column.

Both new lead columns are nullable without a default, so adding them rewrites nothing;
no index is added to an existing table.

Rollback: allowed while no lead is Junk or has a reason, no meeting exists and no
``meeting`` or ``suggestion`` event exists; otherwise that history requires forward
recovery.

Chain: after 20261023_0127 (feedback answers).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261024_0128"
down_revision = "20261023_0127"
branch_labels = None
depends_on = None

STAGES = "'new', 'not_connected', 'follow_up', 'interested', 'won', 'lost'"
EVENT_KINDS = (
    "'captured', 'repeat', 'assigned', 'reassigned', 'call', 'result', 'note', 'edited',"
    " 'message', 'scheduled', 'stage'"
)
STAGE_VALUES = ("new", "not_connected", "follow_up", "interested", "won", "lost")
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
)


def _stored_any(column: str, values: tuple[str, ...]) -> str:
    """PostgreSQL's stored text for ``column IN (values)`` on a varchar column: a check
    a rollback re-creates matches the baseline schema text exactly."""
    items = ", ".join(f"('{value}'::character varying)::text" for value in values)
    return f"({column})::text = ANY (ARRAY[{items}])"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_stage"), "lead_desk_leads", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_stage"),
        "lead_desk_leads",
        f"stage IN ({STAGES}, 'junk')",
    )
    op.add_column(
        "lead_desk_leads", sa.Column("stage_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("lead_desk_leads", sa.Column("outcome_reason", sa.String(40), nullable=True))
    op.create_check_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_outcome_reason"),
        "lead_desk_leads",
        "outcome_reason IS NULL OR stage IN ('lost', 'junk')",
    )
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        f"kind IN ({EVENT_KINDS}, 'meeting', 'suggestion')",
    )
    op.create_table(
        "lead_desk_meetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("location", sa.String(300), nullable=True),
        sa.Column("agenda", sa.String(1000), nullable=True),
        sa.Column("outcome_note", sa.String(1000), nullable=True),
        sa.Column("host_person_id", sa.Uuid(), nullable=True),
        sa.Column("reminded_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_meeting_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "host_person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_meeting_host",
        ),
        sa.CheckConstraint("revision >= 1", name="lead_desk_meeting_revision"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'done', 'missed', 'cancelled')",
            name="lead_desk_meeting_status",
        ),
        sa.CheckConstraint(
            "mode IN ('zoom', 'google_meet', 'phone', 'in_person', 'other')",
            name="lead_desk_meeting_mode",
        ),
        sa.CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="lead_desk_meeting_duration"),
        sa.CheckConstraint(
            "(status = 'scheduled') = (closed_at IS NULL)", name="lead_desk_meeting_closed"
        ),
    )
    # One scheduled meeting per lead: a postponed meeting moves, it is never booked twice.
    op.create_index(
        "uq_lead_desk_meeting_open",
        "lead_desk_meetings",
        ["tenant_id", "lead_id"],
        unique=True,
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "ix_lead_desk_meeting_due",
        "lead_desk_meetings",
        ["tenant_id", "starts_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_leads, lead_desk_events, lead_desk_meetings"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    leads = sa.table("lead_desk_leads", sa.column("stage"), sa.column("outcome_reason"))
    events = sa.table("lead_desk_events", sa.column("kind"))
    meetings = sa.table("lead_desk_meetings", sa.column("id"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(leads.c.stage == "junk")))
        or bind.scalar(sa.select(sa.exists().where(leads.c.outcome_reason.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(meetings.c.id.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(events.c.kind.in_(("meeting", "suggestion")))))
    ):
        raise RuntimeError("Lead OS history requires forward recovery.")
    op.drop_index("ix_lead_desk_meeting_due", table_name="lead_desk_meetings")
    op.drop_index("uq_lead_desk_meeting_open", table_name="lead_desk_meetings")
    op.drop_table("lead_desk_meetings")
    op.drop_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"), "lead_desk_events", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_events_lead_desk_event_kind"),
        "lead_desk_events",
        _stored_any("kind", EVENT_VALUES),
    )
    op.drop_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_outcome_reason"), "lead_desk_leads", type_="check"
    )
    op.drop_column("lead_desk_leads", "outcome_reason")
    op.drop_column("lead_desk_leads", "stage_at")
    op.drop_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_stage"), "lead_desk_leads", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_lead_desk_leads_lead_desk_lead_stage"),
        "lead_desk_leads",
        _stored_any("stage", STAGE_VALUES),
    )
