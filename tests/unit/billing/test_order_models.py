"""The S2a billing models: enum constants match their checks, and every table builds on SQLite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import CheckConstraint, create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.billing import order_models
from ac_platform.billing.models import ACTOR_TYPES, BillingAccount
from ac_platform.billing.order_models import (
    CANCEL_STATES,
    IDEMPOTENCY_SCOPES,
    INTERVALS,
    MODES,
    ORDER_KINDS,
    ORDER_STATUSES,
    PAYMENT_EVENT_KINDS,
    PAYMENT_EVENT_SOURCES,
    PROVIDER_SUBSCRIPTION_STATES,
    PROVIDERS,
    REFUND_STATES,
    SUBSCRIPTION_STATUSES,
    BillingCommandIdempotency,
    BillingOrder,
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingProviderSettings,
    BillingRefundEvent,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.tenancy.models import Tenant

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

TABLES = (
    "billing_provider_settings",
    "billing_orders",
    "billing_order_events",
    "billing_payment_events",
    "billing_command_idempotency",
    "billing_subscriptions",
    "billing_subscription_events",
    "billing_periods",
    "billing_refund_events",
)


def test_enum_constants_match_contract_c1() -> None:
    assert MODES == ("test", "live")
    assert PROVIDERS == ("fake", "razorpay", "cashfree", "payu")
    assert INTERVALS == ("month", "year")
    assert ORDER_KINDS == ("subscription", "top_up")
    assert ORDER_STATUSES == (
        "awaiting_payment",
        "confirming",
        "paid",
        "failed",
        "expired",
        "needs_review",
    )
    assert PAYMENT_EVENT_KINDS == (
        "payment.captured",
        "payment.failed",
        "subscription.activated",
        "subscription.charged",
        "subscription.state",
        "refund.processed",
        "refund.failed",
        "ignored",
    )
    assert PAYMENT_EVENT_SOURCES == ("webhook", "server_read")
    assert PROVIDER_SUBSCRIPTION_STATES == ("pending", "halted", "cancelled", "completed")
    assert IDEMPOTENCY_SCOPES == ("checkout", "verify", "cancel", "refund")
    assert SUBSCRIPTION_STATUSES == (
        "pending_authorisation",
        "active",
        "past_due",
        "halted",
        "cancelled",
        "ended",
    )
    assert CANCEL_STATES == ("none", "requested", "confirmed")
    assert REFUND_STATES == ("pending", "refunded", "refused")
    assert order_models.ACTOR_TYPES is ACTOR_TYPES


def _check_text(table: str, name: str) -> str:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in model_metadata().tables[table].constraints
        if isinstance(constraint, CheckConstraint)
    }
    return constraints[f"ck_{table}_{name}"]


@pytest.mark.parametrize(
    ("table", "check", "values"),
    [
        ("billing_provider_settings", "provider_supported", PROVIDERS),
        ("billing_provider_settings", "mode_supported", MODES),
        ("billing_orders", "kind_supported", ORDER_KINDS),
        ("billing_orders", "mode_supported", MODES),
        ("billing_orders", "interval_supported", INTERVALS),
        ("billing_order_events", "status_supported", ORDER_STATUSES),
        ("billing_order_events", "actor_type_supported", ACTOR_TYPES),
        ("billing_payment_events", "kind_supported", PAYMENT_EVENT_KINDS),
        ("billing_payment_events", "source_supported", PAYMENT_EVENT_SOURCES),
        ("billing_payment_events", "state_supported", PROVIDER_SUBSCRIPTION_STATES),
        ("billing_command_idempotency", "scope_supported", IDEMPOTENCY_SCOPES),
        ("billing_subscriptions", "mode_supported", MODES),
        ("billing_subscriptions", "interval_supported", INTERVALS),
        ("billing_subscription_events", "status_supported", SUBSCRIPTION_STATUSES),
        ("billing_subscription_events", "cancel_state_supported", CANCEL_STATES),
        ("billing_subscription_events", "actor_type_supported", ACTOR_TYPES),
        ("billing_refund_events", "state_supported", REFUND_STATES),
        ("billing_refund_events", "actor_type_supported", ACTOR_TYPES),
    ],
)
def test_every_enum_constant_is_exactly_the_database_check(
    table: str, check: str, values: tuple[str, ...]
) -> None:
    sql = _check_text(table, check)
    quoted = [f"'{value}'" for value in values]
    assert all(value in sql for value in quoted)
    # The check lists exactly these values: no extra literal hides in the SQL.
    assert sql.count("'") == 2 * len(values)


def test_every_table_is_registered() -> None:
    assert set(TABLES) <= set(model_metadata().tables)


@pytest.mark.parametrize("table", TABLES)
def test_every_constraint_and_index_name_fits_postgresql(table: str) -> None:
    # PostgreSQL truncates identifiers over 63 bytes; an over-long convention name in a
    # model would then no longer match the migration. Every name is explicit and short.
    target = model_metadata().tables[table]
    names = [constraint.name for constraint in target.constraints] + [
        index.name for index in target.indexes
    ]
    assert all(isinstance(name, str) and 0 < len(name) <= 63 for name in names), names


def test_every_model_builds_and_accepts_one_valid_row_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    tenant_id, person_id, account_id = uuid4(), uuid4(), uuid4()
    order_id, subscription_id, payment_event_id = uuid4(), uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Tenant(id=tenant_id, slug="public-test", name="Public"),
                Person(
                    id=person_id,
                    email="buyer@example.test",
                    status=PersonStatus.ACTIVE.value,
                    email_verified_at=T0,
                ),
            ]
        )
        session.flush()
        session.add(
            BillingAccount(
                id=account_id,
                tenant_id=tenant_id,
                person_id=person_id,
                kind="personal",
                created_at=T0,
            )
        )
        session.add(
            BillingProviderSettings(
                id=uuid4(),
                revision=1,
                provider="fake",
                mode="test",
                enabled=True,
                plan_refs={"personal:month": "plan_fake_month"},
                key_alias="AC_PAYMENTS_FAKE_KEY",
                actor_person_id=person_id,
                reason="enable the fake provider for tests",
                created_at=T0,
            )
        )
        session.add(
            BillingSubscription(
                id=subscription_id,
                account_id=account_id,
                mode="test",
                provider="fake",
                provider_subscription_ref="sub_fake_0001",
                provider_plan_ref="plan_fake_month",
                plan_key="personal",
                plan_name="Personal",
                plan_revision=1,
                interval="month",
                seats=1,
                included_minutes=800,
                amount_minor=249_900,
                currency="INR",
                gst_inclusive=True,
                renewal_needs_customer_approval=False,
                created_by_person_id=person_id,
                created_at=T0,
            )
        )
        session.flush()
        session.add(
            BillingOrder(
                id=order_id,
                account_id=account_id,
                kind="subscription",
                mode="test",
                provider="fake",
                order_ref="ac_order_00000001",
                provider_order_ref="order_fake_0001",
                subscription_id=subscription_id,
                plan_key="personal",
                plan_name="Personal",
                plan_revision=1,
                interval="month",
                seats=1,
                pack_key=None,
                minutes=800,
                amount_minor=249_900,
                currency="INR",
                gst_inclusive=True,
                created_by_person_id=person_id,
                created_at=T0,
                expires_at=T0 + timedelta(minutes=30),
            )
        )
        session.flush()
        session.add(
            BillingPaymentEvent(
                id=payment_event_id,
                provider="fake",
                provider_event_id="evt_fake_0001",
                kind="subscription.charged",
                source="webhook",
                order_id=order_id,
                subscription_id=subscription_id,
                payment_ref="pay_fake_0001",
                amount_minor=249_900,
                currency="INR",
                period_start=T0,
                period_end=T0 + timedelta(days=30),
                state=None,
                payload_sha256="a" * 64,
                received_at=T0 + timedelta(minutes=1),
                verified_at=T0 + timedelta(minutes=1),
                created_at=T0 + timedelta(minutes=1),
            )
        )
        session.flush()
        session.add_all(
            [
                BillingOrderEvent(
                    id=uuid4(),
                    order_id=order_id,
                    status="paid",
                    payment_event_id=payment_event_id,
                    detail=None,
                    actor_type="provider",
                    created_at=T0 + timedelta(minutes=1),
                ),
                BillingCommandIdempotency(
                    id=uuid4(),
                    account_id=account_id,
                    scope="checkout",
                    key="k-0001",
                    request_sha256="b" * 64,
                    response={"order_id": str(order_id)},
                    status_code=201,
                    created_at=T0,
                ),
                BillingSubscriptionEvent(
                    id=uuid4(),
                    subscription_id=subscription_id,
                    status="active",
                    cancel_state="none",
                    cancel_reason=None,
                    payment_event_id=payment_event_id,
                    detail=None,
                    actor_type="provider",
                    actor_person_id=None,
                    created_at=T0 + timedelta(minutes=1),
                ),
                BillingPeriod(
                    id=uuid4(),
                    subscription_id=subscription_id,
                    payment_event_id=payment_event_id,
                    period_start=T0,
                    period_end=T0 + timedelta(days=30),
                    created_at=T0 + timedelta(minutes=1),
                ),
                BillingRefundEvent(
                    id=uuid4(),
                    order_id=order_id,
                    payment_ref="pay_fake_0001",
                    state="pending",
                    provider_refund_ref=None,
                    amount_minor=249_900,
                    currency="INR",
                    reason="changed my mind within the window",
                    actor_type="person",
                    actor_person_id=person_id,
                    payment_event_id=None,
                    created_at=T0 + timedelta(days=1),
                ),
            ]
        )
    with Session(engine) as session:
        for table in TABLES:
            count = session.scalar(select(func.count()).select_from(model_metadata().tables[table]))
            assert count == 1, table
