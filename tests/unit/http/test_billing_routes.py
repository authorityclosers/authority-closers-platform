"""Route tests for the C1 billing HTTP adapter with a recording fake command service."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from ac_platform.application.settings import Settings
from ac_platform.billing.commands import Caller, CheckoutCommand, WebhookReceipt
from ac_platform.billing.errors import OrderNotFound, SubscriptionNotActive
from ac_platform.billing.views import (
    AccountName,
    CheckoutView,
    HostedView,
    MoneyView,
    OrderView,
    PeriodView,
    RefundState,
    RefundView,
    SubscriptionsView,
    SubscriptionView,
)
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.billing import install_billing_http, install_billing_webhook_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
ORDER_ID = str(UUID(int=1))
SUBSCRIPTION_ID = str(UUID(int=2))
ORIGIN = "https://app.authorityclosers.test"
HOST = "app.authorityclosers.test"
SUBSCRIPTION_BODY = {
    "kind": "subscription",
    "account": "personal",
    "plan_key": "personal",
    "interval": "month",
    "seats": 1,
}


class _Database:
    """A stand-in for the request transaction; the routes only pass it through."""


class _SessionContext:
    def __init__(self, database: object) -> None:
        self.database = database

    async def __aenter__(self) -> object:
        return self.database

    async def __aexit__(self, *_args: object) -> None:
        return None


class _TransactionContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _WebhookDatabase(_Database):
    def begin(self) -> _TransactionContext:
        return _TransactionContext()


def _order(order_id: UUID | str = ORDER_ID, *, status: str = "awaiting_payment") -> OrderView:
    paid = status == "paid"
    return OrderView(
        order_id=str(order_id),
        kind="subscription",
        account="personal",
        status=status,  # type: ignore[arg-type]
        mode="test",
        amount=MoneyView(249_900),
        plan_key="personal",
        plan_name="Personal",
        interval="month",
        seats=1,
        pack_key=None,
        minutes=800,
        subscription_id=SUBSCRIPTION_ID,
        created_at=NOW,
        paid_at=NOW + timedelta(minutes=1) if paid else None,
        refund=(
            RefundView(
                payment_id="fake_pay_1",
                state="available",
                refundable_until=NOW + timedelta(days=7, minutes=1),
            )
            if paid
            else None
        ),
    )


def _subscription(
    subscription_id: UUID | str = SUBSCRIPTION_ID,
    *,
    status: str = "active",
    cancel_state: str = "none",
) -> SubscriptionView:
    return SubscriptionView(
        subscription_id=str(subscription_id),
        account="personal",
        plan_key="personal",
        plan_name="Personal",
        interval="month",
        seats=1,
        amount=MoneyView(249_900),
        mode="test",
        status=status,  # type: ignore[arg-type]
        current_period=PeriodView(start=NOW, end=NOW + timedelta(days=30)),
        renews_at=NOW + timedelta(days=30) if cancel_state == "none" else None,
        cancel_at_period_end=cancel_state != "none",
        cancel_state=cancel_state,  # type: ignore[arg-type]
        renewal_needs_customer_approval=False,
        created_at=NOW,
    )


def _hosted() -> HostedView:
    return HostedView(
        provider="fake",
        kind="redirect",
        url=f"https://salesxray.example.test/account/billing/return?order={ORDER_ID}",
        params={"reference": "ac0123456789abcdef"},
        expires_at=NOW + timedelta(minutes=30),
    )


class _Commands:
    """Records every call; answers with canned views or raises the configured error."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error: Exception | None = None
        self.replayed = False
        self.refund_state: RefundState = "pending"

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.error is not None:
            raise self.error

    async def checkout(
        self, database: object, caller: Caller, command: CheckoutCommand
    ) -> CheckoutView:
        self._record("checkout", database=database, caller=caller, command=command)
        return CheckoutView(order=_order(), hosted=_hosted(), replayed=self.replayed)

    async def read_order(self, database: object, caller: Caller, order_id: UUID) -> OrderView:
        self._record("read_order", database=database, caller=caller, order_id=order_id)
        return _order(order_id)

    async def verify_order(
        self, database: object, caller: Caller, order_id: UUID, *, idempotency_key: str
    ) -> OrderView:
        self._record("verify_order", caller=caller, order_id=order_id, key=idempotency_key)
        return _order(order_id, status="paid")

    async def read_subscriptions(
        self, database: object, caller: Caller, account: AccountName
    ) -> SubscriptionsView:
        self._record("read_subscriptions", caller=caller, account=account)
        return SubscriptionsView(
            current=_subscription(), past=(_subscription(uuid4(), status="ended"),)
        )

    async def read_subscription(
        self, database: object, caller: Caller, subscription_id: UUID
    ) -> SubscriptionView:
        self._record("read_subscription", caller=caller, subscription_id=subscription_id)
        return _subscription(subscription_id)

    async def cancel_subscription(
        self,
        database: object,
        caller: Caller,
        subscription_id: UUID,
        *,
        reason: str | None,
        idempotency_key: str,
    ) -> SubscriptionView:
        self._record(
            "cancel_subscription",
            caller=caller,
            subscription_id=subscription_id,
            reason=reason,
            key=idempotency_key,
        )
        return _subscription(subscription_id, cancel_state="requested")

    async def refund_payment(
        self,
        database: object,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        self._record(
            "refund_payment",
            caller=caller,
            payment_id=payment_id,
            reason=reason,
            key=idempotency_key,
        )
        return RefundView(
            payment_id=payment_id,
            state=self.refund_state,
            refundable_until=NOW + timedelta(days=7),
        )

    async def receive_webhook(
        self, database: object, provider: str, headers: Any, raw_body: bytes
    ) -> WebhookReceipt:
        self._record(
            "receive_webhook",
            database=database,
            provider=provider,
            headers=dict(headers),
            raw_body=raw_body,
        )
        return WebhookReceipt(provider=provider, event_id="evt-1", outcome="paid", replayed=False)

    async def staff_refund_payment(
        self,
        database: object,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        view = await self.refund_payment(
            database, caller, payment_id, reason=reason, idempotency_key=idempotency_key
        )
        self.calls[-1] = ("staff_refund_payment", self.calls[-1][1])
        return view


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql+psycopg://unused:unused@localhost/unused",
        database_migrator_url="postgresql+psycopg://unused:unused@localhost/unused",
        session_token_pepper="billing-test-session-pepper-long-enough",  # noqa: S106
        oauth_transaction_secret="billing-test-oauth-secret-long-enough",  # noqa: S106
        public_app_url=ORIGIN,
        admin_app_url="https://admin.authorityclosers.test",
        api_url="https://api.authorityclosers.test",
    )


def _client(
    commands: _Commands | None, *, membership_role: str | None = "learner"
) -> tuple[TestClient, ActorContext, _WebhookDatabase]:
    actor = ActorContext(person_id=uuid4(), session_id=uuid4(), tenant_id=uuid4())
    webhook_database = _WebhookDatabase()

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, _Database()),
            identity=cast(Any, object()),
            resolved=ResolvedActorContext(
                actor=actor,
                membership_role=membership_role,
                person_revision=0,
                session_revision=0,
                tenant_revision=0,
                membership_revision=0,
            ),
            token="opaque-billing-session-token",  # noqa: S106
        )

    application = FastAPI()
    register_problem_handlers(application)
    install_billing_http(
        application, settings=_settings(), require_actor=require_actor, commands=commands
    )
    install_billing_webhook_http(
        application,
        sessions=lambda: _SessionContext(webhook_database),
        commands=commands,
    )
    return TestClient(application), actor, webhook_database


