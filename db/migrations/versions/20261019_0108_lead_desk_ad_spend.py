"""Ad spend per Meta campaign in the Sales Xray CRM (19 Oct 2026).

One new table, nothing else changes: ``lead_desk_ad_spend_days``, what each of an
organisation's Meta campaigns spent per day, as Meta's Marketing API last said (read
with the organisation's own Continue with Meta connection). Cost per lead is worked
out from it and the leads that arrived; nothing here is a Sales Xray price.

A new, empty table may be rolled back; once any row exists, that history requires
forward recovery.

Chain: after 20261019_0107 (Messenger and Instagram).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261019_0108"
down_revision = "20261019_0107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_ad_spend_days",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("ad_account_id", sa.String(40), nullable=False),
        sa.Column("campaign_id", sa.String(40), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("campaign_name", sa.String(400), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("spend", sa.Numeric(16, 2), nullable=False),
        sa.Column("impressions", sa.BigInteger(), nullable=False),
        sa.Column("clicks", sa.BigInteger(), nullable=False),
        sa.Column("meta_leads", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "provider", "ad_account_id", "campaign_id", "day"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_ad_spend_tenant"),
        sa.CheckConstraint("provider IN ('meta')", name="provider"),
        sa.CheckConstraint(
            "spend >= 0 AND impressions >= 0 AND clicks >= 0 AND meta_leads >= 0", name="counts"
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$' AND ad_account_id ~ '^act_[0-9]{1,30}$'"
            " AND campaign_id ~ '^[0-9]{1,30}$'",
            name="ids",
        ),
    )
    op.create_index("ix_lead_desk_ad_spend_day", "lead_desk_ad_spend_days", ["tenant_id", "day"])


def downgrade() -> None:
    # Fence writes before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE lead_desk_ad_spend_days IN ACCESS EXCLUSIVE MODE"))
    table = sa.table("lead_desk_ad_spend_days", sa.column("tenant_id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(table.c.tenant_id.is_not(None)))):
        raise RuntimeError("Ad spend history requires forward recovery.")
    op.drop_index("ix_lead_desk_ad_spend_day", table_name="lead_desk_ad_spend_days")
    op.drop_table("lead_desk_ad_spend_days")
