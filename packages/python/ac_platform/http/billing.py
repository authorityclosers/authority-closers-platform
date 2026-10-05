"""Checkout, orders, subscriptions, refunds and provider webhooks (Contract C1).

The router owns request shapes, account-scoped tax document reads, origin and header
rules and the no-store headers. Payment commands live behind :class:`BillingCommands`.
Without a composed command service the routes are not installed at all, so a
screen that ships first sees a plain 404 and shows "Not on sale yet".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator
from sqlalchemy import exists, select, tuple_

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.application import BillingApplication
from ac_platform.billing.commands import BillingCommands, BuyerTaxDetails, Caller, CheckoutCommand
from ac_platform.billing.credit_reads import CreditReads
from ac_platform.billing.errors import (
    BillingForbidden,
    BillingIdempotencyKeyRequired,
    BillingValidationFailed,
    BillingWebhookRejected,
)
from ac_platform.billing.invoice_models import BillingCreditNote, BillingInvoice
from ac_platform.billing.invoice_render import render_credit_note, render_invoice
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.simulation import FakeCheckout, SimulationAction, payment_page
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
    identity_error_handler,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.problem import domain_error_handler
from ac_platform.identity.services import (
    AccountUnavailableError,
    EmailVerificationRequiredError,
    IdentityServiceError,
    TenantScopeDeniedError,
)
from ac_platform.kernel.errors import DomainError
from ac_platform.payments.ports import PaymentEventRejected
from ac_platform.payments.registry import UnknownPaymentProviderError
from ac_platform.tenancy.models import Membership

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_REASON_LENGTH = 500
_PROVIDERS = {"razorpay", "fake"}


class BuyerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: StrictStr = Field(min_length=1, max_length=200)
    gstin: StrictStr | None = Field(default=None, pattern=r"^[0-9]{2}[A-Z0-9]{13}$")
    state_code: StrictStr | None = Field(default=None, pattern=r"^[0-9]{2}$")

    @model_validator(mode="after")
    def check_gstin_state(self) -> BuyerRequest:
        if self.gstin is not None:
            state = self.gstin[:2]
            if self.state_code is not None and self.state_code != state:
                raise ValueError("state_code must match the GSTIN's first two digits")
            self.state_code = state
        return self


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: OrderKind
    account: AccountName
    buyer: BuyerRequest | None = None
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


class InvoiceNotFound(DomainError):
    code = "invoice_not_found"
    title = "The invoice does not exist"
    status = 404


class TaxDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    number: str
    created_at: datetime
    currency: str
    taxable_minor: int
    cgst_minor: int
    sgst_minor: int
    igst_minor: int
    total_minor: int
    place_of_supply: str | None


class InvoiceResponse(TaxDocumentResponse):
    invoice_id: UUID = Field(validation_alias="id")


class CreditNoteResponse(TaxDocumentResponse):
    credit_note_id: UUID = Field(validation_alias="id")
    invoice_id: UUID
    refund_ref: str


class CreditNotesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credit_notes: list[CreditNoteResponse]
    next_before: UUID | None


class InvoicesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invoices: list[InvoiceResponse]
    next_before: UUID | None


class CreditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: AccountName = "personal"


class CreditHistoryQuery(CreditQuery):
    limit: int = Field(default=50, ge=1, le=100)
    before: UUID | None = None


class CreditBalanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)
    account: AccountName
    account_id: UUID | None
    balance: StrictStr


class CreditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)
    entry_id: UUID
    quantity: StrictStr
    created_at: datetime
    corrected_entry_id: UUID | None


class CreditHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, from_attributes=True)
    account: AccountName
    account_id: UUID | None
    entries: list[CreditEntryResponse]
    next_before: UUID | None


class _CreditReadRoute(APIRoute):
    """Keep credit read errors private, including dependency and query failures."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def read(request: Request) -> Response:
            try:
                response = await handler(request)
            except RequestValidationError:
                response = await domain_error_handler(
                    request, BillingValidationFailed("The credit read query is invalid.")
                )
            except (
                AccountUnavailableError,
                EmailVerificationRequiredError,
                TenantScopeDeniedError,
            ):
                response = await domain_error_handler(
                    request, BillingForbidden("This caller cannot read billing credits.")
                )
            except IdentityServiceError as error:
                response = await identity_error_handler(request, error)
            except DomainError as error:
                response = await domain_error_handler(request, error)
            _no_store(response)
            return response

        return read


