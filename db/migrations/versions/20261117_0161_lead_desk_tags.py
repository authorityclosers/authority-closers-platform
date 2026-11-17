"""Lead tags (owner's picks, 17 Nov 2026: the M2-A bar's "Add tag", the M1-A dock's Tag and
lead import I4-A "Source and tags", e.g. "Nov video ad"; tags.py).

- New table ``lead_desk_tags``: a workspace's tag, a short name chosen by its own staff and a
  colour from the app's palette; ``name_key`` (the name in lower case, spaces folded) keeps one
  tag per name. Never a lead's data.
- New table ``lead_desk_lead_tags``: which lead carries which tag, who put it on, when, and the
  command that did (a bulk job's Undo takes off only what that job put on). A lead or tag
  removed takes its rows with it.

Rollback: possible only while both tables are empty; once a tag exists, it requires forward
recovery (the 0088+ restore-drill policy).

Chain: after 20261117_0160 (import memory).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0161"
down_revision = "20261117_0160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("name_key", sa.String(32), nullable=False),
        sa.Column("colour", sa.String(12), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_tag_tenant"),
        sa.CheckConstraint("length(trim(name)) > 0", name="lead_desk_tag_name"),
        sa.CheckConstraint(
            "colour IN ('mint', 'sky', 'violet', 'amber', 'rose', 'slate')",
            name="lead_desk_tag_colour",
        ),
        sa.CheckConstraint("revision >= 1", name="lead_desk_tag_revision"),
        sa.UniqueConstraint("tenant_id", "name_key", name="uq_lead_desk_tag_name"),
        sa.UniqueConstraint("tenant_id", "command_id", name="uq_lead_desk_tag_command"),
    )
    op.create_table(
        "lead_desk_lead_tags",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lead_id", "tag_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_lead_tag_tenant"),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["lead_desk_leads.id"],
            name="fk_lead_desk_lead_tag_lead",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["lead_desk_tags.id"],
            name="fk_lead_desk_lead_tag_tag",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_lead_desk_lead_tag_tag", "lead_desk_lead_tags", ["tenant_id", "tag_id"])
    op.create_index(
        "ix_lead_desk_lead_tag_command", "lead_desk_lead_tags", ["tenant_id", "command_id"]
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE lead_desk_tags IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE lead_desk_lead_tags IN ACCESS EXCLUSIVE MODE"))
    tags = sa.table("lead_desk_tags", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(tags.c.id.is_not(None)))):
        raise RuntimeError("Lead tags: that history requires forward recovery.")
    op.drop_index("ix_lead_desk_lead_tag_command", table_name="lead_desk_lead_tags")
    op.drop_index("ix_lead_desk_lead_tag_tag", table_name="lead_desk_lead_tags")
    op.drop_table("lead_desk_lead_tags")
    op.drop_table("lead_desk_tags")
