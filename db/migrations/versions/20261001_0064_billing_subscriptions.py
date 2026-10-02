"""Add billing subscriptions, subscription events, periods and refund events (S2a).

A subscription is an immutable copy of what was authorised; its state lives in
``billing_subscription_events``. Each verified charge writes one ``billing_periods``
row, which the ledger lots reference. This migration also adds the foreign keys
from 0063's ``subscription_id`` columns to ``billing_subscriptions``.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0064"
down_revision = "20261001_0063"
branch_labels = None
depends_on = None

TABLES = (
    "billing_subscriptions",
    "billing_subscription_events",
    "billing_periods",
    "billing_refund_events",
)


def upgrade() -> None:
    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_subscription_ref", sa.String(length=64), nullable=True),
        sa.Column("provider_plan_ref", sa.String(length=64), nullable=True),
        sa.Column("plan_key", sa.String(length=40), nullable=False),
        sa.Column("plan_name", sa.String(length=80), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("included_minutes", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("gst_inclusive", sa.Boolean(), nullable=False),
        sa.Column("renewal_needs_customer_approval", sa.Boolean(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "mode IN ('test', 'live')", name=op.f("ck_billing_subscriptions_mode_supported")
        ),
        sa.CheckConstraint(
            "plan_revision >= 1", name=op.f("ck_billing_subscriptions_plan_revision_positive")
        ),
        sa.CheckConstraint(
            "interval IN ('month', 'year')",
            name=op.f("ck_billing_subscriptions_interval_supported"),
        ),
        sa.CheckConstraint("seats >= 1", name=op.f("ck_billing_subscriptions_seats_positive")),
        sa.CheckConstraint(
            "included_minutes >= 0",
            name=op.f("ck_billing_subscriptions_included_minutes_not_negative"),
        ),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_billing_subscriptions_amount_not_negative")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["billing_accounts.id"],
            name="fk_billing_subscriptions_account_id_billing_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_person_id"],
            ["persons.id"],
            name="fk_billing_subscriptions_created_by_person_id_persons",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_subscriptions")),
    )
    op.create_index(
        "ix_billing_subscriptions_account",
        "billing_subscriptions",
        ["account_id", "created_at"],
    )
    op.create_index(
        "ix_billing_subscriptions_provider_subscription_ref",
        "billing_subscriptions",
        ["provider_subscription_ref"],
        unique=True,
        postgresql_where=sa.text("provider_subscription_ref IS NOT NULL"),
        sqlite_where=sa.text("provider_subscription_ref IS NOT NULL"),
    )
    op.create_table(
        "billing_subscription_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("cancel_state", sa.String(length=16), nullable=False),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column("payment_event_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending_authorisation', 'active', 'past_due', 'halted', "
            "'cancelled', 'ended')",
            name=op.f("ck_billing_subscription_events_status_supported"),
        ),
        sa.CheckConstraint(
            "cancel_state IN ('none', 'requested', 'confirmed')",
            name=op.f("ck_billing_subscription_events_cancel_state_supported"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'system', 'provider')",
            name=op.f("ck_billing_subscription_events_actor_type_supported"),
        ),
        # These two convention names would exceed PostgreSQL's 63-character limit.
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["billing_subscriptions.id"],
            name="fk_billing_subscription_events_subscription_id",
        ),
        sa.ForeignKeyConstraint(
            ["payment_event_id"],
            ["billing_payment_events.id"],
            name="fk_billing_subscription_events_payment_event_id",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_billing_subscription_events_actor_person_id_persons",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_subscription_events")),
    )
    op.create_index(
        "ix_billing_subscription_events_subscription",
        "billing_subscription_events",
        ["subscription_id", "created_at"],
    )
    op.create_table(
        "billing_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("payment_event_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "period_end > period_start", name=op.f("ck_billing_periods_period_window")
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["billing_subscriptions.id"],
            name="fk_billing_periods_subscription_id_billing_subscriptions",
        ),
        sa.ForeignKeyConstraint(
            ["payment_event_id"],
            ["billing_payment_events.id"],
            name="fk_billing_periods_payment_event_id_billing_payment_events",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_periods")),
        sa.UniqueConstraint("payment_event_id", name=op.f("uq_billing_periods_payment_event_id")),
        sa.UniqueConstraint(
            "subscription_id", "period_start", name=op.f("uq_billing_periods_subscription_id")
        ),
    )
    op.create_table(
        "billing_refund_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("payment_ref", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("provider_refund_ref", sa.String(length=64), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("payment_event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending', 'refunded', 'refused')",
            name=op.f("ck_billing_refund_events_state_supported"),
        ),
        sa.CheckConstraint(
            "amount_minor >= 0", name=op.f("ck_billing_refund_events_amount_not_negative")
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'system', 'provider')",
            name=op.f("ck_billing_refund_events_actor_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["billing_orders.id"],
            name="fk_billing_refund_events_order_id_billing_orders",
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_billing_refund_events_actor_person_id_persons",
        ),
        # The convention name would exceed PostgreSQL's 63-character limit.
        sa.ForeignKeyConstraint(
            ["payment_event_id"],
            ["billing_payment_events.id"],
            name="fk_billing_refund_events_payment_event_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_refund_events")),
    )
    op.create_index(
        "ix_billing_refund_events_order", "billing_refund_events", ["order_id", "created_at"]
    )
    op.create_foreign_key(
        "fk_billing_orders_subscription_id_billing_subscriptions",
        "billing_orders",
        "billing_subscriptions",
        ["subscription_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_billing_payment_events_subscription_id_billing_subscriptions",
        "billing_payment_events",
        "billing_subscriptions",
        ["subscription_id"],
        ["id"],
    )
    for table in TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError("forward-only: billing subscriptions and periods are audit history")
