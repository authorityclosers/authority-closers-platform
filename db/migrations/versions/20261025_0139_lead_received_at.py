"""When a lead reached the business, apart from when Sales Xray filed it (owner, 26 Oct
2026, dev report #7: an old Meta lead brought in later showed as a new lead).

- ``lead_desk_leads.received_at``: when the person sent it (a Meta form's created_time),
  set when the source says. Empty means "when it was filed": reads take
  ``coalesce(received_at, created_at)``, so nothing is backfilled.

Rollback: allowed while no lead has a time of its own; otherwise those times require
forward recovery.

Chain: after 20261025_0138.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0139"
down_revision = "20261025_0138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_desk_leads",
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.execute(sa.text("LOCK TABLE lead_desk_leads IN ACCESS EXCLUSIVE MODE"))
    leads = sa.table("lead_desk_leads", sa.column("received_at"))
    if op.get_bind().scalar(sa.select(sa.exists().where(leads.c.received_at.is_not(None)))):
        raise RuntimeError("Lead arrival time history requires forward recovery.")
    op.drop_column("lead_desk_leads", "received_at")
