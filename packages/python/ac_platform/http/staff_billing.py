"""Admin billing overview and audited staff credit grants."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator
from sqlalchemy import select

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied, CapabilityInvalid
from ac_platform.billing.credit_grants import CreditGrantService
from ac_platform.billing.credits import validate_credit_quantity
from ac_platform.billing.errors import (
    BillingForbidden,
    BillingIdempotencyConflict,
    BillingIdempotencyKeyRequired,
    BillingValidationFailed,
)
from ac_platform.billing.ledger import BillingConflict, BillingError
from ac_platform.billing.models import BillingAccount
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
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


class CreditGrantRequest(_Strict):
    quantity: StrictStr = Field(pattern=r"^[0-9]+(\.[0-9]+)?$")
    reason: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("quantity")
    @classmethod
    def exact_positive_quantity(cls, value: str) -> str:
        try:
            quantity = Decimal(value)
            validate_credit_quantity(quantity)
            if quantity < 0 or value != value.strip() or "_" in value:
                raise BillingError("Invalid credit quantity.")
        except (InvalidOperation, BillingError) as error:
            raise ValueError(
                "An exact positive finite credit quantity string is required."
            ) from error
        return value

    @field_validator("reason")
    @classmethod
    def named_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("A reason is required.")
        return value


class CreditGrantResponse(_Strict):
    entry_id: StrictStr
    account_id: StrictStr
    quantity: StrictStr
    source_ref: StrictStr
    audit_event_id: StrictStr
    created_at: StrictStr


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

    @router.post(
        "/billing/accounts/{tenant_id}/{account_id}/credit-grants",
        response_model=CreditGrantResponse,
    )
    async def grant_credits(
        tenant_id: UUID,
        account_id: UUID,
        request: Request,
        body: CreditGrantRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CreditGrantResponse:
        require_safe_origin(request, settings)
        if request.query_params:
            raise CapabilityInvalid("Credit grants accept no query parameters.")
        actor = auth.resolved.actor
        permissions = await platform_projection(
            auth.database, actor, operations_tenant_id=settings.operations_tenant_id
        )
        if "platform_access_manage" not in permissions:
            raise CapabilityDenied("A current platform access-management assignment is required.")
        if idempotency_key is None or not idempotency_key.strip():
            raise BillingIdempotencyKeyRequired("Supply a stable Idempotency-Key for this grant.")
        if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
            raise CapabilityDenied("Staff credit grants are unavailable.")
        # Check stored ownership only after fresh authority; never create a target
        # or trust a caller's person/account-kind hint to bypass self-grant refusal.
        account = await auth.database.scalar(
            select(BillingAccount).where(
                BillingAccount.id == account_id, BillingAccount.tenant_id == tenant_id
            )
        )
        if account is None:
            raise BillingForbidden("The billing account is unavailable.")
        if account.kind == "personal" and account.person_id == actor.person_id:
            raise BillingForbidden("Staff cannot grant credits to their own Personal account.")
        try:
            receipt = await CreditGrantService(
                auth.database,
                operations_tenant_id=settings.operations_tenant_id,
                public_learner_tenant_id=settings.public_learner_tenant_id,
            ).grant(
                actor=actor,
                tenant_id=tenant_id,
                account_id=account_id,
                quantity=Decimal(body.quantity),
                operation_id=idempotency_key,
                reason=body.reason,
            )
        except BillingConflict as error:
            raise BillingIdempotencyConflict(str(error)) from error
        except BillingError as error:
            raise BillingValidationFailed(str(error)) from error
        return CreditGrantResponse.model_validate(receipt.to_dict())

    application.include_router(router)


__all__ = ["BILLING_CAPABILITY", "StaffBillingResponse", "install_staff_billing_http"]
