"""Several pipelines per organisation (owner, 22 Oct 2026: "A for partner leads plus B for
enquiries as two pipelines").

- ``lead_desk_pipelines``: one row per pipeline: its name, its place in the list and the
  lead sources whose new leads it takes. An organisation without rows has one pipeline,
  ``main``; making a second writes ``main``'s row too.
- ``lead_desk_journey_versions.pipeline_key``: the pipeline a saved stage list belongs to.
  Null (every list saved so far) is ``main``. Version numbers stay unique per organisation.
- ``lead_desk_leads.pipeline_key``: the pipeline a lead is in; its step is one of that
  pipeline's stages. Null (every lead so far) is ``main``.

Both columns are nullable without a default, so adding them rewrites nothing and takes no
long lock; no index is added to an existing table.

Rollback: allowed while no pipeline row exists and every lead and stage list is still in
``main``; otherwise the pipelines' history requires forward recovery.

Chain: after 20261021_0120 (why a call stopped).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261022_0121"
down_revision = "20261021_0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_pipelines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "key"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_pipeline_tenant"),
        sa.CheckConstraint("length(trim(name)) > 0", name="lead_desk_pipeline_name"),
        sa.CheckConstraint("position >= 0", name="lead_desk_pipeline_position"),
    )
    op.add_column(
        "lead_desk_journey_versions", sa.Column("pipeline_key", sa.String(40), nullable=True)
    )
    op.add_column("lead_desk_leads", sa.Column("pipeline_key", sa.String(40), nullable=True))


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(
        sa.text(
            "LOCK TABLE lead_desk_leads, lead_desk_journey_versions, lead_desk_pipelines"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    pipelines = sa.table("lead_desk_pipelines", sa.column("key"))
    leads = sa.table("lead_desk_leads", sa.column("pipeline_key"))
    versions = sa.table("lead_desk_journey_versions", sa.column("pipeline_key"))
    bind = op.get_bind()
    if (
        bind.scalar(sa.select(sa.exists().where(pipelines.c.key.is_not(None))))
        or bind.scalar(sa.select(sa.exists().where(leads.c.pipeline_key != "main")))
        or bind.scalar(sa.select(sa.exists().where(versions.c.pipeline_key != "main")))
    ):
        raise RuntimeError("Pipeline history requires forward recovery.")
    op.drop_column("lead_desk_leads", "pipeline_key")
    op.drop_column("lead_desk_journey_versions", "pipeline_key")
    op.drop_table("lead_desk_pipelines")
