"""Add the billing accounts and the append-only capacity ledger (ADR 0052, S1a)."""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0062"
down_revision = "20260930_0061"
branch_labels = None
depends_on = None

LOT_KINDS = "('period_grant', 'purchase', 'grant')"
CLOSING_KINDS = "('expiry', 'refund_hold', 'refund')"


def upgrade() -> None:
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('personal', 'organisation')",
            name=op.f("ck_billing_accounts_kind_supported"),
        ),
        sa.CheckConstraint(
            "(kind = 'personal' AND person_id IS NOT NULL) OR "
            "(kind = 'organisation' AND person_id IS NULL)",
            name=op.f("ck_billing_accounts_kind_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["persons.id"], name="fk_billing_accounts_person_id_persons"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_billing_accounts_tenant_id_tenants",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_accounts")),
        sa.UniqueConstraint("tenant_id", "person_id", name=op.f("uq_billing_accounts_tenant_id")),
    )
    op.create_index(
        "ix_billing_accounts_organisation",
        "billing_accounts",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("person_id IS NULL"),
        sqlite_where=sa.text("person_id IS NULL"),
    )
    op.create_table(
        "billing_ledger_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("lot_id", sa.Uuid(), nullable=True),
        sa.Column("hold_id", sa.Uuid(), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_key", sa.String(length=40), nullable=True),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('period_grant', 'purchase', 'grant', 'correction', "
            "'expiry', 'refund_hold', 'refund', 'refund_hold_release')",
            name=op.f("ck_billing_ledger_entries_kind_supported"),
        ),
        sa.CheckConstraint(
            f"(kind IN {LOT_KINDS} AND seconds > 0 AND lot_id IS NULL AND hold_id IS NULL) OR "
            f"(kind IN {CLOSING_KINDS} AND seconds < 0 AND lot_id IS NOT NULL AND hold_id IS NULL)"
            " OR (kind = 'correction' AND seconds > 0 AND lot_id IS NULL AND hold_id IS NULL)"
            " OR (kind = 'correction' AND seconds < 0 AND lot_id IS NOT NULL AND hold_id IS NULL)"
            " OR (kind = 'refund_hold_release' AND seconds > 0 AND lot_id IS NOT NULL"
            " AND hold_id IS NOT NULL)",
            name=op.f("ck_billing_ledger_entries_kind_shape"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > valid_from",
            name=op.f("ck_billing_ledger_entries_window"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'system', 'provider')",
            name=op.f("ck_billing_ledger_entries_actor_type_supported"),
        ),
        sa.CheckConstraint(
            "length(source_ref) >= 3", name=op.f("ck_billing_ledger_entries_source_ref_length")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["billing_accounts.id"],
            name="fk_billing_ledger_entries_account_id_billing_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_billing_ledger_entries_actor_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name="fk_billing_ledger_entries_audit_event_id_audit_events",
        ),
        sa.ForeignKeyConstraint(
            ["hold_id"],
            ["billing_ledger_entries.id"],
            name="fk_billing_ledger_entries_hold_id_billing_ledger_entries",
        ),
        sa.ForeignKeyConstraint(
            ["lot_id"],
            ["billing_ledger_entries.id"],
            name="fk_billing_ledger_entries_lot_id_billing_ledger_entries",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_ledger_entries")),
        sa.UniqueConstraint("source_ref", name=op.f("uq_billing_ledger_entries_source_ref")),
    )
    op.create_index(
        "ix_billing_ledger_entries_account",
        "billing_ledger_entries",
        ["account_id", "created_at"],
    )
    op.create_index("ix_billing_ledger_entries_lot", "billing_ledger_entries", ["lot_id"])
    op.execute(
        sa.text(
            "CREATE FUNCTION prevent_billing_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN RAISE EXCEPTION 'billing history is append-only'; END; $$;"
        )
    )
    for table in ("billing_accounts", "billing_ledger_entries"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError("forward-only: the billing ledger is audit history")