def _headers(key: str | None = "ck-1", *, origin: str = ORIGIN) -> dict[str, str]:
    headers = {"Host": HOST, "Origin": origin}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["code"] == code
    assert body["status"] == status
    assert set(body) == {"type", "title", "status", "detail", "instance", "code", "request_id"}


# ---- checkout --------------------------------------------------------------------


def test_checkout_requires_an_idempotency_key() -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers(None))
    _problem(response, 428, "idempotency_key_required")
    blank = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers("   "))
    _problem(blank, 428, "idempotency_key_required")
    long = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers("k" * 129))
    _problem(long, 422, "validation_failed")
    assert commands.calls == []


def test_checkout_requires_a_safe_origin() -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.post(
        "/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers(origin="https://evil.example")
    )
    _problem(response, 403, "request_origin_denied")
    assert commands.calls == []


@pytest.mark.parametrize(
    "body",
    [
        {**SUBSCRIPTION_BODY, "price": 1},
        {**SUBSCRIPTION_BODY, "seats": None},
        {
            "kind": "subscription",
            "account": "personal",
            "plan_key": "personal",
            "interval": "month",
        },
        {**SUBSCRIPTION_BODY, "pack_key": "personal_100"},
        {"kind": "top_up", "account": "personal", "plan_key": "personal"},
        {
            "kind": "top_up",
            "account": "personal",
            "plan_key": "personal",
            "pack_key": "x",
            "seats": 1,
        },
        {**SUBSCRIPTION_BODY, "seats": "1"},
        {**SUBSCRIPTION_BODY, "account": "team"},
        {**SUBSCRIPTION_BODY, "plan_key": "Personal"},
    ],
    ids=[
        "unknown-field",
        "seats-null",
        "seats-missing",
        "subscription-with-pack",
        "top-up-without-pack",
        "top-up-with-seats",
        "seats-as-text",
        "unknown-account",
        "plan-key-case",
    ],
)
def test_checkout_rejects_malformed_bodies(body: dict[str, object]) -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.post("/v1/checkout", json=body, headers=_headers())
    assert response.status_code == 422, response.text
    assert commands.calls == []


