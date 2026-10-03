"""Checkout, orders, subscriptions, refunds and provider webhooks (Contract C1).

The router owns request shapes, origin and header rules and the no-store
headers. Every billing rule lives behind :class:`BillingCommands`. Without a
composed command service the routes are not installed at all, so a screen that
ships first sees a plain 404 and shows "Not on sale yet".
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.commands import BillingCommands, Caller, CheckoutCommand
from ac_platform.billing.errors import BillingIdempotencyKeyRequired, BillingValidationFailed
from ac_platform.billing.tax import TaxMode
from ac_platform.billing.views import (
    AccountName,
    CancelState,
    HostedKind,
    Interval,
    Mode,
    OrderKind,
    OrderStatus,
    RefundReasonCode,
    RefundState,
    SubscriptionStatus,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_REASON_LENGTH = 500
_PROVIDERS = {"razorpay", "fake"}


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: OrderKind
    account: AccountName
    plan_key: StrictStr = Field(min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]{1,39}$")
    interval: Interval | None = None
    seats: StrictInt | None = Field(default=None, ge=1, le=50)
    pack_key: StrictStr | None = Field(
        default=None, min_length=2, max_length=40, pattern=r"^[a-z][a-z0-9_]{1,39}$"
    )

    @model_validator(mode="after")
    def check_kind_fields(self) -> CheckoutRequest:
        if self.kind == "subscription" and (
            self.interval is None or self.seats is None or self.pack_key is not None
        ):
            raise ValueError("a subscription names interval and seats and no pack_key")
        if self.kind == "top_up" and (
            self.pack_key is None or self.interval is not None or self.seats is not None
        ):
            raise ValueError("a top-up names pack_key and neither interval nor seats")
        return self


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: StrictStr | None = Field(default=None, max_length=MAX_REASON_LENGTH)


class RefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: StrictStr = Field(min_length=1, max_length=MAX_REASON_LENGTH)


class MoneyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    minor: int
    currency: str
    gst_inclusive: bool


class TaxResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    mode: TaxMode
    rate_basis_points: int
    taxable_minor: int
    gst_minor: int
    total_minor: int


class RefundResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    payment_id: str
    refundable_until: datetime | None
    state: RefundState
    reason_code: RefundReasonCode | None


class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    order_id: str
    kind: OrderKind
    account: AccountName
    status: OrderStatus
    mode: Mode
    amount: MoneyResponse
    tax: TaxResponse
    plan_key: str
    plan_name: str
    interval: Interval | None
    seats: int
    pack_key: str | None
    minutes: int
    subscription_id: str | None
    created_at: datetime
    paid_at: datetime | None
    refund: RefundResponse | None


class HostedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    provider: str
    kind: HostedKind
    url: str | None
    params: dict[str, str]
    expires_at: datetime | None


class CheckoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    order: OrderResponse
    hosted: HostedResponse


class PeriodResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    start: datetime
    end: datetime


class SubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    subscription_id: str
    account: AccountName
    plan_key: str
    plan_name: str
    interval: Interval
    seats: int
    amount: MoneyResponse
    mode: Mode
    status: SubscriptionStatus
    current_period: PeriodResponse | None
    renews_at: datetime | None
    cancel_at_period_end: bool
    cancel_state: CancelState
    renewal_needs_customer_approval: bool
    created_at: datetime


class SubscriptionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    current: SubscriptionResponse | None
    past: list[SubscriptionResponse]


class RefundCommandResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refund: RefundResponse


class WebhookResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received: Literal[True] = True
    outcome: str
    replayed: bool


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise BillingIdempotencyKeyRequired("Send an Idempotency-Key header with this request.")
    key = value.strip()
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise BillingValidationFailed("The Idempotency-Key header is too long.")
    return key


def _body_digest(body: BaseModel) -> str:
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"


def _caller(request: Request, auth: AuthenticatedTransaction) -> Caller:
    actor = auth.resolved.actor
    return Caller(
        person_id=actor.person_id,
        session_id=actor.session_id,
        tenant_id=actor.tenant_id,
        membership_role=auth.resolved.membership_role,
        request_id=getattr(request.state, "request_id", None),
    )


IdempotencyHeader = Annotated[
    str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH + 64)
]


def install_billing_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    commands: BillingCommands | None,
) -> None:
    """Install the C1 routes. ``commands`` is None when billing is not composed."""

    if commands is None:
        return
    service = commands
    router = APIRouter(prefix="/v1", tags=["billing"])
    actor_dependency = Depends(require_actor, scope="function")
    read_require_actor = getattr(require_actor, "read_only", require_actor)
    read_actor_dependency = Depends(read_require_actor, scope="function")

    @router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
    async def checkout(
        request: Request,
        response: Response,
        body: CheckoutRequest,
        idempotency_key: IdempotencyHeader = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CheckoutResponse:
        require_safe_origin(request, settings)
        if request.query_params:
            raise BillingValidationFailed("Checkout accepts no query parameters.")
        key = _idempotency_key(idempotency_key)
        command = CheckoutCommand(
            kind=body.kind,
            account=body.account,
            plan_key=body.plan_key,
            interval=body.interval,
            seats=body.seats,
            pack_key=body.pack_key,
            idempotency_key=key,
            body_sha256=_body_digest(body),
        )
        result = await service.checkout(auth.database, _caller(request, auth), command)
        _no_store(response)
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return CheckoutResponse.model_validate(result)

    @router.get("/orders/{order_id}", response_model=OrderResponse)
    async def read_order(
        order_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> OrderResponse:
        if request.query_params:
            raise BillingValidationFailed("The order read accepts no query parameters.")
        view = await service.read_order(auth.database, _caller(request, auth), order_id)
        _no_store(response)
        return OrderResponse.model_validate(view)

    @router.post("/orders/{order_id}/verify", response_model=OrderResponse)
    async def verify_order(
        order_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        idempotency_key: IdempotencyHeader = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> OrderResponse:
        require_safe_origin(request, settings)
        key = _idempotency_key(idempotency_key)
        view = await service.verify_order(
            auth.database, _caller(request, auth), order_id, idempotency_key=key
        )
        _no_store(response)
        return OrderResponse.model_validate(view)

    @router.get("/subscriptions", response_model=SubscriptionsResponse)
    async def read_subscriptions(
        request: Request,
        response: Response,
        account: Annotated[AccountName, Query()] = "personal",
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> SubscriptionsResponse:
        if set(request.query_params) - {"account"}:
            raise BillingValidationFailed("Only the account query parameter is accepted.")
        view = await service.read_subscriptions(auth.database, _caller(request, auth), account)
        _no_store(response)
        return SubscriptionsResponse.model_validate(view)

    @router.get("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
    async def read_subscription(
        subscription_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> SubscriptionResponse:
        if request.query_params:
            raise BillingValidationFailed("The subscription read accepts no query parameters.")
        view = await service.read_subscription(
            auth.database, _caller(request, auth), subscription_id
        )
        _no_store(response)
        return SubscriptionResponse.model_validate(view)

    @router.post("/subscriptions/{subscription_id}/cancel", response_model=SubscriptionResponse)
    async def cancel_subscription(
        subscription_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: CancelRequest,
        idempotency_key: IdempotencyHeader = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> SubscriptionResponse:
        require_safe_origin(request, settings)
        key = _idempotency_key(idempotency_key)
        reason = body.reason.strip() if body.reason is not None else None
        view = await service.cancel_subscription(
            auth.database,
            _caller(request, auth),
            subscription_id,
            reason=reason or None,
            idempotency_key=key,
        )
        _no_store(response)
        return SubscriptionResponse.model_validate(view)

    @router.post("/payments/{payment_id}/refund", response_model=RefundCommandResponse)
    async def refund_payment(
        payment_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
        request: Request,
        response: Response,
        body: RefundRequest,
        idempotency_key: IdempotencyHeader = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> RefundCommandResponse:
        require_safe_origin(request, settings)
        key = _idempotency_key(idempotency_key)
        reason = body.reason
        if not reason.strip():
            raise BillingValidationFailed("A refund reason is required.")
        view = await service.refund_payment(
            auth.database,
            _caller(request, auth),
            payment_id,
            reason=reason,
            idempotency_key=key,
        )
        _no_store(response)
        response.status_code = (
            status.HTTP_202_ACCEPTED if view.state == "pending" else status.HTTP_200_OK
        )
        return RefundCommandResponse(refund=RefundResponse.model_validate(view))

    @router.post(
        "/platform/billing/payments/{payment_id}/refund", response_model=RefundCommandResponse
    )
    async def staff_refund_payment(
        payment_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
        request: Request,
        response: Response,
        body: RefundRequest,
        idempotency_key: IdempotencyHeader = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> RefundCommandResponse:
        require_admin_surface(request, settings)
        require_safe_origin(request, settings)
        permissions = await platform_projection(
            auth.database, auth.resolved.actor, operations_tenant_id=settings.operations_tenant_id
        )
        if "platform_billing_manage" not in permissions:
            raise CapabilityDenied("A current platform billing assignment is required.")
        key = _idempotency_key(idempotency_key)
        if not body.reason.strip():
            raise BillingValidationFailed("A refund reason is required.")
        view = await service.staff_refund_payment(
            auth.database,
            _caller(request, auth),
            payment_id,
            reason=body.reason,
            idempotency_key=key,
        )
        _no_store(response)
        response.status_code = (
            status.HTTP_202_ACCEPTED if view.state == "pending" else status.HTTP_200_OK
        )
        return RefundCommandResponse(refund=RefundResponse.model_validate(view))

    application.include_router(router)


def install_billing_webhook_http(
    application: FastAPI,
    *,
    sessions: object,
    commands: BillingCommands | None,
) -> None:
    """Install the provider callback route. It has no session; the signature is the proof."""

    if commands is None:
        return
    service = commands
    router = APIRouter(prefix="/v1/payments/webhooks", tags=["billing-webhooks"])

    @router.post("/{provider}", response_model=WebhookResponse)
    async def receive(
        provider: Annotated[str, Path(min_length=2, max_length=32, pattern=r"^[a-z]+$")],
        request: Request,
        response: Response,
    ) -> WebhookResponse:
        if provider not in _PROVIDERS or request.query_params:
            raise BillingValidationFailed("Unknown payment provider callback.")
        raw_body = await request.body()
        headers = {name.lower(): value for name, value in request.headers.items()}
        session_factory = sessions
        assert callable(session_factory)  # composition passes async_sessionmaker
        async with session_factory() as database, database.begin():
            receipt = await service.receive_webhook(database, provider, headers, raw_body)
        response.headers["Cache-Control"] = "no-store"
        return WebhookResponse(outcome=receipt.outcome, replayed=receipt.replayed)

    application.include_router(router)


__all__ = [
    "CancelRequest",
    "CheckoutRequest",
    "CheckoutResponse",
    "OrderResponse",
    "RefundCommandResponse",
    "RefundRequest",
    "SubscriptionResponse",
    "SubscriptionsResponse",
    "WebhookResponse",
    "install_billing_http",
    "install_billing_webhook_http",
]
