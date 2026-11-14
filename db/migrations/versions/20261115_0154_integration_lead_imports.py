"""Lead imports through the API, MCP and CLI (owner, 14 Nov 2026: "pushing thousands of leads
using Claude").

- ``integration_lead_imports``: one import a key or a connected app asked for, written once:
  who, how, how many rows, the Idempotency-Key and the request's digest.
- ``integration_lead_import_chunks``: the work queue, up to 500 rows each. The rows wait only
  while the chunk does; once filed (or failed) the chunk keeps each row's outcome and drops
  the rows, so a lead's details never stay here.

Rollback: possible only while both tables are empty; once they hold an import, its history
requires forward recovery (the 0088+ restore-drill policy).

Chain: after 20261114_0153.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261115_0154"
down_revision = "20261114_0153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_lead_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("via", sa.String(16), nullable=False),
        sa.Column("door_id", sa.Uuid(), nullable=False),
        sa.Column("acting_person_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=True),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_import_tenant", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["acting_person_id"], ["persons.id"], name="fk_lead_import_person"),
        sa.CheckConstraint("via IN ('key', 'connection')", name="lead_import_via"),
        sa.CheckConstraint("total BETWEEN 1 AND 10000", name="lead_import_total"),
        sa.CheckConstraint("chunks BETWEEN 1 AND 100", name="lead_import_chunks"),
    )
    op.create_index(
        "ix_lead_import_tenant", "integration_lead_imports", ["tenant_id", "created_at"]
    )
    op.create_index("ix_lead_import_door", "integration_lead_imports", ["door_id", "created_at"])
    op.create_index(
        "uq_lead_import_idempotency",
        "integration_lead_imports",
        ["tenant_id", "door_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "integration_lead_import_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("first_row", sa.Integer(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["integration_lead_imports.id"],
            name="fk_lead_import_chunk_import",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("import_id", "position", name="uq_lead_import_chunk_position"),
        sa.CheckConstraint(
            "state IN ('pending', 'done', 'failed')", name="lead_import_chunk_state"
        ),
        sa.CheckConstraint(
            "first_row >= 0 AND size BETWEEN 1 AND 500", name="lead_import_chunk_rows"
        ),
        sa.CheckConstraint(
            "(state = 'pending') = (rows IS NOT NULL)", name="lead_import_chunk_held"
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 10", name="lead_import_chunk_attempts"),
    )
    op.create_index(
        "ix_lead_import_chunk_pending",
        "integration_lead_import_chunks",
        ["created_at"],
        postgresql_where=sa.text("state = 'pending'"),
    )


def downgrade() -> None:
    # Fence inserts before the history check, then remove only empty tables.
    op.execute(
        sa.text(
            "LOCK TABLE integration_lead_import_chunks, integration_lead_imports"
            " IN ACCESS EXCLUSIVE MODE"
        )
    )
    imports = sa.table("integration_lead_imports", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(imports.c.id.is_not(None)))):
        raise RuntimeError("Lead import history requires forward recovery.")
    op.drop_index("ix_lead_import_chunk_pending", table_name="integration_lead_import_chunks")
    op.drop_table("integration_lead_import_chunks")
    op.drop_index("uq_lead_import_idempotency", table_name="integration_lead_imports")
    op.drop_index("ix_lead_import_door", table_name="integration_lead_imports")
    op.drop_index("ix_lead_import_tenant", table_name="integration_lead_imports")
    op.drop_table("integration_lead_imports")
