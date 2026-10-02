"""Real PostgreSQL proof for the S2a billing schema (migrations 0063 and 0064).

Migrations 0063 and 0064 apply after 0062 and leave no model drift; every new table
refuses UPDATE and DELETE; the key checks and unique constraints refuse bad rows;
and the foreign keys 0064 adds on the ``subscription_id`` columns exist and hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import (
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
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness

ROOT = Path(__file__).parents[2]
T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
NEW_TABLES = (
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


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@dataclass(frozen=True)
class Seeded:
    account_id: UUID
    person_id: UUID
    order_id: UUID
    subscription_id: UUID
    payment_event_id: UUID
    rows: dict[str, UUID]


def _payment_event(**overrides: object) -> BillingPaymentEvent:
    values: dict[str, object] = {
        "id": uuid4(),
        "provider": "fake",
        "provider_event_id": f"evt_{uuid4().hex[:12]}",
        "kind": "payment.captured",
        "source": "webhook",
        "order_id": None,
        "subscription_id": None,
        "payment_ref": None,
        "amount_minor": 249_900,
        "currency": "INR",
        "period_start": None,
        "period_end": None,
        "state": None,
        "payload_sha256": "c" * 64,
        "received_at": T0,
        "verified_at": T0,
        "created_at": T0,
    }
    values.update(overrides)
    return BillingPaymentEvent(**values)


def _order(account_id: UUID, **overrides: object) -> BillingOrder:
    values: dict[str, object] = {
        "id": uuid4(),
        "account_id": account_id,
        "kind": "top_up",
        "mode": "test",
        "provider": "fake",
        "order_ref": f"ac_{uuid4().hex[:20]}",
        "provider_order_ref": None,
        "subscription_id": None,
        "plan_key": "personal",
        "plan_name": "Personal",
        "plan_revision": 1,
        "interval": None,
        "seats": 1,
        "pack_key": "personal_100",
        "minutes": 100,
        "amount_minor": 49_900,
        "currency": "INR",
        "gst_inclusive": True,
        "created_by_person_id": None,
        "created_at": T0,
        "expires_at": T0 + timedelta(minutes=30),
    }
    values.update(overrides)
    return BillingOrder(**values)


@pytest.fixture(scope="module")
def seeded(postgres_harness: Engine) -> Seeded:
    """One valid row in every S2a table, so mutation tests have something to refuse."""

    tenant_id, person_id, account_id = uuid4(), uuid4(), uuid4()
    order_id, subscription_id, payment_event_id = uuid4(), uuid4(), uuid4()
    rows = {
        "billing_provider_settings": uuid4(),
        "billing_orders": order_id,
        "billing_order_events": uuid4(),
        "billing_payment_events": payment_event_id,
        "billing_command_idempotency": uuid4(),
        "billing_subscriptions": subscription_id,
        "billing_subscription_events": uuid4(),
        "billing_periods": uuid4(),
        "billing_refund_events": uuid4(),
    }
    with Session(postgres_harness) as session, session.begin():
        session.add_all(
            [
                Tenant(id=tenant_id, slug=tenant_id.hex, name="Disposable billing tenant"),
                Person(
                    id=person_id,
                    email=f"buyer-{person_id.hex}@example.test",
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
                id=rows["billing_provider_settings"],
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
            _order(
                account_id,
                id=order_id,
                kind="subscription",
                order_ref="ac_order_00000001",
                provider_order_ref="order_fake_0001",
                subscription_id=subscription_id,
                interval="month",
                pack_key=None,
                minutes=800,
                amount_minor=249_900,
                created_by_person_id=person_id,
            )
        )
        session.flush()
        session.add(
            _payment_event(
                id=payment_event_id,
                provider_event_id="evt_fake_0001",
                kind="subscription.charged",
                order_id=order_id,
                subscription_id=subscription_id,
                payment_ref="pay_fake_0001",
                period_start=T0,
                period_end=T0 + timedelta(days=30),
                received_at=T0 + timedelta(minutes=1),
                verified_at=T0 + timedelta(minutes=1),
                created_at=T0 + timedelta(minutes=1),
            )
        )
        session.flush()
        session.add_all(
            [
                BillingOrderEvent(
                    id=rows["billing_order_events"],
                    order_id=order_id,
                    status="paid",
                    payment_event_id=payment_event_id,
                    detail=None,
                    actor_type="provider",
                    created_at=T0 + timedelta(minutes=1),
                ),
                BillingCommandIdempotency(
                    id=rows["billing_command_idempotency"],
                    account_id=account_id,
                    scope="checkout",
                    key="k-0001",
                    request_sha256="b" * 64,
                    response={"order_id": str(order_id)},
                    status_code=201,
                    created_at=T0,
                ),
                BillingSubscriptionEvent(
                    id=rows["billing_subscription_events"],
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
                    id=rows["billing_periods"],
                    subscription_id=subscription_id,
                    payment_event_id=payment_event_id,
                    period_start=T0,
                    period_end=T0 + timedelta(days=30),
                    created_at=T0 + timedelta(minutes=1),
                ),
                BillingRefundEvent(
                    id=rows["billing_refund_events"],
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
    return Seeded(account_id, person_id, order_id, subscription_id, payment_event_id, rows)


def test_0063_and_0064_apply_after_0062_and_are_the_head(postgres_harness: Engine) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("20261001_0063").down_revision == "20261001_0062"
    assert scripts.get_revision("20261001_0064").down_revision == "20261001_0063"
    assert scripts.get_current_head() == "20261002_0067"
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261002_0067"
        present = set(inspect(connection).get_table_names())
    assert set(NEW_TABLES) <= present


def test_billing_tables_have_no_model_drift(postgres_harness: Engine) -> None:
    with postgres_harness.connect() as connection:
        drift = compare_metadata(MigrationContext.configure(connection), model_metadata())
    billing = [entry for entry in drift if "billing_" in repr(entry)]
    assert billing == []
    assert drift == []


@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_has_the_append_only_trigger(postgres_harness: Engine, table: str) -> None:
    with postgres_harness.connect() as connection:
        found = connection.scalar(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname = :name "
                "AND tgrelid = to_regclass(:table)"
            ),
            {"name": f"{table}_append_only", "table": table},
        )
    assert found == 1


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize("table", NEW_TABLES)
def test_every_new_table_refuses_update_and_delete(
    postgres_harness: Engine, seeded: Seeded, table: str, operation: str
) -> None:
    target = model_metadata().tables[table]
    row_id = seeded.rows[table]
    statement = (
        update(target).where(target.c.id == row_id).values(created_at=func.now())
        if operation == "update"
        else delete(target).where(target.c.id == row_id)
    )
    with (
        pytest.raises(DBAPIError, match="billing history is append-only"),
        postgres_harness.begin() as connection,
    ):
        connection.execute(statement)
    with postgres_harness.connect() as connection:
        remaining = select(func.count()).select_from(target).where(target.c.id == row_id)
        assert connection.scalar(remaining) == 1


def test_top_up_order_with_an_interval_is_refused(postgres_harness: Engine, seeded: Seeded) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_billing_orders_kind_shape"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_order(seeded.account_id, kind="top_up", interval="month"))


def test_subscription_order_without_an_interval_is_refused(
    postgres_harness: Engine, seeded: Seeded
) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_billing_orders_kind_shape"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_order(seeded.account_id, kind="subscription", interval=None, pack_key=None))


def test_payment_event_period_must_end_after_it_starts(
    postgres_harness: Engine, seeded: Seeded
) -> None:
    with (
        pytest.raises(IntegrityError, match="ck_billing_payment_events_period_window"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_payment_event(kind="subscription.charged", period_start=T0, period_end=T0))


def test_duplicate_provider_event_is_refused(postgres_harness: Engine, seeded: Seeded) -> None:
    with (
        pytest.raises(IntegrityError, match="uq_billing_payment_events_provider"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_payment_event(provider="fake", provider_event_id="evt_fake_0001"))


def test_duplicate_idempotency_key_is_refused(postgres_harness: Engine, seeded: Seeded) -> None:
    with (
        pytest.raises(IntegrityError, match="uq_billing_command_idempotency_account_id"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(
            BillingCommandIdempotency(
                id=uuid4(),
                account_id=seeded.account_id,
                scope="checkout",
                key="k-0001",
                request_sha256="d" * 64,
                response={"order_id": "other"},
                status_code=201,
                created_at=T0,
            )
        )


def test_same_idempotency_key_is_allowed_in_another_scope(
    postgres_harness: Engine, seeded: Seeded
) -> None:
    with Session(postgres_harness) as session, session.begin():
        session.add(
            BillingCommandIdempotency(
                id=uuid4(),
                account_id=seeded.account_id,
                scope="verify",
                key="k-0001",
                request_sha256="e" * 64,
                response={"order_id": str(seeded.order_id)},
                status_code=200,
                created_at=T0,
            )
        )


def test_duplicate_provider_order_ref_is_refused_but_null_is_not_unique(
    postgres_harness: Engine, seeded: Seeded
) -> None:
    with Session(postgres_harness) as session, session.begin():
        session.add(_order(seeded.account_id, provider_order_ref=None))
        session.add(_order(seeded.account_id, provider_order_ref=None))
    with (
        pytest.raises(IntegrityError, match="ix_billing_orders_provider_order_ref"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_order(seeded.account_id, provider_order_ref="order_fake_0001"))


@pytest.mark.parametrize(
    ("table", "name"),
    [
        ("billing_orders", "fk_billing_orders_subscription_id_billing_subscriptions"),
        (
            "billing_payment_events",
            "fk_billing_payment_events_subscription_id_billing_subscriptions",
        ),
    ],
)
def test_0064_adds_the_subscription_foreign_keys(
    postgres_harness: Engine, table: str, name: str
) -> None:
    with postgres_harness.connect() as connection:
        foreign_keys = {
            key["name"]: (
                key["constrained_columns"],
                key["referred_table"],
                key["referred_columns"],
            )
            for key in inspect(connection).get_foreign_keys(table)
        }
    assert foreign_keys[name] == (["subscription_id"], "billing_subscriptions", ["id"])


def test_order_and_payment_event_subscription_ids_are_enforced(
    postgres_harness: Engine, seeded: Seeded
) -> None:
    with (
        pytest.raises(IntegrityError, match="fk_billing_orders_subscription_id"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(
            _order(
                seeded.account_id,
                kind="subscription",
                interval="month",
                pack_key=None,
                subscription_id=uuid4(),
            )
        )
    with (
        pytest.raises(IntegrityError, match="fk_billing_payment_events_subscription_id"),
        Session(postgres_harness) as session,
        session.begin(),
    ):
        session.add(_payment_event(subscription_id=uuid4()))
