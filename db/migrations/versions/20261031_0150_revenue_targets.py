"""Revenue targets (owner meeting, 28 Oct 2026, Dipak's idea: each seller has a monthly
revenue target, the system works out the calls it takes, and Home shows a small bar).

- New table ``lead_desk_deal_amounts``: what a Won lead was worth. A move to Won writes one
  row with the amount, the seller it is credited to (the lead's owner) and the lead's side
  (Inbound or Cold). A correction is a new row; the newest row per lead stands. A Won lead
  from before this has no row: its amount is not set, never guessed.
- New table ``lead_desk_revenue_targets``: monthly targets, the organisation's (no person)
  and each seller's. Append-only; the newest row per month and person stands, and 0 clears a
  target. A seller without one gets an even share of the organisation's.

Whether sellers may set their own target and the typical deal size (for the maths until
there are enough deals of its own) sit in the workspace's lead desk settings (no column).

Rollback: possible only while both tables are empty; once they hold amounts or targets, the
history requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261031_0149.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261031_0150"
down_revision = "20261031_0149"
branch_labels = None
depends_on = None

MAX_AMOUNT = 1_000_000_000_000


def upgrade() -> None:
    op.create_table(
        "lead_desk_deal_amounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credited_person_id", sa.Uuid(), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["lead_id"], ["lead_desk_leads.id"], name="fk_lead_desk_deal_lead", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["credited_person_id"], ["persons.id"], name="fk_lead_desk_deal_credited"
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"], ["persons.id"], name="fk_lead_desk_deal_actor"
        ),
        sa.CheckConstraint(f"amount BETWEEN 1 AND {MAX_AMOUNT}", name="lead_desk_deal_amount"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)", name="lead_desk_deal_currency"
        ),
        sa.CheckConstraint("side IN ('inbound', 'cold')", name="lead_desk_deal_side"),
    )
    op.create_index("ix_lead_desk_deal_won", "lead_desk_deal_amounts", ["tenant_id", "won_at"])
    op.create_index(
        "ix_lead_desk_deal_lead", "lead_desk_deal_amounts", ["tenant_id", "lead_id", "created_at"]
    )
    op.create_index(
        "uq_lead_desk_deal_command",
        "lead_desk_deal_amounts",
        ["tenant_id", "command_id"],
        unique=True,
        postgresql_where=sa.text("command_id IS NOT NULL"),
    )
    op.create_table(
        "lead_desk_revenue_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("set_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_lead_desk_rev_target_person"
        ),
        sa.ForeignKeyConstraint(
            ["set_by_person_id"], ["persons.id"], name="fk_lead_desk_rev_target_setter"
        ),
        sa.CheckConstraint(
            f"amount BETWEEN 0 AND {MAX_AMOUNT}", name="lead_desk_rev_target_amount"
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="lead_desk_rev_target_currency",
        ),
    )
    op.create_index(
        "ix_lead_desk_rev_target_month",
        "lead_desk_revenue_targets",
        ["tenant_id", "month", "person_id", "created_at"],
    )
    op.create_index(
        "uq_lead_desk_rev_target_command",
        "lead_desk_revenue_targets",
        ["tenant_id", "command_id"],
        unique=True,
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_deal_amounts, lead_desk_revenue_targets IN ACCESS EXCLUSIVE MODE"
        )
    )
    amounts = sa.table("lead_desk_deal_amounts", sa.column("id"))
    targets = sa.table("lead_desk_revenue_targets", sa.column("id"))
    used = sa.or_(
        sa.exists().where(amounts.c.id.is_not(None)),
        sa.exists().where(targets.c.id.is_not(None)),
    )
    if op.get_bind().scalar(sa.select(used)):
        raise RuntimeError("Deal amount and revenue target history requires forward recovery.")
    op.drop_index("uq_lead_desk_rev_target_command", table_name="lead_desk_revenue_targets")
    op.drop_index("ix_lead_desk_rev_target_month", table_name="lead_desk_revenue_targets")
    op.drop_table("lead_desk_revenue_targets")
    op.drop_index("uq_lead_desk_deal_command", table_name="lead_desk_deal_amounts")
    op.drop_index("ix_lead_desk_deal_lead", table_name="lead_desk_deal_amounts")
    op.drop_index("ix_lead_desk_deal_won", table_name="lead_desk_deal_amounts")
    op.drop_table("lead_desk_deal_amounts")