def test_checkout_returns_the_c1_shape_and_replays_with_200() -> None:
    client, actor, _database = _client(commands := _Commands())
    response = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers("ck-1"))
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert response.json() == {
        "order": {
            "order_id": ORDER_ID,
            "kind": "subscription",
            "account": "personal",
            "status": "awaiting_payment",
            "mode": "test",
            "amount": {"minor": 249900, "currency": "INR", "gst_inclusive": True},
            "tax": {
                "mode": "inclusive",
                "rate_basis_points": 1800,
                "taxable_minor": 211780,
                "gst_minor": 38120,
                "total_minor": 249900,
            },
            "plan_key": "personal",
            "plan_name": "Personal",
            "interval": "month",
            "seats": 1,
            "pack_key": None,
            "minutes": 800,
            "subscription_id": SUBSCRIPTION_ID,
            "created_at": "2026-10-01T09:00:00Z",
            "paid_at": None,
            "refund": None,
        },
        "hosted": {
            "provider": "fake",
            "kind": "redirect",
            "url": f"https://salesxray.example.test/account/billing/return?order={ORDER_ID}",
            "params": {"reference": "ac0123456789abcdef"},
            "expires_at": "2026-10-01T09:30:00Z",
        },
    }
    ((name, call),) = commands.calls
    assert name == "checkout"
    assert isinstance(call["database"], _Database)
    assert call["caller"] == Caller(
        person_id=actor.person_id,
        session_id=actor.session_id,
        tenant_id=actor.tenant_id,
        membership_role="learner",
        request_id=None,
    )
    canonical = (
        '{"account":"personal","interval":"month","kind":"subscription",'
        '"pack_key":null,"plan_key":"personal","seats":1}'
    )
    assert call["command"] == CheckoutCommand(
        kind="subscription",
        account="personal",
        plan_key="personal",
        interval="month",
        seats=1,
        pack_key=None,
        idempotency_key="ck-1",
        body_sha256=hashlib.sha256(canonical.encode()).hexdigest(),
    )

    commands.replayed = True
    replay = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers("ck-1"))
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert replay.headers["cache-control"] == "private, no-store"


def test_checkout_top_up_body_maps_to_the_command() -> None:
    client, _actor, _database = _client(commands := _Commands())
    body = {
        "kind": "top_up",
        "account": "personal",
        "plan_key": "personal",
        "pack_key": "personal_100",
    }
    response = client.post("/v1/checkout", json=body, headers=_headers("tk-1"))
    assert response.status_code == 201, response.text
    command = commands.calls[0][1]["command"]
    assert (command.kind, command.pack_key, command.interval, command.seats) == (
        "top_up",
        "personal_100",
        None,
        None,
    )
    rejected = client.post("/v1/checkout?debug=1", json=body, headers=_headers("tk-2"))
    _problem(rejected, 422, "validation_failed")


# ---- orders ------------------------------------------------------------------------


