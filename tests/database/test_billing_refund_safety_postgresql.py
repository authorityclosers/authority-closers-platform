"""AUT-719 refund durability, exact signed correlation and C1 replay regressions.

Fictional accounts only, disposable PostgreSQL and mock provider transport.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from dataclasses import replace
from uuid import UUID, uuid4

import httpx
import pytest

from ac_platform.billing.application import BillingApplication
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.errors import BillingIdempotencyConflict, BillingRateLimited, PaymentUsed
from ac_platform.billing.order_models import BillingOrder, BillingOrderEvent, BillingSubscription
from ac_platform.billing.periods import add_months
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.payments.ports import (
    AmbiguousPaymentOutcomeError,
    Money,
    PaymentEventKind,
    PaymentMode,
    RefundReceipt,
    RefundState,
)
from ac_platform.payments.razorpay import RazorpayAdapter
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.providers.ports import PermanentProviderError
from tests.database.test_billing_settlement_postgresql import (
    PACK_PRICE,
    PACK_SECONDS,
    PERIOD_SECONDS,
    RETURN_URL_BASE,
    T0,
    TRIAL_SECONDS,
    Lab,
    World,
    caller,
    scenario,
    source,
    top_up_command,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world


def restart(lab: Lab, providers: PaymentProviderRegistry | None = None) -> BillingApplication:
    return BillingApplication(
        CheckoutService(
            catalogue=lab.app.service.catalogue,
            providers=providers or lab.app.service.providers,
            public_learner_tenant_id=lab.world.public_tenant_id,
            operations_tenant_id=lab.world.operations_tenant_id,
            return_url_base=RETURN_URL_BASE,
            clock=lab.world.clock,
        )
    )


async def pending_refund(**kwargs) -> RefundReceipt:
    return RefundReceipt(
        provider="fake",
        provider_refund_ref="fake_refund_expected",
        state=RefundState.PENDING,
        money=kwargs["money"],
    )


@pytest.mark.parametrize("crash", [False, True], ids=["timeout", "crash"])
def test_refund_intent_survives_provider_failure_and_caller_rollback(
    postgres_harness, world: World, monkeypatch, crash: bool
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, "lost-answer")
        calls = 0

        async def lost_answer(**kwargs):
            nonlocal calls
            calls += 1
            # Another connection can see the committed hold while the call runs.
            assert (await lab.refund_events(paid.order_id))[0].state == "pending"
            assert (await lab.lots(learner))[f"order:{paid.order_id}"].capacity == 0
            assert kwargs["idempotency_key"]
            if crash:
                raise RuntimeError("fictional process crash after provider acceptance")
            raise AmbiguousPaymentOutcomeError("fictional provider timeout")

        monkeypatch.setattr(world.fake, "refund", lost_answer)
        if crash:
            with pytest.raises(RuntimeError, match="fictional process crash"):
                await lab.refund(learner, paid.payment_ref, key="durable")
        else:
            async with lab.sessions() as database:
                with pytest.raises(RuntimeError, match="caller rollback"):
                    async with database.begin():
                        view = await lab.app.refund_payment(
                            database,
                            caller(learner),
                            paid.payment_ref,
                            reason="changed my mind",
                            idempotency_key="durable",
                        )
                        assert view.state == "pending"
                        raise RuntimeError("caller rollback")
        recovered = restart(lab)
        async with lab.sessions() as database, database.begin():
            view = await recovered.refund_payment(
                database,
                caller(learner),
                paid.payment_ref,
                reason="changed my mind",
                idempotency_key="durable",
            )
            assert view.state == "pending"
        with pytest.raises(BillingIdempotencyConflict):
            await lab.refund(learner, paid.payment_ref, key="durable", reason="different")
        assert (await lab.refund(learner, paid.payment_ref, key="new-key")).state == "pending"
        assert calls == 1
        assert (await lab.allowance(learner))["available_seconds"] == TRIAL_SECONDS + PERIOD_SECONDS
        # An unknown refund id alone is insufficient after a lost response.
        original = (await lab.payment_events(paid.order_id))[0]
        wrong_receipt = world.fake.signed_event(
            kind=PaymentEventKind.REFUNDED,
            event_id=f"wrong-receipt:{paid.order_ref}",
            order_reference=paid.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=paid.payment_ref,
            provider_refund_ref="fake_refund_unrelated",
            refund_reference="another-command",
        )
        assert await lab.webhook(*wrong_receipt) == ("needs_review", False)
        assert (await lab.refund_events(paid.order_id))[-1].state == "pending"
        callback = world.fake.signed_event(
            kind=PaymentEventKind.REFUNDED,
            event_id=f"recover:{paid.order_ref}",
            order_reference=paid.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=paid.payment_ref,
            provider_refund_ref="fake_refund_recovered",
            refund_reference=lab.app.settlement._refund_key(original),
        )
        assert await lab.webhook(*callback) == ("refund", False)
        assert (await lab.refund_events(paid.order_id))[-1].state == "refunded"
        assert (await lab.lots(learner))[f"order:{paid.order_id}"].capacity == 0
        assert calls == 1

    scenario(postgres_harness, world, exercise)


@pytest.mark.parametrize("kind", [PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED])
@pytest.mark.parametrize(
    "mismatch", ["amount", "currency", "payment", "refund", "missing", "provider"]
)
def test_signed_mismatch_keeps_the_exact_pending_hold(
    postgres_harness, world: World, monkeypatch, kind: PaymentEventKind, mismatch: str
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, f"mismatch-{kind}-{mismatch}")
        monkeypatch.setattr(world.fake, "refund", pending_refund)
        accepted = await lab.refund(learner, paid.payment_ref, key="match")
        before = await lab.entries(learner)
        headers, body = world.fake.signed_event(
            kind=kind,
            event_id=f"wrong:{paid.order_ref}",
            order_reference=paid.order_ref,
            money=Money(1, "INR")
            if mismatch == "amount"
            else Money(PACK_PRICE.amount_minor, "USD")
            if mismatch == "currency"
            else PACK_PRICE,
            provider_payment_ref="fake_payment_other"
            if mismatch == "payment"
            else paid.payment_ref,
            provider_refund_ref=None
            if mismatch == "missing"
            else "fake_refund_wrong"
            if mismatch == "refund"
            else "fake_refund_expected",
        )
        if mismatch == "provider":
            event = replace(world.fake.verify_event(headers, body), provider="other")
            async with lab.sessions() as database, database.begin():
                assert await lab.app.settlement.apply(database, event, source="webhook") == (
                    "unmatched",
                    False,
                )
        else:
            assert await lab.webhook(headers, body) == ("needs_review", False)
            assert await lab.webhook(headers, body) == ("replayed", True)
        assert [e.id for e in await lab.entries(learner)] == [e.id for e in before]
        assert (await lab.refund_events(paid.order_id))[-1].state == "pending"
        assert await lab.refund(learner, paid.payment_ref, key="match") == accepted
        with pytest.raises(BillingIdempotencyConflict):
            await lab.refund(learner, paid.payment_ref, key="match", reason="changed")
        correct = world.fake.signed_event(
            kind=kind,
            event_id=f"right:{paid.order_ref}",
            order_reference=paid.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=paid.payment_ref,
            provider_refund_ref="fake_refund_expected",
        )
        assert await lab.webhook(*correct) == ("refund", False)
        after = await lab.entries(learner)
        assert (await lab.lots(learner))[f"order:{paid.order_id}"].capacity == (
            0 if kind is PaymentEventKind.REFUNDED else PACK_SECONDS
        )
        assert await lab.webhook(*correct) == ("replayed", True)
        distinct = world.fake.signed_event(
            kind=kind,
            event_id=f"duplicate:{paid.order_ref}",
            order_reference=paid.order_ref,
            money=PACK_PRICE,
            provider_payment_ref=paid.payment_ref,
            provider_refund_ref="fake_refund_expected",
        )
        assert await lab.webhook(*distinct) == ("no_action", False)
        assert [e.id for e in await lab.entries(learner)] == [e.id for e in after]

    scenario(postgres_harness, world, exercise)


def test_refund_hold_precedes_concurrent_reservation_and_replay(
    postgres_harness, world: World, monkeypatch
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, "race-refund-first")
        entered, finish = asyncio.Event(), asyncio.Event()
        calls = 0

        async def slow_provider(**kwargs):
            nonlocal calls
            calls += 1
            entered.set()
            await finish.wait()
            return await pending_refund(**kwargs)

        monkeypatch.setattr(world.fake, "refund", slow_provider)
        task = asyncio.create_task(lab.refund(learner, paid.payment_ref, key="race"))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            with pytest.raises(ConversationDenied):
                await lab.reserve(learner, TRIAL_SECONDS + PERIOD_SECONDS + 1)
            same = await lab.refund(learner, paid.payment_ref, key="race")
            assert same.state == "pending"
        finally:
            finish.set()
            first = await asyncio.wait_for(task, timeout=10)
        assert first == same
        assert calls == 1
        assert len([e for e in await lab.entries(learner) if e.kind == "refund_hold"]) == 1

    scenario(postgres_harness, world, exercise)


def test_reservation_lock_wins_before_refund(postgres_harness, world: World, monkeypatch):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, "race-reserve-first")
        reached_lock = asyncio.Event()

        async def observed_lock(database, tenant_id):
            reached_lock.set()
            await take_admission_lock(database, tenant_id)

        monkeypatch.setattr("ac_platform.billing.settlement.take_admission_lock", observed_lock)
        async with lab.sessions() as database, database.begin():
            await lab.acquisition(database, learner).reserve(
                source(PERIOD_SECONDS + 600), actor=learner.actor
            )
            task = asyncio.create_task(lab.refund(learner, paid.payment_ref, key="reserve-wins"))
            await asyncio.wait_for(reached_lock.wait(), timeout=10)
            assert not task.done()
        with pytest.raises(PaymentUsed):
            await asyncio.wait_for(task, timeout=10)
        assert await lab.refund_events(paid.order_id) == []
        assert lab.provider_refunds(paid.order_ref) == []

    scenario(postgres_harness, world, exercise)


def test_verify_replays_exact_result_across_concurrency_and_restart(postgres_harness, world: World):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        checkout = await lab.checkout(learner, top_up_command("verify-c1"))
        order_id = UUID(checkout.order.order_id)
        first, concurrent = await asyncio.gather(
            lab.verify(learner, order_id, key="verify"), lab.verify(learner, order_id, key="verify")
        )
        assert first == concurrent
        recovered = restart(lab)
        async with lab.sessions() as database, database.begin():
            assert (
                await recovered.verify_order(
                    database, caller(learner), order_id, idempotency_key="verify"
                )
                == first
            )
        async with lab.sessions() as database, database.begin():
            with pytest.raises(BillingRateLimited):
                await recovered.verify_order(
                    database, caller(learner), order_id, idempotency_key="another"
                )
        # The provider changes after the first result. Replaying keeps that result.
        lab.fake.settle(checkout.hosted.params["reference"])
        world.clock.tick(10)
        paid = await lab.verify(learner, order_id, key="verify-paid")
        assert paid.status == "paid"
        assert await lab.verify(learner, order_id, key="verify") == first
        assert await lab.verify(learner, order_id, key="verify-paid") == paid
        other = await lab.checkout(learner, top_up_command("verify-other"))
        with pytest.raises(BillingIdempotencyConflict):
            await lab.verify(learner, UUID(other.order.order_id), key="verify")

    scenario(postgres_harness, world, exercise)


def test_definite_provider_refusal_releases_hold_without_refund(
    postgres_harness, world: World, monkeypatch
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, "definite-refusal")

        async def refused(**kwargs):
            raise PermanentProviderError("fictional definite refusal")

        monkeypatch.setattr(world.fake, "refund", refused)
        assert (await lab.refund(learner, paid.payment_ref, key="refused")).state == "pending"
        assert [e.state for e in await lab.refund_events(paid.order_id)] == ["pending", "refused"]
        assert (await lab.closings(learner))[f"order:{paid.order_id}"] == [
            "refund_hold",
            "refund_hold_release",
        ]
        assert (await lab.lots(learner))[f"order:{paid.order_id}"].capacity == PACK_SECONDS

    scenario(postgres_harness, world, exercise)


@pytest.mark.parametrize("months", [1, 12], ids=["monthly", "yearly"])
@pytest.mark.parametrize("failed", [False, True], ids=["processed", "failed"])
def test_razorpay_subscription_refund_matches_verified_payment_without_subscription_ref(
    postgres_harness, world: World, monkeypatch, months: int, failed: bool
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        base = await lab.subscribe_and_pay(learner)
        suffix = uuid4().hex[:12]
        sub_ref, pay_ref, refund_ref = f"sub_{suffix}", f"pay_{suffix}", f"rfnd_{suffix}"
        amount = 249_900 if months == 1 else 2_499_000
        async with lab.sessions() as database, database.begin():
            previous_order = await database.get(BillingOrder, base.order_id)
            previous_sub = await database.get(BillingSubscription, base.subscription_id)
            sub = BillingSubscription(
                **{
                    c.name: getattr(previous_sub, c.name)
                    for c in BillingSubscription.__table__.columns
                }
            )
            sub.id, sub.provider, sub.provider_subscription_ref, sub.provider_plan_ref = (
                uuid4(),
                "razorpay",
                sub_ref,
                "plan_fictional",
            )
            sub.interval, sub.amount_minor = ("month" if months == 1 else "year"), amount
            database.add(sub)
            await database.flush()
            order = BillingOrder(
                **{c.name: getattr(previous_order, c.name) for c in BillingOrder.__table__.columns}
            )
            order.id, order.subscription_id, order.provider = uuid4(), sub.id, "razorpay"
            order.order_ref, order.provider_order_ref = f"ord_{suffix}", sub_ref
            order.interval, order.amount_minor = sub.interval, amount
            database.add(order)
            await database.flush()
            database.add(
                BillingOrderEvent(
                    id=uuid4(),
                    order_id=order.id,
                    status="awaiting_payment",
                    payment_event_id=None,
                    detail="fictional checkout ready",
                    actor_type="person",
                    created_at=lab.now,
                )
            )

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == f"/v1/payments/{pay_ref}/refund"
            body = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": refund_ref,
                    "status": "pending",
                    "amount": body["amount"],
                    "currency": "INR",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            fictional_credentials = {
                "key_id": "rzp_test_FICTIONAL0001",
                "key_secret": "fictional-key",
                "webhook_secret": "fictional-hook",
            }
            adapter = RazorpayAdapter(
                mode=PaymentMode.TEST, http_client=client, **fictional_credentials
            )
            app = restart(lab, PaymentProviderRegistry([world.fake, adapter]))

            async def cancel(*args, **kwargs):
                return None

            monkeypatch.setattr(adapter, "cancel_subscription", cancel)

            async def deliver(payload, event_id):
                body = json.dumps(payload, separators=(",", ":")).encode()
                headers = {
                    "X-Razorpay-Event-Id": event_id,
                    "X-Razorpay-Signature": hmac.new(
                        b"fictional-hook", body, hashlib.sha256
                    ).hexdigest(),
                }
                lab.tick()
                async with lab.sessions() as database, database.begin():
                    receipt = await app.receive_webhook(database, "razorpay", headers, body)
                return receipt.outcome, receipt.replayed

            charge = {
                "event": "subscription.charged",
                "payload": {
                    "subscription": {
                        "entity": {
                            "id": sub_ref,
                            "plan_id": "plan_fictional",
                            "quantity": 1,
                            "current_start": int(T0.timestamp()),
                            "current_end": int(add_months(T0, months).timestamp()),
                        }
                    },
                    "payment": {"entity": {"id": pay_ref, "amount": amount, "currency": "INR"}},
                },
            }
            assert await deliver(charge, f"charge:{suffix}") == ("paid", False)
            async with lab.sessions() as database, database.begin():
                accepted = await app.refund_payment(
                    database,
                    caller(learner),
                    pay_ref,
                    reason="unused period",
                    idempotency_key="subscription-refund",
                )
            assert accepted.state == "pending"
            lots = [
                lot
                for ref, lot in (await lab.lots(learner)).items()
                if ref != "trial"
                and ref not in {f"period:{p.id}" for p in await lab.periods(base.subscription_id)}
            ]
            assert len(lots) == months
            assert all(lot.capacity == 0 for lot in lots)
            callback = {
                "event": "refund.failed" if failed else "refund.processed",
                "payload": {
                    "refund": {
                        "entity": {
                            "id": refund_ref,
                            "payment_id": pay_ref,
                            "amount": amount,
                            "currency": "INR",
                            "receipt": None,
                        }
                    },
                    "payment": {"entity": {"id": pay_ref, "order_id": f"order_provider_{suffix}"}},
                },
            }
            assert await deliver(callback, f"refund:{suffix}") == ("refund", False)
            assert await deliver(callback, f"refund:{suffix}") == ("replayed", True)
            events = await lab.refund_events(order.id)
            assert events[-1].state == ("refused" if failed else "refunded")
            entries = await lab.entries(learner)
            holds = [e for e in entries if e.kind == "refund_hold"]
            assert len(holds) == months
            assert len([e for e in entries if e.kind == "refund_hold_release"]) == months
            assert len([e for e in entries if e.kind == "refund"]) == (0 if failed else months)
            async with lab.sessions() as database, database.begin():
                final = await app.read_order(database, caller(learner), order.id)
                assert final.refund.state == ("refused" if failed else "refunded")
                assert (
                    await app.refund_payment(
                        database,
                        caller(learner),
                        pay_ref,
                        reason="unused period",
                        idempotency_key="subscription-refund",
                    )
                    == accepted
                )

    scenario(postgres_harness, world, exercise)


def test_signed_payment_mismatch_is_not_the_original_refundable_charge(
    postgres_harness, world: World
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        checkout = await lab.checkout(learner, top_up_command("bad-then-good"))
        order_id = UUID(checkout.order.order_id)
        order_ref = checkout.hosted.params["reference"]
        payment_ref = world.fake.settle(order_ref)
        for amount, expected in [(1, "needs_review"), (PACK_PRICE.amount_minor, "paid")]:
            callback = world.fake.signed_event(
                kind=PaymentEventKind.PAID,
                event_id=f"charge:{order_ref}:{amount}",
                order_reference=order_ref,
                provider_payment_ref=payment_ref,
                money=Money(amount, "INR"),
            )
            assert await lab.webhook(*callback) == (expected, False)
        assert (await lab.refund(learner, payment_ref, key="original")).state == "pending"
        assert [e.amount_minor for e in await lab.refund_events(order_id)] == [
            PACK_PRICE.amount_minor
        ] * 2
        assert lab.provider_refunds(order_ref) == [PACK_PRICE]

    scenario(postgres_harness, world, exercise)


def test_refund_callbacks_select_their_own_period_on_one_subscription_order(
    postgres_harness, world: World, monkeypatch
):
    async def exercise(lab: Lab) -> None:
        learner = await lab.learner()
        first = await lab.subscribe_and_pay(learner)
        next_charge = world.fake.charge(
            first.provider_subscription_ref,
            event_id=f"next:{first.order_ref}",
            order_reference=first.order_ref,
            money=Money(249_900, "INR"),
            period_start=first.period_end,
            period_end=add_months(first.period_end, 1),
        )
        assert await lab.webhook(*next_charge) == ("paid", False)
        next_payment = f"{first.provider_subscription_ref}_pay_2"

        async def pending(**kwargs):
            return RefundReceipt(
                provider="fake",
                provider_refund_ref=f"fake_refund_{kwargs['idempotency_key']}",
                state=RefundState.PENDING,
                money=kwargs["money"],
            )

        monkeypatch.setattr(world.fake, "refund", pending)
        await lab.refund(learner, first.payment_ref, key="first-period")
        await lab.refund(learner, next_payment, key="next-period")
        events = await lab.refund_events(first.order_id)
        refs = {e.payment_ref: e.provider_refund_ref for e in events if e.provider_refund_ref}
        callback = world.fake.signed_event(
            kind=PaymentEventKind.REFUND_FAILED,
            event_id=f"release-first:{first.order_ref}",
            order_reference=first.order_ref,
            provider_payment_ref=first.payment_ref,
            provider_refund_ref=refs[first.payment_ref],
            money=Money(249_900, "INR"),
        )
        assert await lab.webhook(*callback) == ("refund", False)
        periods = await lab.periods(first.subscription_id)
        lots = await lab.lots(learner)
        assert lots[f"period:{periods[0].id}"].capacity == PERIOD_SECONDS
        assert lots[f"period:{periods[1].id}"].capacity == 0
        assert (await lab.refund_events(first.order_id))[-1].payment_ref == first.payment_ref

    scenario(postgres_harness, world, exercise)
