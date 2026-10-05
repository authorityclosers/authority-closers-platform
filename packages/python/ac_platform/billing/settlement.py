"""Verified provider events become periods, lots, order and subscription events, and refunds.

This is the only path that writes paid seconds (ADR 0052, section E). A
callback is verified by the provider adapter's signature check, stored once
by (provider, event id), matched to our copy, reduced to a pure decision and
applied in the caller's transaction under the tenant admission lock.
"""

from __future__ import annotations

import contextlib
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.checkout import CheckoutService, one, recurring_provider
from ac_platform.billing.commands import Caller, WebhookReceipt
from ac_platform.billing.errors import (
    BillingRateLimited,
    BillingValidationFailed,
    OrderNotFound,
    PaymentNotFound,
    PaymentUsed,
    ProviderUnavailable,
    RefundWindowClosed,
)
from ac_platform.billing.invoices import issue_credit_note, issue_invoice
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import (
    BillingCommandIdempotency,
    BillingOrder,
    BillingOrderEvent,
    BillingPaymentEvent,
    BillingPeriod,
    BillingRefundEvent,
    BillingSubscription,
    BillingSubscriptionEvent,
)
from ac_platform.billing.periods import AccountKind, Interval, PlannedLot
from ac_platform.billing.projection import REFUND_WINDOW, Projection, payment_refundable
from ac_platform.billing.reducers import (
    Decision,
    GrantLots,
    NeedsReview,
    NoAction,
    OrderCopy,
    ReviewReason,
    SubscriptionCopy,
    SubscriptionStateChange,
    reduce_order_event,
    reduce_subscription_event,
)
from ac_platform.billing.views import OrderView, RefundView
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.kernel.authz import ActorContext
from ac_platform.payments.fake import FakePaymentProvider
from ac_platform.payments.ports import (
    Money,
    PaymentEvent,
    PaymentEventKind,
    PaymentEventRejected,
    PaymentState,
    RefundAlreadyRequestedError,
    RefundState,
)
from ac_platform.payments.recurring import SubscriptionState
from ac_platform.providers.ports import PermanentProviderError, ProviderError

VERIFY_INTERVAL_SECONDS = 10.0
_EVENT_KIND_NAMES = {
    PaymentEventKind.PAID: "payment.captured",
    PaymentEventKind.FAILED: "payment.failed",
    PaymentEventKind.REFUNDED: "refund.processed",
    PaymentEventKind.REFUND_FAILED: "refund.failed",
    PaymentEventKind.IGNORED: "ignored",
    PaymentEventKind.SUBSCRIPTION_ACTIVATED: "subscription.activated",
    PaymentEventKind.SUBSCRIPTION_CHARGED: "subscription.charged",
    PaymentEventKind.SUBSCRIPTION_PAST_DUE: "subscription.state",
    PaymentEventKind.SUBSCRIPTION_HALTED: "subscription.state",
    PaymentEventKind.SUBSCRIPTION_CANCELLED: "subscription.state",
    PaymentEventKind.SUBSCRIPTION_ENDED: "subscription.state",
}
_STATE_NAMES = {
    PaymentEventKind.SUBSCRIPTION_PAST_DUE: "pending",
    PaymentEventKind.SUBSCRIPTION_HALTED: "halted",
    PaymentEventKind.SUBSCRIPTION_CANCELLED: "cancelled",
    PaymentEventKind.SUBSCRIPTION_ENDED: "completed",
}
_SUBSCRIPTION_STATUS = {
    SubscriptionState.PENDING: "pending_authorisation",
    SubscriptionState.AUTHORISED: "pending_authorisation",
    SubscriptionState.ACTIVE: "active",
    SubscriptionState.PAST_DUE: "past_due",
    SubscriptionState.HALTED: "halted",
    SubscriptionState.PAUSED: "halted",
    SubscriptionState.CANCELLED: "cancelled",
    SubscriptionState.ENDED: "ended",
}


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("billing times must be timezone-aware")
    return moment.astimezone(UTC)