def test_read_order_is_private_no_store() -> None:
    client, actor, _database = _client(commands := _Commands())
    response = client.get(f"/v1/orders/{ORDER_ID}", headers={"Host": HOST})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["order_id"] == ORDER_ID
    assert response.json()["status"] == "awaiting_payment"
    ((name, call),) = commands.calls
    assert (name, call["order_id"], call["caller"].person_id) == (
        "read_order",
        UUID(ORDER_ID),
        actor.person_id,
    )
    rejected = client.get(f"/v1/orders/{ORDER_ID}?fields=all", headers={"Host": HOST})
    _problem(rejected, 422, "validation_failed")
    assert client.get("/v1/orders/not-a-uuid", headers={"Host": HOST}).status_code == 422


def test_order_not_found_is_a_problem_with_its_code() -> None:
    client, _actor, _database = _client(commands := _Commands())
    commands.error = OrderNotFound("That order does not exist.")
    response = client.get(f"/v1/orders/{ORDER_ID}", headers={"Host": HOST})
    _problem(response, 404, "order_not_found")
    assert response.json()["detail"] == "That order does not exist."


def test_verify_order_needs_key_and_origin_and_returns_the_order() -> None:
    client, _actor, _database = _client(commands := _Commands())
    missing = client.post(f"/v1/orders/{ORDER_ID}/verify", headers=_headers(None))
    _problem(missing, 428, "idempotency_key_required")
    response = client.post(f"/v1/orders/{ORDER_ID}/verify", headers=_headers("vk-1"))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["status"] == "paid"
    assert response.json()["refund"] == {
        "payment_id": "fake_pay_1",
        "refundable_until": "2026-10-08T09:01:00Z",
        "state": "available",
        "reason_code": None,
    }
    ((name, call),) = commands.calls
    assert (name, call["order_id"], call["key"]) == ("verify_order", UUID(ORDER_ID), "vk-1")


# ---- subscriptions -----------------------------------------------------------------


def test_subscriptions_read_defaults_to_personal_and_rejects_other_queries() -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.get("/v1/subscriptions", headers={"Host": HOST})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["current"]["subscription_id"] == SUBSCRIPTION_ID
    assert body["current"]["renews_at"] == "2026-10-31T09:00:00Z"
    assert [item["status"] for item in body["past"]] == ["ended"]
    assert commands.calls[-1][1]["account"] == "personal"
    organisation = client.get("/v1/subscriptions?account=organisation", headers={"Host": HOST})
    assert organisation.status_code == 200
    assert commands.calls[-1][1]["account"] == "organisation"
    assert client.get("/v1/subscriptions?account=team", headers={"Host": HOST}).status_code == 422
    rejected = client.get("/v1/subscriptions?account=personal&x=1", headers={"Host": HOST})
    _problem(rejected, 422, "validation_failed")
    single = client.get(f"/v1/subscriptions/{SUBSCRIPTION_ID}", headers={"Host": HOST})
    assert single.status_code == 200
    assert single.json()["cancel_state"] == "none"


