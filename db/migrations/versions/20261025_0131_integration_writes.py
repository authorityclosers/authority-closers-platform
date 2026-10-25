"""The AI-write ledger (owner order, 25 Oct 2026; design: docs/product/ai-writes.md).

- ``integration_writes``: one row per change an AI app (a Connect connection), an API key
  or the CLI made to a lead, and one per undo. Append-only: an undo is a new row that
  points at the change it undoes, at most once. It holds ids, the request's SHA-256 and
  the names of the fields set, never the text. It decides the daily caps and the 7-day
  undo; the lead's own history and the audit log keep the rest.

The table is new, so its indexes are made with it. Nothing else changes.

Rollback: allowed while no change has been recorded; otherwise that history requires
forward recovery.

Chain: after 20261025_0130 (the team engine's targets and nudges).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261025_0131"
down_revision = "20261025_0130"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_writes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("via", sa.String(12), nullable=False),
        sa.Column("grant_id", sa.Uuid(), nullable=True),
        sa.Column("key_id", sa.Uuid(), nullable=True),
        sa.Column("app_label", sa.String(80), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=True),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("undoes_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_integration_write_tenant"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "person_id"],
            ["memberships.tenant_id", "memberships.person_id"],
            name="fk_integration_write_person",
        ),
        sa.ForeignKeyConstraint(
            ["undoes_id"], ["integration_writes.id"], name="fk_integration_write_undoes"
        ),
        sa.CheckConstraint("via IN ('connection', 'key', 'app')", name="integration_write_via"),
        sa.CheckConstraint(
            "((via = 'connection') = (grant_id IS NOT NULL))"
            " AND ((via = 'key') = (key_id IS NOT NULL))",
            name="integration_write_door",
        ),
        sa.CheckConstraint(
            "action IN ('note', 'task', 'outcome', 'summary', 'stage', 'create', 'update',"
            " 'import', 'undo')",
            name="integration_write_action",
        ),
        sa.CheckConstraint(
            "(action = 'undo') = (undoes_id IS NOT NULL)", name="integration_write_undo"
        ),
        sa.CheckConstraint(
            "via = 'app' OR request_sha256 IS NOT NULL", name="integration_write_request"
        ),
    )
    # A retried request records nothing twice.
    op.create_index(
        "uq_integration_write_command",
        "integration_writes",
        ["tenant_id", "command_id"],
        unique=True,
    )
    # A change is undone at most once.
    op.create_index(
        "uq_integration_write_undoes",
        "integration_writes",
        ["undoes_id"],
        unique=True,
        postgresql_where=sa.text("undoes_id IS NOT NULL"),
    )
    # The daily caps: per connection, per key, per lead and per workspace.
    op.create_index(
        "ix_integration_write_grant", "integration_writes", ["tenant_id", "grant_id", "created_at"]
    )
    op.create_index(
        "ix_integration_write_key", "integration_writes", ["tenant_id", "key_id", "created_at"]
    )
    op.create_index(
        "ix_integration_write_lead", "integration_writes", ["tenant_id", "lead_id", "created_at"]
    )
    op.create_index(
        "ix_integration_write_recent", "integration_writes", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    op.execute(sa.text("LOCK TABLE integration_writes IN ACCESS EXCLUSIVE MODE"))
    writes = sa.table("integration_writes", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(writes.c.id.is_not(None)))):
        raise RuntimeError("AI-write history requires forward recovery.")
    op.drop_index("ix_integration_write_recent", table_name="integration_writes")
    op.drop_index("ix_integration_write_lead", table_name="integration_writes")
    op.drop_index("ix_integration_write_key", table_name="integration_writes")
    op.drop_index("ix_integration_write_grant", table_name="integration_writes")
    op.drop_index("uq_integration_write_undoes", table_name="integration_writes")
    op.drop_index("uq_integration_write_command", table_name="integration_writes")
    op.drop_table("integration_writes")
