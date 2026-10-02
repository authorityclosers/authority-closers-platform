"""Add billing provider settings, orders, order events, payment events and idempotency (S2a).

Every table is append-only: an order is an immutable copy of what was sold, and each
state change is a new ``billing_order_events`` row. ``subscription_id`` columns are
created here without their foreign key; 0064 adds it once ``billing_subscriptions``
exists.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261001_0063"
down_revision = "20261001_0062"
branch_labels = None
depends_on = None

TABLES = (
    "billing_provider_settings",
    "billing_orders",
    "billing_payment_events",
    "billing_order_events",
    "billing_command_idempotency",
)


def upgrade() -> None:
    op.create_table(
        "billing_provider_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("plan_refs", sa.JSON(), nullable=False),
        sa.Column("key_alias", sa.String(length=80), nullable=True),
        sa.Column("actor_person_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_billing_provider_settings_revision_positive")
        ),
        sa.CheckConstraint(
            "provider IN ('fake', 'razorpay', 'cashfree', 'payu')",
            name=op.f("ck_billing_provider_settings_provider_supported"),
        ),
        sa.CheckConstraint(
            "mode IN ('test', 'live')", name=op.f("ck_billing_provider_settings_mode_supported")
        ),
        sa.ForeignKeyConstraint(
            ["actor_person_id"],
            ["persons.id"],
            name="fk_billing_provider_settings_actor_person_id_persons",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name="fk_billing_provider_settings_audit_event_id_audit_events",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_provider_settings")),
        sa.UniqueConstraint("revision", name=op.f("uq_billing_provider_settings_revision")),
    )
    op.create_table(
        "billing_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("order_ref", sa.String(length=25), nullable=False),
        sa.Column("provider_order_ref", sa.String(length=64), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("plan_key", sa.String(length=40), nullable=False),
        sa.Column("plan_name", sa.String(length=80), nullable=False),
        sa.Column("plan_revision", sa.Integer(), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=True),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("pack_key", sa.String(length=40), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("gst_inclusive", sa.Boolean(), nullable=False),
        sa.Column("created_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('subscription', 'top_up')", name=op.f("ck_billing_orders_kind_supported")
        ),
        sa.CheckConstraint(
            "(kind = 'subscription' AND interval IS NOT NULL AND pack_key IS NULL) OR "
            "(kind = 'top_up' AND pack_key IS NOT NULL AND interval IS NULL)",
            name=op.f("ck_billing_orders_kind_shape"),
        ),
        sa.CheckConstraint(
            "mode IN ('test', 'live')", name=op.f("ck_billing_orders_mode_supported")
        ),
        sa.CheckConstraint(
            "length(order_ref) >= 8", name=op.f("ck_billing_orders_order_ref_length")
        ),
        sa.CheckConstraint(
            "plan_revision >= 1", name=op.f("ck_billing_orders_plan_revision_positive")
        ),
        sa.CheckConstraint(
            "interval IS NULL OR interval IN ('month', 'year')",
            name=op.f("ck_billing_orders_interval_supported"),
        ),
        sa.CheckConstraint("seats >= 1", name=op.f("ck_billing_orders_seats_positive")),
        sa.CheckConstraint("minutes >= 0", name=op.f("ck_billing_orders_minutes_not_negative")),
        sa.CheckConstraint("amount_minor >= 0", name=op.f("ck_billing_orders_amount_not_negative")),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_billing_orders_checkout_window")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["billing_accounts.id"],
            name="fk_billing_orders_account_id_billing_accounts",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_person_id"],
            ["persons.id"],
            name="fk_billing_orders_created_by_person_id_persons",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_orders")),
        sa.UniqueConstraint("order_ref", name=op.f("uq_billing_orders_order_ref")),
    )
    op.create_index("ix_billing_orders_account", "billing_orders", ["account_id", "created_at"])
    op.create_index(
        "ix_billing_orders_provider_order_ref",
        "billing_orders",
        ["provider_order_ref"],
        unique=True,
        postgresql_where=sa.text("provider_order_ref IS NOT NULL"),
        sqlite_where=sa.text("provider_order_ref IS NOT NULL"),
    )
    op.create_table(
        "billing_payment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("payment_ref", sa.String(length=64), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=True),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('payment.captured', 'payment.failed', 'subscription.activated', "
            "'subscription.charged', 'subscription.state', 'refund.processed', "
            "'refund.failed', 'ignored')",
            name=op.f("ck_billing_payment_events_kind_supported"),
        ),
        sa.CheckConstraint(
            "source IN ('webhook', 'server_read')",
            name=op.f("ck_billing_payment_events_source_supported"),
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor >= 0",
            name=op.f("ck_billing_payment_events_amount_not_negative"),
        ),
        sa.CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end > period_start",
            name=op.f("ck_billing_payment_events_period_window"),
        ),
        sa.CheckConstraint(
            "state IS NULL OR state IN ('pending', 'halted', 'cancelled', 'completed')",
            name=op.f("ck_billing_payment_events_state_supported"),
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name=op.f("ck_billing_payment_events_payload_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["billing_orders.id"],
            name="fk_billing_payment_events_order_id_billing_orders",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_payment_events")),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name=op.f("uq_billing_payment_events_provider"),
        ),
    )
    op.create_index("ix_billing_payment_events_order", "billing_payment_events", ["order_id"])
    op.create_table(
        "billing_order_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("payment_event_id", sa.Uuid(), nullable=True),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('awaiting_payment', 'confirming', 'paid', 'failed', 'expired', "
            "'needs_review')",
            name=op.f("ck_billing_order_events_status_supported"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('person', 'system', 'provider')",
            name=op.f("ck_billing_order_events_actor_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["billing_orders.id"],
            name="fk_billing_order_events_order_id_billing_orders",
        ),
        sa.ForeignKeyConstraint(
            ["payment_event_id"],
            ["billing_payment_events.id"],
            name="fk_billing_order_events_payment_event_id_billing_payment_events",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_order_events")),
    )
    op.create_index(
        "ix_billing_order_events_order", "billing_order_events", ["order_id", "created_at"]
    )
    op.create_table(
        "billing_command_idempotency",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('checkout', 'verify', 'cancel', 'refund')",
            name=op.f("ck_billing_command_idempotency_scope_supported"),
        ),
        sa.CheckConstraint(
            "length(key) >= 1", name=op.f("ck_billing_command_idempotency_key_length")
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name=op.f("ck_billing_command_idempotency_request_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["billing_accounts.id"],
            name="fk_billing_command_idempotency_account_id_billing_accounts",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_command_idempotency")),
        sa.UniqueConstraint(
            "account_id",
            "scope",
            "key",
            name=op.f("uq_billing_command_idempotency_account_id"),
        ),
    )
    for table in TABLES:
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION prevent_billing_mutation();"
            )
        )


def downgrade() -> None:
    raise RuntimeError("forward-only: billing orders and payment events are audit history")