def test_cancel_returns_the_subscription_and_maps_errors() -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.post(
        f"/v1/subscriptions/{SUBSCRIPTION_ID}/cancel",
        json={"reason": "  no longer needed  "},
        headers=_headers("cancel-1"),
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert (response.json()["cancel_at_period_end"], response.json()["cancel_state"]) == (
        True,
        "requested",
    )
    assert response.json()["renews_at"] is None
    ((name, call),) = commands.calls
    assert (name, call["subscription_id"], call["reason"], call["key"]) == (
        "cancel_subscription",
        UUID(SUBSCRIPTION_ID),
        "no longer needed",
        "cancel-1",
    )
    blank = client.post(
        f"/v1/subscriptions/{SUBSCRIPTION_ID}/cancel", json={"reason": "  "}, headers=_headers("c2")
    )
    assert blank.status_code == 200
    assert commands.calls[-1][1]["reason"] is None
    unknown = client.post(
        f"/v1/subscriptions/{SUBSCRIPTION_ID}/cancel", json={"why": "x"}, headers=_headers("c3")
    )
    assert unknown.status_code == 422
    commands.error = SubscriptionNotActive("This subscription is no longer active.")
    ended = client.post(
        f"/v1/subscriptions/{SUBSCRIPTION_ID}/cancel", json={}, headers=_headers("c4")
    )
    _problem(ended, 409, "subscription_not_active")


# ---- refunds ---------------------------------------------------------------------


def test_refund_is_202_while_pending_and_200_once_refunded() -> None:
    client, _actor, _database = _client(commands := _Commands())
    pending = client.post(
        "/v1/payments/fake_pay_1/refund", json={"reason": "changed my mind"}, headers=_headers("r1")
    )
    assert pending.status_code == 202, pending.text
    assert pending.headers["cache-control"] == "private, no-store"
    assert pending.json() == {
        "refund": {
            "payment_id": "fake_pay_1",
            "refundable_until": "2026-10-08T09:00:00Z",
            "state": "pending",
            "reason_code": None,
        }
    }
    ((name, call),) = commands.calls
    assert (name, call["payment_id"], call["reason"], call["key"]) == (
        "refund_payment",
        "fake_pay_1",
        "changed my mind",
        "r1",
    )
    commands.refund_state = "refunded"
    done = client.post(
        "/v1/payments/fake_pay_1/refund", json={"reason": "changed my mind"}, headers=_headers("r1")
    )
    assert done.status_code == 200
    assert done.json()["refund"]["state"] == "refunded"
    blank = client.post(
        "/v1/payments/fake_pay_1/refund", json={"reason": " "}, headers=_headers("r2")
    )
    _problem(blank, 422, "validation_failed")
    assert (
        client.post("/v1/payments/fake_pay_1/refund", json={}, headers=_headers("r3")).status_code
        == 422
    )
    odd = client.post("/v1/payments/pay%20one/refund", json={"reason": "x"}, headers=_headers("r4"))
    assert odd.status_code == 422
    assert len(commands.calls) == 2


# ---- webhooks -------------------------------------------------------------------


def test_unknown_webhook_provider_is_refused_before_any_command() -> None:
    client, _actor, _database = _client(commands := _Commands())
    response = client.post("/v1/payments/webhooks/unknown", content=b"{}")
    _problem(response, 422, "validation_failed")
    assert client.post("/v1/payments/webhooks/Fake", content=b"{}").status_code == 422
    query = client.post("/v1/payments/webhooks/fake?x=1", content=b"{}")
    _problem(query, 422, "validation_failed")
    assert commands.calls == []


def test_fake_webhook_passes_the_raw_body_and_lower_cased_headers_through() -> None:
    client, _actor, database = _client(commands := _Commands())
    raw = b'{"kind":"paid","order_reference":"ac0123456789abcdef"}'
    response = client.post(
        "/v1/payments/webhooks/fake",
        content=raw,
        headers={
            "X-Fake-Payment-Signature": "abc123",
            "X-Fake-Payment-Event-Id": "evt-1",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"received": True, "outcome": "paid", "replayed": False}
    ((name, call),) = commands.calls
    assert name == "receive_webhook"
    assert call["provider"] == "fake"
    assert call["raw_body"] == raw
    assert call["database"] is database
    headers = call["headers"]
    assert all(key == key.lower() for key in headers)
    assert headers["x-fake-payment-signature"] == "abc123"
    assert headers["x-fake-payment-event-id"] == "evt-1"
    assert headers["content-type"] == "application/json"


# ---- composition ----------------------------------------------------------------


def test_without_commands_no_billing_route_is_installed() -> None:
    client, _actor, _database = _client(None)
    paths = set(cast(Any, client.app).openapi()["paths"])
    assert not any(path.startswith("/v1/checkout") for path in paths)
    assert not any(path.startswith("/v1/orders") for path in paths)
    assert not any(path.startswith("/v1/subscriptions") for path in paths)
    assert not any(path.startswith("/v1/payments") for path in paths)
    missing = client.post("/v1/checkout", json=SUBSCRIPTION_BODY, headers=_headers())
    assert missing.status_code == 404
    assert missing.headers["content-type"] != "application/problem+json"
    assert client.post("/v1/payments/webhooks/fake", content=b"{}").status_code == 404


def test_with_commands_every_c1_route_is_installed() -> None:
    client, _actor, _database = _client(_Commands())
    paths = cast(Any, client.app).openapi()["paths"]
    assert {
        "/v1/checkout",
        "/v1/orders/{order_id}",
        "/v1/orders/{order_id}/verify",
        "/v1/subscriptions",
        "/v1/subscriptions/{subscription_id}",
        "/v1/subscriptions/{subscription_id}/cancel",
        "/v1/payments/{payment_id}/refund",
        "/v1/payments/webhooks/{provider}",
    } <= set(paths)
