"""Websites and landing pages for the CRM: one line of script on a site, and every form fill
is a lead with its page and ad source (owner, 30 Oct 2026: "connecting websites matters a
lot to customers… today's way of adding websites and landing pages is a frustrating
experience"; design docs/product/lead-desk/website-connect.md; the orchestrator assigned
0145, after 0144).

- ``lead_desk_sites``: each website or landing page host the organisation's line is on:
  its state (active, paused or removed), when it was first and last seen, the page last
  seen, the builder it seems to use, and how many new leads it brought. Added by a person
  or by the site's first visit; a removed site stays as removed, so it can't add itself
  back.
- ``lead_desk_site_pages``: one row per page and day (UTC): views, the most lead forms
  seen on the page, form fills, new leads and bot fills turned away. Counts only: no
  visitor id and no address are kept.

The organisation's key is a website source in ``lead_desk_sources`` (kind ``webhook``,
``config.website``), so that table is unchanged. Both tables are new; nothing else changes.

Rollback: allowed while no site exists; otherwise that history requires forward recovery.

Chain: after 20261030_0144 (organisation seat grants).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0145"
down_revision = "20261030_0144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_sites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("host", sa.String(253), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("platform", sa.String(24), nullable=True),
        sa.Column("added", sa.String(8), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_page", sa.String(500), nullable=True),
        sa.Column("leads", sa.Integer(), nullable=False),
        sa.Column("last_lead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_site_tenant"),
        sa.UniqueConstraint("tenant_id", "host", name="uq_lead_desk_site_host"),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'removed')", name="lead_desk_site_status"
        ),
        sa.CheckConstraint("added IN ('person', 'seen')", name="lead_desk_site_added"),
        sa.CheckConstraint("leads >= 0", name="lead_desk_site_leads"),
        sa.CheckConstraint("length(trim(host)) > 0", name="lead_desk_site_host"),
    )
    op.create_index("ix_lead_desk_site_tenant", "lead_desk_sites", ["tenant_id", "status"])
    op.create_table(
        "lead_desk_site_pages",
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("views", sa.Integer(), nullable=False),
        sa.Column("forms", sa.Integer(), nullable=False),
        sa.Column("fills", sa.Integer(), nullable=False),
        sa.Column("leads", sa.Integer(), nullable=False),
        sa.Column("blocked", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("site_id", "day", "path"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_site_page_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["lead_desk_sites.id"], name="fk_lead_desk_site_page_site"
        ),
        sa.CheckConstraint(
            "views >= 0 AND forms >= 0 AND fills >= 0 AND leads >= 0 AND blocked >= 0",
            name="lead_desk_site_page_counts",
        ),
    )
    op.create_index("ix_lead_desk_site_page_tenant", "lead_desk_site_pages", ["tenant_id", "day"])


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    for table in ("lead_desk_site_pages", "lead_desk_sites"):
        op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    sites = sa.table("lead_desk_sites", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(sites.c.id.is_not(None)))):
        raise RuntimeError("Website history requires forward recovery.")
    op.drop_index("ix_lead_desk_site_page_tenant", table_name="lead_desk_site_pages")
    op.drop_table("lead_desk_site_pages")
    op.drop_index("ix_lead_desk_site_tenant", table_name="lead_desk_sites")
    op.drop_table("lead_desk_sites")