class Settlement:
    """Webhook receipt, verified server reads and refunds for one :class:`CheckoutService`."""

    def __init__(self, service: CheckoutService) -> None:
        self.service = service

    # ---- entry points ---------------------------------------------------------

    async def receive_webhook(
        self, database: AsyncSession, provider_name: str, headers: dict[str, str], raw_body: bytes
    ) -> WebhookReceipt:
        provider = self.service.providers.get(provider_name)
        try:
            event = provider.verify_event(headers, raw_body, now=_utc(self.service.clock()))
        except PaymentEventRejected:
            raise
        outcome, replayed = await self.apply(database, event, source="webhook")
        return WebhookReceipt(
            provider=provider.name, event_id=event.event_id, outcome=outcome, replayed=replayed
        )

    async def verify_order(
        self, database: AsyncSession, caller: Caller, order_id: UUID, *, idempotency_key: str
    ) -> OrderView:
        """C1 §2: ask the provider through a verified server read, at most once per 10 s."""

        order = await database.get(BillingOrder, order_id)
        if order is None:
            raise OrderNotFound("That order does not exist.")
        resolved = await self.service.account_by_id(database, caller, order.account_id, write=False)
        if resolved is None:
            raise OrderNotFound("That order does not exist.")
        await take_admission_lock(database, resolved.tenant_id)
        digest = self.service.digest(str(order_id))
        replay = await self.service._replay(
            database, resolved.account, "verify", idempotency_key, digest
        )
        if replay is not None:
            return TypeAdapter(OrderView).validate_python(replay)
        now = _utc(self.service.clock())
        last = await database.scalar(
            select(func.max(BillingCommandIdempotency.created_at)).where(
                BillingCommandIdempotency.account_id == resolved.account.id,
                BillingCommandIdempotency.scope == "verify",
                BillingCommandIdempotency.request_sha256 == digest,
            )
        )
        if last is not None and (now - _utc(last)).total_seconds() < VERIFY_INTERVAL_SECONDS:
            raise BillingRateLimited("Wait a few seconds before checking again.")
        provider = self.service.providers.get(order.provider)
        try:
            if isinstance(provider, FakePaymentProvider) and self.service.fake_checkout_base_url:
                # Hosted test checkout settles synchronously through signed webhooks.
                # Process-local snapshots cannot supersede its durable verified state.
                pass
            elif order.kind == "top_up" and order.provider_order_ref is not None:
                snapshot = await provider.fetch_payment(
                    order_reference=order.order_ref, provider_order_ref=order.provider_order_ref
                )
                if snapshot.state is PaymentState.PAID and snapshot.paid is not None:
                    event = PaymentEvent(
                        provider=provider.name,
                        event_id=f"read:{snapshot.provider_payment_ref or order.order_ref}:paid",
                        kind=PaymentEventKind.PAID,
                        event_type="server_read",
                        body_digest=hashlib.sha256(
                            f"{order.order_ref}:{snapshot.provider_payment_ref}".encode()
                        ).hexdigest(),
                        order_reference=order.order_ref,
                        provider_order_ref=snapshot.provider_order_ref,
                        provider_payment_ref=snapshot.provider_payment_ref,
                        money=snapshot.paid,
                        occurred_at=now,
                    )
                    await self.apply(database, event, source="server_read")
                elif snapshot.state is PaymentState.FAILED:
                    await self._order_event(database, order, "failed", None, "provider read", now)
            elif (
                order.subscription_id is not None
                and (recurring := recurring_provider(provider)) is not None
            ):
                subscription = await database.get(BillingSubscription, order.subscription_id)
                if subscription is not None and subscription.provider_subscription_ref is not None:
                    sub_snapshot = await recurring.fetch_subscription(
                        subscription.provider_subscription_ref
                    )
                    await self._subscription_state(
                        database,
                        subscription,
                        _SUBSCRIPTION_STATUS[sub_snapshot.state],
                        None,
                        "provider read",
                        now,
                    )
                    if sub_snapshot.state is SubscriptionState.ACTIVE:
                        latest = await self.service.latest_order_event(database, order.id)
                        if latest is not None and latest.status == "awaiting_payment":
                            await self._order_event(
                                database, order, "confirming", None, "provider read", now
                            )
        except ProviderError as error:
            raise ProviderUnavailable("The payment provider did not answer.") from error
        view = await self.service.order_view(database, order, resolved.name, now)
        await self.service._remember(
            database,
            resolved.account,
            "verify",
            idempotency_key,
            digest,
            TypeAdapter(OrderView).dump_python(view, mode="json"),
            200,
        )
        return view

    async def refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        """C1 §4: within 7 days of verification and only if nothing from the payment was used."""

        return await self._refund_payment(
            database,
            caller,
            payment_id,
            reason=reason,
            idempotency_key=idempotency_key,
            staff=False,
        )

    async def staff_refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
    ) -> RefundView:
        """Use fresh staff authority and commit the request's refund intent before sending."""

        return await self._refund_payment(
            database, caller, payment_id, reason=reason, idempotency_key=idempotency_key, staff=True
        )

    async def _refund_payment(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        *,
        reason: str,
        idempotency_key: str,
        staff: bool,
    ) -> RefundView:
        # Commit the intent before submission: neither caller rollback nor a
        # process crash may undo the hold after the provider receives a refund.
        async with AsyncSession(bind=database.bind, expire_on_commit=False) as durable:
            if staff:
                # Fresh platform projection locks Person and Session. Prepare
                # the attributable audit/hold in that same transaction so their
                # foreign keys cannot wait on our own authentication locks.
                # Commit the intent before any provider call, as on the customer path.
                prepared = await self._prepare_refund(
                    database, caller, payment_id, reason, idempotency_key, staff=True
                )
                await database.commit()
            else:
                async with durable.begin():
                    prepared = await self._prepare_refund(
                        durable, caller, payment_id, reason, idempotency_key
                    )
            view, order, payment, money, send = prepared
            if not send:
                return view
            provider = self.service.providers.get(order.provider)
            try:
                receipt = await provider.refund(
                    order_reference=order.order_ref,
                    provider_payment_ref=payment_id,
                    money=money,
                    idempotency_key=self._refund_key(payment),
                )
            except ProviderError as error:
                if not isinstance(error, PermanentProviderError) or isinstance(
                    error, RefundAlreadyRequestedError
                ):
                    return view  # unknown outcome: keep the committed intent and holds
                receipt = None  # a definite refusal is the only error that releases
            async with durable.begin():
                account = await durable.get(BillingAccount, order.account_id)
                assert account is not None
                await take_admission_lock(durable, account.tenant_id)
                latest = await self._latest_refund(durable, order.id, payment_id)
                assert latest is not None
                if latest.state == "pending":
                    state = (
                        "refused"
                        if receipt is None
                        else "refunded"
                        if receipt.state is RefundState.PROCESSED
                        else "pending"
                    )
                    if receipt is not None and (
                        receipt.provider != order.provider or receipt.money != money
                    ):
                        return view  # unusable receipt: retain holds for verified recovery
                    durable.add(
                        BillingRefundEvent(
                            id=uuid4(),
                            order_id=order.id,
                            payment_ref=payment_id,
                            state=state,
                            provider_refund_ref=None
                            if receipt is None
                            else receipt.provider_refund_ref,
                            amount_minor=money.amount_minor,
                            currency=money.currency,
                            reason=reason,
                            actor_type="person",
                            actor_person_id=caller.person_id,
                            payment_event_id=payment.id,
                            created_at=max(
                                _utc(self.service.clock()),
                                _utc(latest.created_at) + timedelta(microseconds=1),
                            ),
                        )
                    )
                    await durable.flush()
                    if state != "pending":
                        ledger = self.service.ledger(durable, tenant_id=account.tenant_id)
                        sources = await self._sources(durable, order, payment)
                        lots = [
                            e
                            for e in await ledger.entries(order.account_id)
                            if e.source_ref in sources
                        ]
                        await self._settle_refund(
                            durable,
                            ledger,
                            order,
                            lots,
                            confirmed=state == "refunded",
                            payment=payment,
                            now=_utc(self.service.clock()),
                        )
            # The immutable command result is acceptance (pending). Status reads
            # expose subsequent settlement; replay never resends the provider call.
            return view

    @staticmethod
    def _refund_key(payment: BillingPaymentEvent) -> str:
        return hashlib.sha256(
            f"refund:{payment.provider}:{payment.payment_ref}".encode()
        ).hexdigest()[:20]

    async def _prepare_refund(
        self,
        database: AsyncSession,
        caller: Caller,
        payment_id: str,
        reason: str,
        idempotency_key: str,
        *,
        staff: bool = False,
    ) -> tuple[RefundView, BillingOrder, BillingPaymentEvent, Money, bool]:
        if staff:
            permissions = await platform_projection(
                database,
                ActorContext(caller.person_id, caller.session_id, caller.tenant_id),
                operations_tenant_id=self.service.operations_tenant_id,
            )
            if "platform_billing_manage" not in permissions:
                raise CapabilityDenied("A current platform billing assignment is required.")
            if not reason.strip() or len(reason) > 500:
                raise BillingValidationFailed("A refund reason of 1 to 500 characters is required.")
        payment = await self._verified_payment(database, payment_id)
        if payment is None or payment.order_id is None:
            raise PaymentNotFound("That payment does not exist.")
        order = await database.get(BillingOrder, payment.order_id)
        assert order is not None
        if staff:
            account = await database.get(BillingAccount, order.account_id)
        else:
            resolved = await self.service.account_by_id(
                database, caller, order.account_id, write=True
            )
            account = None if resolved is None else resolved.account
        if account is None:
            raise PaymentNotFound("That payment does not exist.")
        await take_admission_lock(database, account.tenant_id)
        digest = self.service.digest(payment_id, reason)
        money = Money(
            payment.amount_minor or order.amount_minor, payment.currency or order.currency
        )
        replay = await self.service._replay(database, account, "refund", idempotency_key, digest)
        if replay is not None:
            return TypeAdapter(RefundView).validate_python(replay), order, payment, money, False
        now = _utc(self.service.clock())
        latest_refund = await self._latest_refund(database, order.id, payment_id)
        if latest_refund is not None:
            view = RefundView(
                payment_id=payment_id,
                state="pending"
                if latest_refund.state == "pending"
                else "refunded"
                if latest_refund.state == "refunded"
                else "refused",
                refundable_until=_utc(payment.verified_at) + REFUND_WINDOW,
            )
            await self.service._remember(
                database,
                account,
                "refund",
                idempotency_key,
                digest,
                TypeAdapter(RefundView).dump_python(view, mode="json"),
                200 if view.state == "refunded" else 202,
            )
            return view, order, payment, money, False
        verified_at = _utc(payment.verified_at)
        if now > verified_at + REFUND_WINDOW:
            raise RefundWindowClosed("Refunds are possible within 7 days of payment.")
        ledger = self.service.ledger(database, tenant_id=account.tenant_id)
        entries = await ledger.entries(account.id)
        sources = await self._sources(database, order, payment)
        payment_lots = [
            entry
            for entry in entries
            if entry.kind in ("period_grant", "purchase") and entry.source_ref in sources
        ]
        if not payment_lots:
            raise PaymentNotFound("This payment granted no minutes.")
        projection = await self._projection(database, ledger, account, now)
        lots_by_id = {lot.lot_id: lot for lot in ledger.lots_from_entries(entries)}
        if not payment_refundable(
            projection, [lots_by_id[str(e.id)] for e in payment_lots], verified_at=verified_at
        ):
            raise PaymentUsed(
                "Minutes from this payment were already used, so it cannot be refunded."
            )
        audit_id = None
        if staff:
            audit = await AuditRepository(database).append(
                tenant_id=account.tenant_id,
                actor_person_id=caller.person_id,
                session_id=caller.session_id,
                action="billing.staff_refund_requested",
                resource_type="billing_payment",
                resource_id=payment.id,
                payload={
                    "account_id": str(account.id),
                    "order_id": str(order.id),
                    "payment_id": payment_id,
                },
                reason=reason,
                request_id=caller.request_id,
                now=now,
            )
            audit_id = audit.id
        for entry in payment_lots:
            position = projection.position(str(entry.id))
            remainder = entry.seconds if position is None else position.unallocated
            await ledger.write_closing(
                lot=entry,
                kind="refund_hold",
                seconds=remainder,
                remainder=remainder,
                source_ref=f"refund-hold:{entry.id}",
                actor_type="person",
                actor_person_id=caller.person_id,
                reason=reason,
                audit_event_id=audit_id,
            )
        view = RefundView(
            payment_id=payment_id, state="pending", refundable_until=verified_at + REFUND_WINDOW
        )
        database.add(
            BillingRefundEvent(
                id=uuid4(),
                order_id=order.id,
                payment_ref=payment_id,
                state="pending",
                provider_refund_ref=None,
                amount_minor=money.amount_minor,
                currency=money.currency,
                reason=reason,
                actor_type="person",
                actor_person_id=caller.person_id,
                payment_event_id=payment.id,
                created_at=now,
            )
        )
        await self.service._remember(
            database,
            account,
            "refund",
            idempotency_key,
            digest,
            TypeAdapter(RefundView).dump_python(view, mode="json"),
            202,
        )
        return view, order, payment, money, True

    # ---- applying a verified event ------------------------------------------------

    async def apply(
        self, database: AsyncSession, event: PaymentEvent, *, source: str
    ) -> tuple[str, bool]:
        """Store the event once and apply its decision. Returns (outcome, replayed)."""

        existing = await database.scalar(
            select(BillingPaymentEvent).where(
                BillingPaymentEvent.provider == event.provider,
                BillingPaymentEvent.provider_event_id == event.event_id,
            )
        )
        if existing is not None:
            return "replayed", True
        now = _utc(self.service.clock())
        subscription = (
            None
            if event.kind in (PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED)
            else await self._match_subscription(database, event)
        )
        order = await self._match_order(database, event, subscription)
        stored = BillingPaymentEvent(
            id=uuid4(),
            provider=event.provider,
            provider_event_id=event.event_id,
            kind=_EVENT_KIND_NAMES[event.kind],
            source=source,
            order_id=None if order is None else order.id,
            subscription_id=None if subscription is None else subscription.id,
            payment_ref=event.provider_payment_ref,
            amount_minor=None if event.money is None else event.money.amount_minor,
            currency=None if event.money is None else event.money.currency,
            period_start=event.period_start,
            period_end=event.period_end,
            state=_STATE_NAMES.get(event.kind),
            payload_sha256=event.body_digest,
            received_at=now,
            verified_at=now,
            created_at=now,
        )
        database.add(stored)
        await database.flush()
        if subscription is not None:
            account_id = subscription.account_id
        elif order is not None:
            account_id = order.account_id
        else:
            return "unmatched", False
        account = await database.get(BillingAccount, account_id)
        assert account is not None  # orders and subscriptions reference an account
        await take_admission_lock(database, account.tenant_id)
        if event.kind in (PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED):
            assert order is not None
            return await self._refund_outcome(database, order, event, stored, now), False
        if subscription is not None:
            period_id = uuid4()
            decision = reduce_subscription_event(
                self._subscription_copy(subscription, account), event, period_id=str(period_id)
            )
            return await self._apply_subscription(
                database, account, subscription, order, stored, decision, period_id, now
            ), False
        assert order is not None
        decision = await self._order_decision(database, account, order, event, now)
        return await self._apply_order(database, account, order, stored, decision, now), False

    async def _order_decision(
        self,
        database: AsyncSession,
        account: BillingAccount,
        order: BillingOrder,
        event: PaymentEvent,
        now: datetime,
    ) -> Decision:
        first_start = await database.scalar(
            select(func.min(BillingPeriod.period_start))
            .join(BillingSubscription, BillingSubscription.id == BillingPeriod.subscription_id)
            .where(BillingSubscription.account_id == account.id)
        )
        if first_start is None:
            return NeedsReview(reason=ReviewReason.PERIOD_MISSING)
        return reduce_order_event(
            OrderCopy(
                order_id=str(order.id),
                minutes=order.minutes,
                money=Money(order.amount_minor, order.currency),
                provider=order.provider,
                order_reference=order.order_ref,
                provider_order_ref=order.provider_order_ref or order.order_ref,
            ),
            event,
            verified_at=now,
            first_period_start=_utc(first_start),
        )

    async def _apply_order(
        self,
        database: AsyncSession,
        account: BillingAccount,
        order: BillingOrder,
        stored: BillingPaymentEvent,
        decision: Decision,
        now: datetime,
    ) -> str:
        if isinstance(decision, GrantLots):
            await issue_invoice(database, order, stored, now, self.service.invoice_settings)
            await self._write_lots(
                database, account, decision.lots, "purchase", order.plan_key, stored
            )
            await self._order_event(database, order, "paid", stored.id, "verified payment", now)
            return "paid"
        if isinstance(decision, NeedsReview):
            await self._order_event(
                database, order, "needs_review", stored.id, f"review: {decision.reason.value}", now
            )
            return "needs_review"
        if isinstance(decision, NoAction) and decision.event_kind is PaymentEventKind.FAILED:
            await self._order_event(database, order, "failed", stored.id, "payment failed", now)
            return "failed"
        return "no_action"

    async def _apply_subscription(
        self,
        database: AsyncSession,
        account: BillingAccount,
        subscription: BillingSubscription,
        order: BillingOrder | None,
        stored: BillingPaymentEvent,
        decision: Decision,
        period_id: UUID,
        now: datetime,
    ) -> str:
        if isinstance(decision, GrantLots):
            await issue_invoice(
                database, order or subscription, stored, now, self.service.invoice_settings
            )
            assert stored.period_start is not None and stored.period_end is not None
            database.add(
                BillingPeriod(
                    id=period_id,
                    subscription_id=subscription.id,
                    payment_event_id=stored.id,
                    period_start=stored.period_start,
                    period_end=stored.period_end,
                    created_at=now,
                )
            )
            await database.flush()
            await self._write_lots(
                database, account, decision.lots, "period_grant", subscription.plan_key, stored
            )
            await self._subscription_state(
                database, subscription, "active", stored.id, "period paid", now
            )
            if order is not None:
                latest = await self.service.latest_order_event(database, order.id)
                if latest is not None and latest.status != "paid":
                    await self._order_event(
                        database, order, "paid", stored.id, "first period paid", now
                    )
            return "paid"
        if isinstance(decision, SubscriptionStateChange):
            await self._subscription_state(
                database,
                subscription,
                _SUBSCRIPTION_STATUS[decision.state],
                stored.id,
                "provider state",
                now,
            )
            if decision.state in {SubscriptionState.CANCELLED, SubscriptionState.HALTED} and (
                order is not None
                and (latest := await self.service.latest_order_event(database, order.id))
                is not None
                and latest.status in {"awaiting_payment", "confirming"}
            ):
                await self._order_event(
                    database, order, "failed", stored.id, "authorisation stopped", now
                )
            if (
                decision.state is SubscriptionState.ACTIVE
                and order is not None
                and (latest := await self.service.latest_order_event(database, order.id))
                is not None
                and latest.status == "awaiting_payment"
            ):
                await self._order_event(database, order, "confirming", stored.id, "authorised", now)
            return "state"
        if isinstance(decision, NeedsReview):
            last = await self.service.latest_subscription_event(database, subscription.id)
            database.add(
                BillingSubscriptionEvent(
                    id=uuid4(),
                    subscription_id=subscription.id,
                    status=last.status if last is not None else "pending_authorisation",
                    cancel_state=last.cancel_state if last is not None else "none",
                    cancel_reason=None,
                    payment_event_id=stored.id,
                    detail=f"review: {decision.reason.value}",
                    actor_type="provider",
                    actor_person_id=None,
                    created_at=now,
                )
            )
            if order is not None:
                latest_order = await self.service.latest_order_event(database, order.id)
                if latest_order is not None and latest_order.status in (
                    "awaiting_payment",
                    "confirming",
                ):
                    await self._order_event(
                        database,
                        order,
                        "needs_review",
                        stored.id,
                        f"review: {decision.reason.value}",
                        now,
                    )
            await database.flush()
            return "needs_review"
        return "no_action"

    # ---- helpers ------------------------------------------------------------------

    @staticmethod
    async def _sources(
        database: AsyncSession, order: BillingOrder, payment: BillingPaymentEvent
    ) -> set[str]:
        """The lot source refs a verified payment can have produced (B2 naming)."""

        if order.kind == "top_up":
            return {f"order:{order.id}"}
        refs: set[str] = set()
        periods = await database.scalars(
            select(BillingPeriod).where(BillingPeriod.payment_event_id == payment.id)
        )
        for period in periods:
            refs.add(f"period:{period.id}")
            refs.update(f"period:{period.id}:m{k}" for k in range(12))
        return refs

    @staticmethod
    async def _verified_payment(
        database: AsyncSession, payment_ref: str | None, provider: str | None = None
    ) -> BillingPaymentEvent | None:
        payment: BillingPaymentEvent | None = await database.scalar(
            select(BillingPaymentEvent)
            .where(
                BillingPaymentEvent.payment_ref == payment_ref,
                *([] if provider is None else [BillingPaymentEvent.provider == provider]),
                BillingPaymentEvent.kind.in_(("payment.captured", "subscription.charged")),
                or_(
                    exists(
                        select(BillingPeriod.id).where(
                            BillingPeriod.payment_event_id == BillingPaymentEvent.id
                        )
                    ),
                    exists(
                        select(BillingOrderEvent.id).where(
                            BillingOrderEvent.payment_event_id == BillingPaymentEvent.id,
                            BillingOrderEvent.status == "paid",
                        )
                    ),
                ),
            )
            .order_by(BillingPaymentEvent.verified_at, BillingPaymentEvent.id)
            .limit(1)
        )
        return payment

    async def _match_subscription(
        self, database: AsyncSession, event: PaymentEvent
    ) -> BillingSubscription | None:
        if event.provider_subscription_ref is None:
            return None
        return await one(
            database,
            select(BillingSubscription).where(
                BillingSubscription.provider == event.provider,
                BillingSubscription.provider_subscription_ref == event.provider_subscription_ref,
            ),
        )

    async def _match_order(
        self, database: AsyncSession, event: PaymentEvent, subscription: BillingSubscription | None
    ) -> BillingOrder | None:
        if event.kind in (PaymentEventKind.REFUNDED, PaymentEventKind.REFUND_FAILED):
            payment = await self._verified_payment(
                database, event.provider_payment_ref, event.provider
            )
            if payment is not None:
                return await database.get(BillingOrder, payment.order_id)
        if subscription is not None:
            return await one(
                database,
                select(BillingOrder).where(BillingOrder.subscription_id == subscription.id),
            )
        if event.provider_order_ref is not None:
            order = await database.scalar(
                select(BillingOrder).where(
                    BillingOrder.provider == event.provider,
                    BillingOrder.provider_order_ref == event.provider_order_ref,
                )
            )
            if order is not None:
                return order
        if event.order_reference is not None:
            return await one(
                database,
                select(BillingOrder).where(
                    BillingOrder.provider == event.provider,
                    BillingOrder.order_ref == event.order_reference,
                ),
            )
        return None

    @staticmethod
    def _subscription_copy(
        subscription: BillingSubscription, account: BillingAccount
    ) -> SubscriptionCopy:
        return SubscriptionCopy(
            subscription_id=str(subscription.id),
            account=AccountKind.PERSONAL
            if account.kind == "personal"
            else AccountKind.ORGANISATION,
            plan_key=subscription.plan_key,
            interval=Interval.MONTH if subscription.interval == "month" else Interval.YEAR,
            seats=subscription.seats,
            included_minutes=subscription.included_minutes,
            money=Money(subscription.amount_minor, subscription.currency),
            provider=subscription.provider,
            provider_plan_ref=subscription.provider_plan_ref or "",
            provider_subscription_ref=subscription.provider_subscription_ref or "",
        )

    async def _write_lots(
        self,
        database: AsyncSession,
        account: BillingAccount,
        lots: tuple[PlannedLot, ...],
        kind: str,
        plan_key: str,
        stored: BillingPaymentEvent,
    ) -> None:
        ledger = self.service.ledger(database, tenant_id=account.tenant_id)
        for planned in lots:
            await ledger.write_lot(
                account=account,
                kind=kind,
                seconds=planned.seconds,
                valid_from=planned.valid_from,
                expires_at=planned.expires_at,
                plan_key=plan_key,
                source_ref=planned.source_ref,
                actor_type="provider",
                reason=f"verified {stored.kind} {stored.provider_event_id}",
            )

    async def _order_event(
        self,
        database: AsyncSession,
        order: BillingOrder,
        status: str,
        payment_event_id: UUID | None,
        detail: str,
        now: datetime,
    ) -> None:
        database.add(
            BillingOrderEvent(
                id=uuid4(),
                order_id=order.id,
                status=status,
                payment_event_id=payment_event_id,
                detail=detail,
                actor_type="provider",
                created_at=now,
            )
        )
        await database.flush()

    async def _subscription_state(
        self,
        database: AsyncSession,
        subscription: BillingSubscription,
        status: str,
        payment_event_id: UUID | None,
        detail: str,
        now: datetime,
    ) -> None:
        latest = await self.service.latest_subscription_event(database, subscription.id)
        cancel_state = latest.cancel_state if latest is not None else "none"
        if status in ("cancelled", "ended") and cancel_state == "requested":
            cancel_state = "confirmed"
        if latest is not None and latest.status == status and latest.cancel_state == cancel_state:
            return
        database.add(
            BillingSubscriptionEvent(
                id=uuid4(),
                subscription_id=subscription.id,
                status=status,
                cancel_state=cancel_state,
                cancel_reason=None,
                payment_event_id=payment_event_id,
                detail=detail,
                actor_type="provider",
                actor_person_id=None,
                created_at=now,
            )
        )
        await database.flush()

    async def _latest_refund(
        self, database: AsyncSession, order_id: UUID, payment_ref: str | None = None
    ) -> BillingRefundEvent | None:
        return await one(
            database,
            select(BillingRefundEvent)
            .where(
                BillingRefundEvent.order_id == order_id,
                *([] if payment_ref is None else [BillingRefundEvent.payment_ref == payment_ref]),
            )
            .order_by(BillingRefundEvent.created_at.desc(), BillingRefundEvent.id.desc())
            .limit(1),
        )

    async def _projection(
        self, database: AsyncSession, ledger: BillingLedger, account: BillingAccount, now: datetime
    ) -> Projection:
        if account.kind == "personal":
            assert account.person_id is not None
            projected = await ledger.project_person(
                tenant_id=account.tenant_id, person_id=account.person_id, now=now, mirror=True
            )
            return projected.projection
        return (
            await ledger.project_organisation(tenant_id=account.tenant_id, now=now, mirror=True)
        ).projection

    async def _refund_outcome(
        self,
        database: AsyncSession,
        order: BillingOrder,
        event: PaymentEvent,
        stored: BillingPaymentEvent,
        now: datetime,
    ) -> str:
        latest = await self._latest_refund(database, order.id, event.provider_payment_ref)
        payment = await self._verified_payment(database, event.provider_payment_ref, event.provider)
        if (
            latest is None
            or payment is None
            or event.provider != order.provider
            or payment.provider != event.provider
            or event.provider_payment_ref != latest.payment_ref
            or payment.payment_ref != latest.payment_ref
            or event.money != Money(latest.amount_minor, latest.currency)
            or event.money != Money(payment.amount_minor or 0, payment.currency or order.currency)
            or event.provider_refund_ref is None
            or (
                latest.provider_refund_ref is not None
                and event.provider_refund_ref != latest.provider_refund_ref
            )
            or (
                latest.provider_refund_ref is None
                and event.refund_reference != self._refund_key(payment)
            )
        ):
            await self._order_event(
                database, order, "needs_review", stored.id, "refund correlation mismatch", now
            )
            return "needs_review"
        if latest.state != "pending":
            return "no_action"
        confirmed = event.kind is PaymentEventKind.REFUNDED
        database.add(
            BillingRefundEvent(
                id=uuid4(),
                order_id=order.id,
                payment_ref=latest.payment_ref,
                state="refunded" if confirmed else "refused",
                provider_refund_ref=event.provider_refund_ref,
                amount_minor=latest.amount_minor,
                currency=latest.currency,
                reason=latest.reason,
                actor_type="provider",
                actor_person_id=None,
                payment_event_id=stored.id,
                created_at=max(now, _utc(latest.created_at) + timedelta(microseconds=1)),
            )
        )
        await database.flush()
        sources = await self._sources(database, order, payment)
        account = await database.get(BillingAccount, order.account_id)
        assert account is not None
        ledger = self.service.ledger(database, tenant_id=account.tenant_id)
        lots = [e for e in await ledger.entries(order.account_id) if e.source_ref in sources]
        await self._settle_refund(
            database, ledger, order, lots, confirmed=confirmed, payment=payment, now=now
        )
        return "refund"

    async def _settle_refund(
        self,
        database: AsyncSession,
        ledger: BillingLedger,
        order: BillingOrder,
        payment_lots: list[BillingLedgerEntry],
        *,
        confirmed: bool,
        payment: BillingPaymentEvent,
        now: datetime,
    ) -> None:
        """A confirmed refund writes the release and the refund; a refusal releases only."""

        if confirmed:
            refund = await self._latest_refund(database, order.id, payment.payment_ref)
            assert refund is not None
            await issue_credit_note(database, payment, refund, now, self.service.invoice_settings)

        entries = await ledger.entries(order.account_id)
        released = {e.hold_id for e in entries if e.kind == "refund_hold_release"}
        for lot in payment_lots:
            hold = next(
                (
                    e
                    for e in entries
                    if e.kind == "refund_hold" and e.lot_id == lot.id and e.id not in released
                ),
                None,
            )
            if hold is None:
                continue
            held_seconds = -hold.seconds
            # The release gives the held seconds back to the lot; the refund
            # closing then takes exactly those seconds, so the two rows always
            # travel together in one transaction.
            database.add(
                BillingLedgerEntry(
                    id=uuid4(),
                    account_id=lot.account_id,
                    kind="refund_hold_release",
                    seconds=held_seconds,
                    lot_id=lot.id,
                    hold_id=hold.id,
                    valid_from=lot.valid_from,
                    expires_at=None,
                    plan_key=lot.plan_key,
                    source_ref=f"refund-release:{hold.id}",
                    actor_type="provider",
                    actor_person_id=None,
                    reason="refund settled",
                    audit_event_id=None,
                    created_at=now,
                )
            )
            await database.flush()
            if confirmed:
                await ledger.write_closing(
                    lot=lot,
                    kind="refund",
                    seconds=held_seconds,
                    remainder=held_seconds,
                    source_ref=f"refund:{lot.id}",
                    actor_type="provider",
                    reason="refund confirmed by the provider",
                )
        await database.flush()
        if confirmed and order.subscription_id is not None:
            subscription = await database.get(BillingSubscription, order.subscription_id)
            provider = self.service.providers.get(order.provider)
            recurring = recurring_provider(provider)
            if (
                subscription is not None
                and subscription.provider_subscription_ref is not None
                and recurring is not None
            ):
                # The refund is already verified; a provider hiccup on the
                # renewal stop is retried by reconciliation, never by the customer.
                with contextlib.suppress(ProviderError):
                    await recurring.cancel_subscription(
                        subscription.provider_subscription_ref, at_period_end=True
                    )
                await self._subscription_state(
                    database, subscription, "cancelled", None, "refunded", now
                )


__all__ = ["VERIFY_INTERVAL_SECONDS", "Settlement"]