async def _invoice_account(
    auth: AuthenticatedTransaction, settings: Settings, account: AccountName
) -> UUID | None:
    """Read existing accounts only; use current membership, not the session's role copy."""
    actor = auth.resolved.actor
    statement = select(BillingAccount.id).where(BillingAccount.kind == account)
    if settings.operations_tenant_id is not None:
        if actor.tenant_id == settings.operations_tenant_id:
            raise InvoiceNotFound("That invoice does not exist.")
        statement = statement.where(BillingAccount.tenant_id != settings.operations_tenant_id)
    if account == "personal":
        statement = statement.where(BillingAccount.person_id == actor.person_id)
        if settings.public_learner_tenant_id is not None:
            statement = statement.where(
                BillingAccount.tenant_id == settings.public_learner_tenant_id
            )
    else:
        membership = exists().where(
            Membership.tenant_id == BillingAccount.tenant_id,
            Membership.person_id == actor.person_id,
            Membership.role.in_(("owner", "admin")),
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
        statement = statement.where(BillingAccount.tenant_id == actor.tenant_id, membership)
    account_id: UUID | None = await auth.database.scalar(statement)
    if account == "organisation" and account_id is None:
        raise InvoiceNotFound("That invoice does not exist.")
    return account_id


async def _read_invoice(
    auth: AuthenticatedTransaction, settings: Settings, invoice_id: UUID
) -> BillingInvoice:
    invoice = await auth.database.get(BillingInvoice, invoice_id)
    account = (
        None if invoice is None else await auth.database.get(BillingAccount, invoice.account_id)
    )
    if account is None or account.kind not in {"personal", "organisation"}:
        raise InvoiceNotFound("That invoice does not exist.")
    name: AccountName = "personal" if account.kind == "personal" else "organisation"
    if await _invoice_account(auth, settings, name) != account.id:
        raise InvoiceNotFound("That invoice does not exist.")
    assert invoice is not None
    return invoice


async def _read_credit_note(
    auth: AuthenticatedTransaction, settings: Settings, credit_note_id: UUID
) -> BillingCreditNote:
    note = await auth.database.get(BillingCreditNote, credit_note_id)
    if note is None:
        raise InvoiceNotFound("That invoice does not exist.")
    invoice = await _read_invoice(auth, settings, note.invoice_id)
    if note.account_id != invoice.account_id:
        raise InvoiceNotFound("That invoice does not exist.")
    return note


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise BillingIdempotencyKeyRequired("Send an Idempotency-Key header with this request.")
    key = value.strip()
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise BillingValidationFailed("The Idempotency-Key header is too long.")
    return key


def _body_digest(body: BaseModel) -> str:
    data = body.model_dump(mode="json")
    if isinstance(body, CheckoutRequest) and body.buyer is None:
        data.pop("buyer")  # Preserve pre-invoice checkout idempotency digests.
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
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

    credit_router = APIRouter(prefix="/billing/credits", route_class=_CreditReadRoute)

    def credit_reads(auth: AuthenticatedTransaction) -> CreditReads:
        return CreditReads(
            auth.database,
            public_learner_tenant_id=settings.public_learner_tenant_id,
            operations_tenant_id=settings.operations_tenant_id,
        )

    @credit_router.get("", response_model=CreditBalanceResponse)
    async def read_credits(
        request: Request,
        query: Annotated[CreditQuery, Query()],
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> CreditBalanceResponse:
        return CreditBalanceResponse.model_validate(
            await credit_reads(auth).balance(_caller(request, auth), query.account)
        )

    @credit_router.get("/history", response_model=CreditHistoryResponse)
    async def read_credit_history(
        request: Request,
        query: Annotated[CreditHistoryQuery, Query()],
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> CreditHistoryResponse:
        return CreditHistoryResponse.model_validate(
            await credit_reads(auth).history(
                _caller(request, auth), query.account, limit=query.limit, before=query.before
            )
        )

    router.include_router(credit_router)

    @router.get("/invoices", response_model=InvoicesResponse)
    async def list_invoices(
        request: Request,
        response: Response,
        account: Annotated[AccountName, Query()] = "personal",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> InvoicesResponse:
        if set(request.query_params) - {"account", "limit", "before"}:
            raise BillingValidationFailed("Only account, limit and before are accepted.")
        account_id = await _invoice_account(auth, settings, account)
        statement = select(BillingInvoice).where(BillingInvoice.account_id == account_id)
        if before is not None:
            cursor = await _read_invoice(auth, settings, before)
            if cursor.account_id != account_id:
                raise InvoiceNotFound("That invoice does not exist.")
            statement = statement.where(
                tuple_(BillingInvoice.created_at, BillingInvoice.id)
                < (cursor.created_at, cursor.id)
            )
        rows = list(
            await auth.database.scalars(
                statement.order_by(
                    BillingInvoice.created_at.desc(), BillingInvoice.id.desc()
                ).limit(limit + 1)
            )
        )
        _no_store(response)
        return InvoicesResponse(
            invoices=[InvoiceResponse.model_validate(row) for row in rows[:limit]],
            next_before=rows[limit - 1].id if len(rows) > limit else None,
        )

    @router.get("/invoices/{invoice_id}/download", response_class=HTMLResponse)
    async def download_invoice(
        invoice_id: Annotated[UUID, Path()],
        request: Request,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> HTMLResponse:
        if request.query_params:
            raise BillingValidationFailed("Invoice downloads accept no query parameters.")
        invoice = await _read_invoice(auth, settings, invoice_id)
        response = HTMLResponse(render_invoice(invoice))
        _no_store(response)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="invoice-{invoice_id}.html"'
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @router.get("/credit-notes", response_model=CreditNotesResponse)
    async def list_credit_notes(
        request: Request,
        response: Response,
        account: Annotated[AccountName, Query()] = "personal",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before: Annotated[UUID | None, Query()] = None,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> CreditNotesResponse:
        if set(request.query_params) - {"account", "limit", "before"}:
            raise BillingValidationFailed("Only account, limit and before are accepted.")
        account_id = await _invoice_account(auth, settings, account)
        statement = select(BillingCreditNote).where(BillingCreditNote.account_id == account_id)
        if before is not None:
            cursor = await _read_credit_note(auth, settings, before)
            if cursor.account_id != account_id:
                raise InvoiceNotFound("That invoice does not exist.")
            statement = statement.where(
                tuple_(BillingCreditNote.created_at, BillingCreditNote.id)
                < (cursor.created_at, cursor.id)
            )
        rows = list(
            await auth.database.scalars(
                statement.order_by(
                    BillingCreditNote.created_at.desc(), BillingCreditNote.id.desc()
                ).limit(limit + 1)
            )
        )
        _no_store(response)
        return CreditNotesResponse(
            credit_notes=[CreditNoteResponse.model_validate(row) for row in rows[:limit]],
            next_before=rows[limit - 1].id if len(rows) > limit else None,
        )

    @router.get("/credit-notes/{credit_note_id}/download", response_class=HTMLResponse)
    async def download_credit_note(
        credit_note_id: Annotated[UUID, Path()],
        request: Request,
        auth: AuthenticatedTransaction = read_actor_dependency,
    ) -> HTMLResponse:
        if request.query_params:
            raise BillingValidationFailed("Credit note downloads accept no query parameters.")
        note = await _read_credit_note(auth, settings, credit_note_id)
        response = HTMLResponse(render_credit_note(note))
        _no_store(response)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="credit-note-{credit_note_id}.html"'
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
            buyer=None if body.buyer is None else BuyerTaxDetails(**body.buyer.model_dump()),
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
            try:
                receipt = await service.receive_webhook(database, provider, headers, raw_body)
            except PaymentEventRejected as error:
                raise BillingWebhookRejected(
                    "The payment callback could not be verified."
                ) from error
            except UnknownPaymentProviderError as error:
                raise BillingValidationFailed("Unknown payment provider callback.") from error
        response.headers["Cache-Control"] = "no-store"
        return WebhookResponse(outcome=receipt.outcome, replayed=receipt.replayed)

    application.include_router(router)

    if isinstance(service, BillingApplication) and "fake" in service.service.providers.names:
        simulation = FakeCheckout(service.service)
        origin = service.service.fake_checkout_base_url

        @application.get("/v1/payments/fake/checkout/{order_id}", response_class=HTMLResponse)
        async def fake_checkout_page(
            order_id: UUID,
            token: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")],
        ) -> HTMLResponse:
            assert callable(sessions)
            async with sessions() as database, database.begin():
                order = await simulation.read(database, order_id, token)
            return HTMLResponse(
                payment_page(order, token, service.service.return_url(order_id)),
                headers={
                    "Cache-Control": "no-store",
                    "Referrer-Policy": "strict-origin",
                    # Chromium checks form-action through the POST's 303 redirect.
                    "Content-Security-Policy": "default-src 'none'; form-action 'self' "
                    f"{service.service.return_origin}; base-uri 'none'; frame-ancestors 'none'",
                },
            )

        @application.post("/v1/payments/fake/checkout/{order_id}/{action}")
        async def fake_checkout_submit(
            order_id: UUID,
            action: SimulationAction,
            request: Request,
            token: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")],
        ) -> RedirectResponse:
            if origin is None or request.headers.get("origin") != origin:
                raise BillingValidationFailed("Use the test payment page to submit this choice.")
            assert callable(sessions)
            async with sessions() as database, database.begin():
                url = await simulation.submit(database, order_id, token, action)
            return RedirectResponse(
                url,
                status_code=303,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "strict-origin"},
            )


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
