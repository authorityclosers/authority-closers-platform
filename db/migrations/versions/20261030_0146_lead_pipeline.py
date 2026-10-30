"""Live or cold: a source tag on every lead (owner, 30 Oct 2026, urgent fix 6: "Add a field
lead.pipeline = live | cold (default live)").

- ``lead_desk_leads.pipeline``: ``live`` (the leads worked every day) or ``cold`` (a bulk list
  kept apart). Empty, every lead from before, reads as ``live``, so nothing is rewritten here;
  the bulk upload is marked ``cold`` by a recorded data change (scripts/data-changes).
- Not ``pipeline_key`` (0121), which is the Lead OS pipeline a lead is in.
- No screen reads it yet: the cold/live switch comes after design.

Rollback: allowed while no lead is tagged; otherwise the tags require forward recovery.

Chain: after 20261030_0145.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0146"
down_revision = "20261030_0145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_desk_leads",
        sa.Column("pipeline", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    op.execute(sa.text("LOCK TABLE lead_desk_leads IN ACCESS EXCLUSIVE MODE"))
    leads = sa.table("lead_desk_leads", sa.column("pipeline"))
    if op.get_bind().scalar(sa.select(sa.exists().where(leads.c.pipeline.is_not(None)))):
        raise RuntimeError("Live or cold lead tag history requires forward recovery.")
    op.drop_column("lead_desk_leads", "pipeline")
