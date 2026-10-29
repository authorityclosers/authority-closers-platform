"""Plan price history for the Admin price editor (owner, 29 Oct 2026: "Admin price editor";
the orchestrator assigned 0143, after 0142).

- New table ``plan_price_changes``: one append-only row per price change the owner makes in
  Admin, with the plan's new revision, the monthly and yearly paise before and after, the
  reason and who made it. The ``plans`` row carries the current price; checkout reads it.
  The ORM refuses updates and deletes (the schema gate allows no triggers).

No price changes here: the owner sets prices in Admin in each environment.

Rollback: allowed while no price change was saved; otherwise that history requires forward
recovery.

Chain: after 20261027_0142 (lead assigned notifications).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261029_0143"
down_revision = "20261027_0142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plan_price_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("plan_key", sa.String(40), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("monthly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("yearly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("previous_monthly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("previous_yearly_price_paise", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("changed_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name="fk_plan_price_change_plan"),
        sa.ForeignKeyConstraint(
            ["changed_by_person_id"], ["persons.id"], name="fk_plan_price_change_person"
        ),
        sa.UniqueConstraint("plan_id", "plan_revision", name="uq_plan_price_changes_plan_revision"),
        sa.CheckConstraint("plan_revision >= 1", name="plan_revision_positive"),
        sa.CheckConstraint(
            "monthly_price_paise IS NULL OR monthly_price_paise >= 0",
            name="monthly_price_paise_not_negative",
        ),
        sa.CheckConstraint(
            "yearly_price_paise IS NULL OR yearly_price_paise >= 0",
            name="yearly_price_paise_not_negative",
        ),
        sa.CheckConstraint("length(trim(reason)) > 0", name="reason_present"),
    )


def downgrade() -> None:
    # Fence writes before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE plan_price_changes IN ACCESS EXCLUSIVE MODE"))
    saved = sa.table("plan_price_changes", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(saved.c.id.is_not(None)))):
        raise RuntimeError("Plan price history requires forward recovery.")
    op.drop_table("plan_price_changes")
