"""Saved views on Leads, kept on the server (owner, 16 Nov 2026; 02-management-findings-and-
spec.md §4.6, M5 and §6; the owner's 17 Nov pick M4-B: "make it understandable and
progressive"). Until now a view lived on one phone only (app/leads/saved-views.ts).

- New table ``lead_desk_saved_views``: a named Leads list (the same filter options as
  GET /leads, as JSON) with how it shows (columns, density, sort; JSON), either one person's
  ("me") or the whole team's ("team", made by owners, admins and managers). Rows hold a name
  and filter options chosen by the workspace's own staff; never a lead's data. A deleted view
  is removed (it is a preference, not history).

Rollback: possible only while the table is empty; once it holds a view, it requires forward
recovery (the 0088+ restore-drill policy).

Chain: after 20261117_0158 (Archive and Bin).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0159"
down_revision = "20261117_0158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_saved_views",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=False),
        sa.Column("visibility", sa.String(8), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("display", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_view_tenant"),
        sa.ForeignKeyConstraint(
            ["owner_person_id"], ["persons.id"], name="fk_lead_desk_view_owner"
        ),
        sa.CheckConstraint("visibility IN ('me', 'team')", name="lead_desk_view_visibility"),
        sa.CheckConstraint("length(trim(name)) > 0", name="lead_desk_view_name"),
        sa.CheckConstraint("revision >= 1", name="lead_desk_view_revision"),
    )
    op.create_index(
        "ix_lead_desk_view_tenant",
        "lead_desk_saved_views",
        ["tenant_id", "visibility", "position"],
    )
    op.create_index(
        "uq_lead_desk_view_command",
        "lead_desk_saved_views",
        ["tenant_id", "command_id"],
        unique=True,
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE lead_desk_saved_views IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("lead_desk_saved_views", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
        raise RuntimeError("Saved views: that history requires forward recovery.")
    op.drop_index("uq_lead_desk_view_command", table_name="lead_desk_saved_views")
    op.drop_index("ix_lead_desk_view_tenant", table_name="lead_desk_saved_views")
    op.drop_table("lead_desk_saved_views")
