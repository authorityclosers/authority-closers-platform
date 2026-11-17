"""Archive and Bin for leads (owner, 16 Nov 2026: "deleting old leads, managing the leads at a
higher level is not there"; docs/design/research/lead-import-and-management-20261116/
02-management-findings-and-spec.md §4.5 and §6).

- ``lead_desk_leads.archived_at`` and ``archived_by_person_id``: an archived lead leaves every
  work list, count and queue, keeps its stage, owner and history, is found by search and by
  the Archived list, and comes back with Restore.
- ``lead_desk_leads.binned_at`` and ``binned_by_person_id``: Delete moves a lead to the Bin.
  Owners and admins restore it within 30 days; after that the purge (the old hard delete,
  lead_desk/deletion.py) removes it. Nothing else reads a binned lead.
- Index ``ix_lead_desk_lead_binned`` (partial, binned leads only) for the Bin list and purge.

Additive only: nullable columns, no row changes; every existing lead stays on the desk.

Rollback: allowed while no lead is archived or binned; otherwise those choices require forward
recovery.

Chain: after 20261116_0157 (Ask Dipak's lesson library).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0158"
down_revision = "20261116_0157"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lead_desk_leads", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("lead_desk_leads", sa.Column("archived_by_person_id", sa.Uuid(), nullable=True))
    op.add_column(
        "lead_desk_leads", sa.Column("binned_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("lead_desk_leads", sa.Column("binned_by_person_id", sa.Uuid(), nullable=True))
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_lead_desk_lead_binned",
            "lead_desk_leads",
            ["tenant_id", "binned_at"],
            postgresql_where=sa.text("binned_at IS NOT NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Fence writes before the history check, then remove only what nothing uses yet.
    op.execute(sa.text("LOCK TABLE lead_desk_leads IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("lead_desk_leads", sa.column("archived_at"), sa.column("binned_at"))
    shelved = sa.or_(rows.c.archived_at.is_not(None), rows.c.binned_at.is_not(None))
    if op.get_bind().scalar(sa.select(sa.exists().where(shelved))):
        raise RuntimeError("Archived or binned leads: that history requires forward recovery.")
    op.drop_index("ix_lead_desk_lead_binned", table_name="lead_desk_leads")
    op.drop_column("lead_desk_leads", "binned_by_person_id")
    op.drop_column("lead_desk_leads", "binned_at")
    op.drop_column("lead_desk_leads", "archived_by_person_id")
    op.drop_column("lead_desk_leads", "archived_at")
