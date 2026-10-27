"""Google Sheets and Drive, slice 1: one Google connection per organisation, and the rows
its Sheet copy has written (owner, 27 Oct 2026: "connect all Google apps… Google Sheets
integration is important"; design docs/product/lead-desk/google-sheets-drive.md; the
orchestrator assigned 0141, after v1.00's 0140).

- ``lead_desk_google_connections``: an organisation's Google sign-in for Sheets and Drive:
  who connected it, which Google account, the scopes granted (``drive.file`` only, never
  the whole Drive), the refresh token sealed (AES-GCM, never in clear), and what it made
  (the "Sales X-Ray" folder, the copy Sheet). At most one live connection per
  organisation; a disconnected one stays as history with ``revoked_at``.
- ``lead_desk_sheet_rows``: each lead the copy Sheet has been sent, so a lead is written
  once, and a new copy Sheet starts afresh.

Both tables are new, so their indexes are made with them. Nothing else changes.

Rollback: allowed while no connection exists; otherwise that history requires forward
recovery.

Chain: after 20261026_0140 (Pulse link).
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0141"
down_revision = "20261026_0140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_desk_google_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("connected_by_person_id", sa.Uuid(), nullable=False),
        sa.Column("google_email", sa.String(320), nullable=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("token", sa.JSON(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_google_connection_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["connected_by_person_id"],
            ["persons.id"],
            name="fk_lead_desk_google_connection_person",
        ),
    )
    op.create_index(
        "uq_lead_desk_google_connection_live",
        "lead_desk_google_connections",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "lead_desk_sheet_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("spreadsheet_id", sa.String(128), nullable=False),
        sa.Column("lead_id", sa.Uuid(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_lead_desk_sheet_row_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id", "spreadsheet_id", "lead_id", name="uq_lead_desk_sheet_row_lead"
        ),
    )


def downgrade() -> None:
    # Fence writes before the history check, then undo only what nothing uses yet.
    for table in ("lead_desk_sheet_rows", "lead_desk_google_connections"):
        op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    rows = sa.table("lead_desk_google_connections", sa.column("id"))
    if op.get_bind().scalar(sa.select(sa.exists().where(rows.c.id.is_not(None)))):
        raise RuntimeError("Google connection history requires forward recovery.")
    op.drop_table("lead_desk_sheet_rows")
    op.drop_index("uq_lead_desk_google_connection_live", table_name="lead_desk_google_connections")
    op.drop_table("lead_desk_google_connections")
