"""Append-only invoices, credit notes and buyer snapshots (AUT-878, ADR 0053)."""

import sqlalchemy as sa
from alembic import op

revision = "20261003_0069"
down_revision = "20261003_0068"
branch_labels = None
depends_on = None
TABLES = (
    "billing_invoice_counters",
    "billing_buyer_tax_details",
    "billing_invoices",
    "billing_credit_notes",
)


def upgrade() -> None:
    op.create_table(TABLES[0], sa.Column("financial_year", sa.String(7), primary_key=True))
    op.create_table(
        TABLES[1],
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("billing_orders.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("gstin", sa.String(15)),
        sa.Column("state_code", sa.String(2)),
        sa.Column(
            "supersedes_id", sa.Uuid(), sa.ForeignKey("billing_buyer_tax_details.id"), unique=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_billing_buyer_order",
        TABLES[1],
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("supersedes_id IS NULL"),
    )
    for table in TABLES[2:]:
        invoice = table == "billing_invoices"
        extra = (
            [
                sa.Column("order_id", sa.Uuid(), sa.ForeignKey("billing_orders.id")),
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("payment_ref", sa.String(64), nullable=False),
            ]
            if invoice
            else [
                sa.Column(
                    "invoice_id", sa.Uuid(), sa.ForeignKey("billing_invoices.id"), nullable=False
                ),
                sa.Column("refund_ref", sa.String(64), nullable=False),
            ]
        )
        op.create_table(
            table,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "account_id", sa.Uuid(), sa.ForeignKey("billing_accounts.id"), nullable=False
            ),
            sa.Column(
                "financial_year",
                sa.String(7),
                sa.ForeignKey("billing_invoice_counters.financial_year"),
                nullable=False,
            ),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("number", sa.String(100), nullable=False, unique=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "payment_event_id" if invoice else "refund_event_id",
                sa.Uuid(),
                sa.ForeignKey(
                    "billing_payment_events.id" if invoice else "billing_refund_events.id"
                ),
                nullable=False,
            ),
            sa.Column("supersedes_id", sa.Uuid(), sa.ForeignKey(f"{table}.id"), unique=True),
            *extra,
            sa.CheckConstraint("sequence > 0", name="sequence_positive"),
            sa.UniqueConstraint("financial_year", "sequence"),
        )
        op.create_index(
            "uq_billing_invoice_payment" if invoice else "uq_billing_credit_refund",
            table,
            ["provider", "payment_ref"] if invoice else ["invoice_id", "refund_ref"],
            unique=True,
            postgresql_where=sa.text("supersedes_id IS NULL"),
        )
    for table in TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError("forward-only: tax documents are audit history")
