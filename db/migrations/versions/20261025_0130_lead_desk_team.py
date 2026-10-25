"""The team engine's targets and nudge ledger (owner program, 25 Oct 2026, section 2;
design: docs/product/lead-desk/team-engine.md, sections 2 and 3).

- ``lead_desk_targets``: a seller's daily or weekly target on one metric (calls, connects,
  follow-ups, meetings), set by an owner or manager from a day on. A new value is a new row
  that supersedes the old one from its day, so a past day keeps the target it had. The
  command that set it is unique per workspace, so a retry never sets it twice.
- ``lead_desk_nudges``: the nudge ledger. One row per seller and two-hour window of the work
  day: the sender writes it before it sends, so a seller gets one nudge per window at most
  and two senders never both send.

Both tables are new, so their indexes are made with them. Nothing else changes.

Rollback: allowed while no target and no nudge exists; otherwise that history requires
forward recovery.

Chain: after 20261024_0129 (the work-memory engine's tasks).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0130"
down_revision = "20261024_0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(8), nullable=False),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("set_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_target_person",
        ),
        sa.CheckConstraint("period IN ('day', 'week')", name="lead_desk_target_period"),
        sa.CheckConstraint(
            "metric IN ('calls', 'connects', 'follow_ups', 'meetings')",
            name="lead_desk_target_metric",
        ),
        sa.CheckConstraint("value BETWEEN 0 AND 10000", name="lead_desk_target_value"),
    )
    # A retried command never sets a target twice.
    op.create_index(
        "uq_lead_desk_target_command", "lead_desk_targets", ["tenant_id", "command_id"], unique=True
    )
    # A seller's targets as they stood on a day: the newest row from that day back.
    op.create_index(
        "ix_lead_desk_target_person",
        "lead_desk_targets",
        ["tenant_id", "person_id", "metric", "period", "effective_from"],
    )

    op.create_table(
        "lead_desk_nudges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("words", sa.String(200), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_lead_desk_nudge_person",
        ),
        sa.CheckConstraint("kind IN ('drift', 'idle')", name="lead_desk_nudge_kind"),
    )
    # One nudge per seller and window: the sender's claim.
    op.create_index(
        "uq_lead_desk_nudge_window",
        "lead_desk_nudges",
        ["tenant_id", "person_id", "window_start"],
        unique=True,
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(sa.text("LOCK TABLE lead_desk_targets, lead_desk_nudges IN ACCESS EXCLUSIVE MODE"))
    targets = sa.table("lead_desk_targets", sa.column("id"))
    nudges = sa.table("lead_desk_nudges", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(targets.c.id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(nudges.c.id.is_not(None)))
    ):
        raise RuntimeError("Lead desk team history requires forward recovery.")
    op.drop_index("uq_lead_desk_nudge_window", table_name="lead_desk_nudges")
    op.drop_table("lead_desk_nudges")
    op.drop_index("ix_lead_desk_target_person", table_name="lead_desk_targets")
    op.drop_index("uq_lead_desk_target_command", table_name="lead_desk_targets")
    op.drop_table("lead_desk_targets")
