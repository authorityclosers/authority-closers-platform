"""What a workspace chose in its earlier lead imports (owner's picks, 17 Nov 2026: lead
import I2, "We'll remember this for your next import"; study 01 §6 "Remember mappings and
value maps per workspace", lead-management item 5).

- New table ``lead_desk_import_memory``: one row per workspace, kind and word. "column": a
  file header (normalised) and the field it fills, or "_keep" (kept on the lead as a detail)
  or "_skip" (not imported); "stage": a stage word and the stage key it means; "owner": a
  name and the teammate's person id. The next import's preview and check start from these.
  Words and choices made by the workspace's own staff; never a lead's data. A newer choice
  replaces the row (it is a preference, not history).

Rollback: possible only while the table is empty; once it holds a choice, it requires
forward recovery (the 0088+ restore-drill policy).

Chain: after 20261117_0159 (saved views).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261117_0160"
down_revision = "20261117_0159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_import_memory",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("word", sa.String(120), nullable=False),
        sa.Column("value", sa.String(80), nullable=False),
        sa.Column("updated_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_lead_import_memory_tenant"),
        sa.CheckConstraint("kind IN ('column', 'stage', 'owner')", name="lead_import_memory_kind"),
        sa.CheckConstraint("length(word) > 0", name="lead_import_memory_word"),
        sa.UniqueConstraint("tenant_id", "kind", "word", name="uq_lead_import_memory_word"),
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only an empty table.
    op.execute(sa.text("LOCK TABLE lead_desk_import_memory IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("lead_desk_import_memory", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
        raise RuntimeError("Import memory: that history requires forward recovery.")
    op.drop_table("lead_desk_import_memory")
