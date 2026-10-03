"""Admin → Billing staff read (AUT-879); refunds and grants keep their own routes."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied, CapabilityInvalid
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_admin_surface
from ac_platform.staff_billing.read import PAGE_LIMIT, billing_overview

BILLING_CAPABILITY = "platform_billing_manage"
OrderStatus = Literal["awaiting_payment", "confirming", "paid", "failed", "expired", "needs_review"]
SubscriptionStatus = Literal[
    "pending_authorisation", "active", "past_due", "halted", "cancelled", "ended"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class CustomerResponse(_Strict):
    account_id: UUID
    kind: Literal["personal", "organisation"]
    name: str | None
    email: str | None


class OrderResponse(_Strict):
    order_id: UUID
    order_ref: str
    kind: Literal["subscription", "top_up"]
    mode: Literal["test", "live"]
    provider: str
    provider_order_ref: str | None
    customer: CustomerResponse
    plan_key: str
    plan_name: str
    interval: Literal["month", "year"] | None
    seats: int
    minutes: int
    amount_minor: int
    currency: str
    gst_inclusive: bool
    status: OrderStatus
    created_at: datetime


class PaymentResponse(_Strict):
    payment_id: str
    event: Literal["payment.captured", "payment.failed", "subscription.charged"]
    provider: str
    order_id: UUID | None
    order_ref: str | None
    subscription_id: UUID | None
    customer: CustomerResponse | None
    plan_name: str | None
    seats: int | None
    amount_minor: int | None
    currency: str | None
    gst_inclusive: bool | None
    verified_at: datetime
    refund_state: Literal["available", "pending", "refunded", "refused", "unavailable"] | None
    refundable_until: datetime | None


class RefundResponse(_Strict):
    payment_id: str
    order_id: UUID
    customer: CustomerResponse | None
    state: Literal["pending", "refunded", "refused"]
    amount_minor: int
    currency: str
    reason: str
    provider_refund_ref: str | None
    requested_at: datetime
    updated_at: datetime


class SubscriptionResponse(_Strict):
    subscription_id: UUID
    mode: Literal["test", "live"]
    provider: str
    provider_subscription_ref: str | None
    customer: CustomerResponse
    plan_key: str
    plan_name: str
    interval: Literal["month", "year"]
    seats: int
    amount_minor: int
    currency: str
    gst_inclusive: bool
    status: SubscriptionStatus
    cancel_state: Literal["none", "requested", "confirmed"]
    cancel_at_period_end: bool
    current_period_end: datetime | None
    renews_at: datetime | None
    created_at: datetime


class StaffBillingResponse(_Strict):
    generated_at: datetime
    page_limit: int
    orders: list[OrderResponse]
    payments: list[PaymentResponse]
    refunds: list[RefundResponse]
    subscriptions: list[SubscriptionResponse]


def install_staff_billing_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    def require_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    router = APIRouter(prefix="/v1/platform", dependencies=[Depends(require_surface)])
    # The fresh capability read takes share locks, so it needs the ordinary actor.
    actor_dependency = Depends(require_actor, scope="function")

    @router.get("/billing", response_model=StaffBillingResponse)
    async def billing(
        request: Request, auth: AuthenticatedTransaction = actor_dependency
    ) -> StaffBillingResponse:
        if request.query_params:
            raise CapabilityInvalid("The billing overview accepts no query parameters.")
        permissions = await platform_projection(
            auth.database, auth.resolved.actor, operations_tenant_id=settings.operations_tenant_id
        )
        if BILLING_CAPABILITY not in permissions:
            raise CapabilityDenied("A current platform billing assignment is required.")
        now = datetime.now(UTC)
        overview = await billing_overview(auth.database, now=now)
        return StaffBillingResponse(
            generated_at=now,
            page_limit=PAGE_LIMIT,
            orders=[OrderResponse.model_validate(row) for row in overview.orders],
            payments=[PaymentResponse.model_validate(row) for row in overview.payments],
            refunds=[RefundResponse.model_validate(row) for row in overview.refunds],
            subscriptions=[
                SubscriptionResponse.model_validate(row) for row in overview.subscriptions
            ],
        )

    application.include_router(router)


__all__ = ["BILLING_CAPABILITY", "StaffBillingResponse", "install_staff_billing_http"]
