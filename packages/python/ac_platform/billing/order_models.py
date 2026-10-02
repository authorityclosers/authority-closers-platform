"""Billing orders, payment events, subscriptions, periods and refunds (Contract C1, S2a).

Orders and subscriptions are immutable copies of what was sold; every state change
is a new row in the matching ``_events`` table, and the current status is the latest
event. Payment events hold one row per verified provider event or verified server
read. None of these tables grants access: only the ledger (``models.py``) does, and
only a verified payment event writes a ledger lot. Every table carries the
``BEFORE UPDATE OR DELETE`` trigger from migration 0062.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ac_platform.billing.models import ACTOR_TYPES
from ac_platform.db.base import Base

MODES = ("test", "live")
PROVIDERS = ("fake", "razorpay", "cashfree", "payu")
INTERVALS = ("month", "year")
ORDER_KINDS = ("subscription", "top_up")
ORDER_STATUSES = ("awaiting_payment", "confirming", "paid", "failed", "expired", "needs_review")
PAYMENT_EVENT_KINDS = (
    "payment.captured",
    "payment.failed",
    "subscription.activated",
    "subscription.charged",
    "subscription.state",
    "refund.processed",
    "refund.failed",
    "ignored",
)
PAYMENT_EVENT_SOURCES = ("webhook", "server_read")
PROVIDER_SUBSCRIPTION_STATES = ("pending", "halted", "cancelled", "completed")
IDEMPOTENCY_SCOPES = ("checkout", "verify", "cancel", "refund")
SUBSCRIPTION_STATUSES = (
    "pending_authorisation",
    "active",
    "past_due",
    "halted",
    "cancelled",
    "ended",
)
CANCEL_STATES = ("none", "requested", "confirmed")
REFUND_STATES = ("pending", "refunded", "refused")

_MODES = "('test', 'live')"
_ACTOR_TYPES = "('person', 'system', 'provider')"


class BillingProviderSettings(Base):
    """One append-only version of the payment provider settings; the current row is the
    highest revision. ``key_alias`` names the settings alias holding the key, never a key."""

    __tablename__ = "billing_provider_settings"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="revision_positive"),
        CheckConstraint(
            "provider IN ('fake', 'razorpay', 'cashfree', 'payu')", name="provider_supported"
        ),
        CheckConstraint(f"mode IN {_MODES}", name="mode_supported"),
        UniqueConstraint("revision"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(8))
    enabled: Mapped[bool] = mapped_column(Boolean)
    plan_refs: Mapped[dict[str, Any]] = mapped_column(JSON)
    key_alias: Mapped[str | None] = mapped_column(String(80))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    reason: Mapped[str | None] = mapped_column(String(500))
    audit_event_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("audit_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingOrder(Base):
    """Immutable copy of one checkout: what was sold, for how much, to which account."""

    __tablename__ = "billing_orders"
    __table_args__ = (
        CheckConstraint("kind IN ('subscription', 'top_up')", name="kind_supported"),
        CheckConstraint(
            "(kind = 'subscription' AND interval IS NOT NULL AND pack_key IS NULL) OR "
            "(kind = 'top_up' AND pack_key IS NOT NULL AND interval IS NULL)",
            name="kind_shape",
        ),
        CheckConstraint(f"mode IN {_MODES}", name="mode_supported"),
        CheckConstraint("length(order_ref) >= 8", name="order_ref_length"),
        CheckConstraint("plan_revision >= 1", name="plan_revision_positive"),
        CheckConstraint(
            "interval IS NULL OR interval IN ('month', 'year')", name="interval_supported"
        ),
        CheckConstraint("seats >= 1", name="seats_positive"),
        CheckConstraint("minutes >= 0", name="minutes_not_negative"),
        CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        CheckConstraint("expires_at > created_at", name="checkout_window"),
        UniqueConstraint("order_ref"),
        Index("ix_billing_orders_account", "account_id", "created_at"),
        Index(
            "ix_billing_orders_provider_order_ref",
            "provider_order_ref",
            unique=True,
            postgresql_where=text("provider_order_ref IS NOT NULL"),
            sqlite_where=text("provider_order_ref IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("billing_accounts.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(32))
    order_ref: Mapped[str] = mapped_column(String(25))
    provider_order_ref: Mapped[str | None] = mapped_column(String(64))
    subscription_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("billing_subscriptions.id")
    )
    plan_key: Mapped[str] = mapped_column(String(40))
    plan_name: Mapped[str] = mapped_column(String(80))
    plan_revision: Mapped[int] = mapped_column(Integer)
    interval: Mapped[str | None] = mapped_column(String(8))
    seats: Mapped[int] = mapped_column(Integer)
    pack_key: Mapped[str | None] = mapped_column(String(40))
    minutes: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    gst_inclusive: Mapped[bool] = mapped_column(Boolean)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingPaymentEvent(Base):
    """One verified provider event or verified server read, normalised per section E."""

    __tablename__ = "billing_payment_events"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('payment.captured', 'payment.failed', 'subscription.activated', "
            "'subscription.charged', 'subscription.state', 'refund.processed', "
            "'refund.failed', 'ignored')",
            name="kind_supported",
        ),
        CheckConstraint("source IN ('webhook', 'server_read')", name="source_supported"),
        CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="amount_not_negative"),
        CheckConstraint(
            "period_end IS NULL OR period_start IS NULL OR period_end > period_start",
            name="period_window",
        ),
        CheckConstraint(
            "state IS NULL OR state IN ('pending', 'halted', 'cancelled', 'completed')",
            name="state_supported",
        ),
        CheckConstraint("length(payload_sha256) = 64", name="payload_sha256_length"),
        UniqueConstraint("provider", "provider_event_id"),
        Index("ix_billing_payment_events_order", "order_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(16))
    order_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("billing_orders.id"))
    subscription_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("billing_subscriptions.id")
    )
    payment_ref: Mapped[str | None] = mapped_column(String(64))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[str | None] = mapped_column(String(24))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingOrderEvent(Base):
    """One order status change; the latest row is the order's current status."""

    __tablename__ = "billing_order_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_payment', 'confirming', 'paid', 'failed', 'expired', "
            "'needs_review')",
            name="status_supported",
        ),
        CheckConstraint(f"actor_type IN {_ACTOR_TYPES}", name="actor_type_supported"),
        Index("ix_billing_order_events_order", "order_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("billing_orders.id"))
    status: Mapped[str] = mapped_column(String(24))
    payment_event_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("billing_payment_events.id")
    )
    detail: Mapped[str | None] = mapped_column(String(500))
    actor_type: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingCommandIdempotency(Base):
    """First result of a billing POST per (account, scope, Idempotency-Key)."""

    __tablename__ = "billing_command_idempotency"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('checkout', 'verify', 'cancel', 'refund')", name="scope_supported"
        ),
        CheckConstraint("length(key) >= 1", name="key_length"),
        CheckConstraint("length(request_sha256) = 64", name="request_sha256_length"),
        UniqueConstraint("account_id", "scope", "key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("billing_accounts.id", ondelete="RESTRICT")
    )
    scope: Mapped[str] = mapped_column(String(24))
    key: Mapped[str] = mapped_column(String(128))
    request_sha256: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict[str, Any]] = mapped_column(JSON)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingSubscription(Base):
    """Immutable copy of one authorised subscription: plan, interval, seats and price."""

    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        CheckConstraint(f"mode IN {_MODES}", name="mode_supported"),
        CheckConstraint("plan_revision >= 1", name="plan_revision_positive"),
        CheckConstraint("interval IN ('month', 'year')", name="interval_supported"),
        CheckConstraint("seats >= 1", name="seats_positive"),
        CheckConstraint("included_minutes >= 0", name="included_minutes_not_negative"),
        CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        Index("ix_billing_subscriptions_account", "account_id", "created_at"),
        Index(
            "ix_billing_subscriptions_provider_subscription_ref",
            "provider_subscription_ref",
            unique=True,
            postgresql_where=text("provider_subscription_ref IS NOT NULL"),
            sqlite_where=text("provider_subscription_ref IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    account_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("billing_accounts.id", ondelete="RESTRICT")
    )
    mode: Mapped[str] = mapped_column(String(8))
    provider: Mapped[str] = mapped_column(String(32))
    provider_subscription_ref: Mapped[str | None] = mapped_column(String(64))
    provider_plan_ref: Mapped[str | None] = mapped_column(String(64))
    plan_key: Mapped[str] = mapped_column(String(40))
    plan_name: Mapped[str] = mapped_column(String(80))
    plan_revision: Mapped[int] = mapped_column(Integer)
    interval: Mapped[str] = mapped_column(String(8))
    seats: Mapped[int] = mapped_column(Integer)
    included_minutes: Mapped[int] = mapped_column(Integer)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    gst_inclusive: Mapped[bool] = mapped_column(Boolean)
    renewal_needs_customer_approval: Mapped[bool] = mapped_column(Boolean)
    created_by_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingSubscriptionEvent(Base):
    """One subscription status change; the latest row is the current status."""

    __tablename__ = "billing_subscription_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_authorisation', 'active', 'past_due', 'halted', "
            "'cancelled', 'ended')",
            name="status_supported",
        ),
        CheckConstraint(
            "cancel_state IN ('none', 'requested', 'confirmed')", name="cancel_state_supported"
        ),
        CheckConstraint(f"actor_type IN {_ACTOR_TYPES}", name="actor_type_supported"),
        Index("ix_billing_subscription_events_subscription", "subscription_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    # Explicit names: the convention names would exceed PostgreSQL's 63-character limit.
    subscription_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "billing_subscriptions.id", name="fk_billing_subscription_events_subscription_id"
        ),
    )
    status: Mapped[str] = mapped_column(String(24))
    cancel_state: Mapped[str] = mapped_column(String(16))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    payment_event_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "billing_payment_events.id", name="fk_billing_subscription_events_payment_event_id"
        ),
    )
    detail: Mapped[str | None] = mapped_column(String(500))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingPeriod(Base):
    """One paid provider period per verified charge. Ledger lots reference
    ``period:<id>`` (monthly) and ``period:<id>:m<k>`` (yearly, k = 0-11)."""

    __tablename__ = "billing_periods"
    __table_args__ = (
        CheckConstraint("period_end > period_start", name="period_window"),
        UniqueConstraint("payment_event_id"),
        UniqueConstraint("subscription_id", "period_start"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    subscription_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("billing_subscriptions.id"))
    payment_event_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("billing_payment_events.id"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingRefundEvent(Base):
    """One refund state change on a paid order (C1 section 4)."""

    __tablename__ = "billing_refund_events"
    __table_args__ = (
        CheckConstraint("state IN ('pending', 'refunded', 'refused')", name="state_supported"),
        CheckConstraint("amount_minor >= 0", name="amount_not_negative"),
        CheckConstraint(f"actor_type IN {_ACTOR_TYPES}", name="actor_type_supported"),
        Index("ix_billing_refund_events_order", "order_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("billing_orders.id"))
    payment_ref: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    provider_refund_ref: Mapped[str | None] = mapped_column(String(64))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(500))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_person_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("persons.id"))
    # Explicit name: the convention name would exceed PostgreSQL's 63-character limit.
    payment_event_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("billing_payment_events.id", name="fk_billing_refund_events_payment_event_id"),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "ACTOR_TYPES",
    "CANCEL_STATES",
    "IDEMPOTENCY_SCOPES",
    "INTERVALS",
    "MODES",
    "ORDER_KINDS",
    "ORDER_STATUSES",
    "PAYMENT_EVENT_KINDS",
    "PAYMENT_EVENT_SOURCES",
    "PROVIDERS",
    "PROVIDER_SUBSCRIPTION_STATES",
    "REFUND_STATES",
    "SUBSCRIPTION_STATUSES",
    "BillingCommandIdempotency",
    "BillingOrder",
    "BillingOrderEvent",
    "BillingPaymentEvent",
    "BillingPeriod",
    "BillingProviderSettings",
    "BillingRefundEvent",
    "BillingSubscription",
    "BillingSubscriptionEvent",
]
