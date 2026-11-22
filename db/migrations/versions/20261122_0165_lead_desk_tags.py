"""Tags on leads (owner's picks, 17 Nov 2026: M2-A "Add tag", the phone dock's Tag, import I4
"Source and tags"; docs/design/research/lead-import-and-management-20261116/02 §4 and §6).

- New table ``lead_desk_tags``: a workspace's own tags, each a short name and one of the app's
  colours, in the order the workspace keeps them. One name per workspace, case aside (a unique
  index on the lower-cased name), and only the app's eight colours (a CHECK). Words chosen by
  the workspace's staff; never a lead's data. A deleted tag is removed with its links (it is a
  label, not history: each lead's history keeps the lines that added and removed it).
- New table ``lead_desk_lead_tags``: which lead carries which tag, when it was added and by
  whom (none for an import's or an API's rules). Current state only; every change is an
  ``edited`` line in the lead's history.

Locks: additive only (two new tables). The foreign keys briefly lock ``lead_desk_leads``,
``tenants`` and ``persons`` against writes; ``lock_timeout`` bounds the wait, so a long
transaction on the leads fails this migration (retry it) instead of stalling every lead write.

Rollback: possible only while both tables are empty; once a tag exists, it requires forward
recovery (the 0088+ restore-drill policy).

Chain: after 20261120_0164 (sign-in account emails). Built 18 Nov as 0163; renumbered for v1.94
(22 Nov 2026) because 0164 shipped first.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261122_0165"
down_revision = "20261120_0164"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        "lead_desk_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("colour", sa.String(12), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_lead_desk_tag_tenant"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_desk_tag_tenant"),
        sa.ForeignKeyConstraint(
            ["created_by_person_id"], ["persons.id"], name="fk_lead_desk_tag_creator"
        ),
        sa.CheckConstraint("length(trim(name)) > 0", name="lead_desk_tag_name"),
        sa.CheckConstraint("revision >= 1", name="lead_desk_tag_revision"),
        # The app's eight tints (tags.COLOURS, contracts.TagColour), never a raw colour.
        sa.CheckConstraint(
            "colour IN ('mint', 'sky', 'amber', 'rose', 'violet', 'slate', 'lime', 'orange')",
            name="lead_desk_tag_colour",
        ),
    )
    op.create_index("ix_lead_desk_tag_tenant", "lead_desk_tags", ["tenant_id", "position"])
    # One "Hot" per workspace, however it is typed (two people making it at once included).
    op.create_index(
        "uq_lead_desk_tag_name",
        "lead_desk_tags",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_index(
        "uq_lead_desk_tag_command", "lead_desk_tags", ["tenant_id", "command_id"], unique=True
    )
    op.create_table(
        "lead_desk_lead_tags",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("tag_id", sa.Uuid(), nullable=False),
        sa.Column("added_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("lead_id", "tag_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "lead_id"],
            ["lead_desk_leads.tenant_id", "lead_desk_leads.id"],
            name="fk_lead_desk_lead_tag_lead",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tag_id"],
            ["lead_desk_tags.tenant_id", "lead_desk_tags.id"],
            name="fk_lead_desk_lead_tag_tag",
        ),
        sa.ForeignKeyConstraint(
            ["added_by_person_id"], ["persons.id"], name="fk_lead_desk_lead_tag_person"
        ),
    )
    op.create_index("ix_lead_desk_lead_tag_tag", "lead_desk_lead_tags", ["tenant_id", "tag_id"])


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(sa.text("LOCK TABLE lead_desk_lead_tags IN ACCESS EXCLUSIVE MODE"))
    op.execute(sa.text("LOCK TABLE lead_desk_tags IN ACCESS EXCLUSIVE MODE"))
    links = sa.table("lead_desk_lead_tags", sa.column("lead_id"))
    tags = sa.table("lead_desk_tags", sa.column("id"))
    bind = op.get_bind()
    if bind.scalar(sa.select(sa.exists().where(links.c.lead_id.is_not(None)))) or bind.scalar(
        sa.select(sa.exists().where(tags.c.id.is_not(None)))
    ):
        raise RuntimeError("Lead tags: that history requires forward recovery.")
    op.drop_index("ix_lead_desk_lead_tag_tag", table_name="lead_desk_lead_tags")
    op.drop_table("lead_desk_lead_tags")
    op.drop_index("uq_lead_desk_tag_name", table_name="lead_desk_tags")
    op.drop_index("uq_lead_desk_tag_command", table_name="lead_desk_tags")
    op.drop_index("ix_lead_desk_tag_tenant", table_name="lead_desk_tags")
    op.drop_table("lead_desk_tags")
