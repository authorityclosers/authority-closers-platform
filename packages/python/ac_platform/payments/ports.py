"""Provider-neutral payment contracts.

An adapter turns one provider's checkout, webhook, status and refund formats
into these shapes. Nothing here grants access: a verified ``PaymentEvent`` is a
fact for the payment service to record, and credits come only from the credit
ledger. Amounts are integers in minor units; floats are never accepted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from urllib.parse import urlsplit

from ac_platform.providers.ports import PermanentProviderError, ProviderError
from ac_platform.providers.service import ProviderWebhookRejected

# Currency -> number of minor-unit digits. Adding a currency is a catalogue decision.
SUPPORTED_CURRENCIES: Mapping[str, int] = MappingProxyType({"INR": 2, "USD": 2})
MAX_AMOUNT_MINOR = 10**12
# PayU limits its transaction id to 25 characters, the shortest limit of the providers.
MAX_ORDER_REFERENCE = 25
# PayU limits its refund token to 23 characters.
MAX_REFUND_KEY = 23
MAX_WEBHOOK_BODY_BYTES = 1_000_000

_ORDER_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{5,24}")
_REFUND_KEY = re.compile(r"[A-Za-z0-9]{6,23}")
_PROVIDER_NAME = re.compile(r"[a-z][a-z0-9_]{1,31}")
_FORBIDDEN_TEXT = ("\r", "\n", "\x00", "|")


class PaymentEventRejected(ProviderWebhookRejected):
    """A payment callback failed the authenticity, freshness or shape checks."""


class AmbiguousPaymentOutcomeError(ProviderError):
    """A money-moving call may have taken effect but returned no usable receipt.

    Never retry it blindly and never treat it as failed: reconcile it with
    ``fetch_payment`` or the provider's dashboard first.
    """


class RefundAlreadyRequestedError(PermanentProviderError):
    """The provider has already seen this refund idempotency key."""


class PaymentMode(StrEnum):
    TEST = "test"
    LIVE = "live"


class CheckoutKind(StrEnum):
    """How the browser reaches the provider's payment page."""

    REDIRECT = "redirect"
    FORM_POST = "form_post"
    CLIENT_SDK = "client_sdk"


class PaymentEventKind(StrEnum):
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    IGNORED = "ignored"
    # The provider could not complete a refund it had accepted.
    REFUND_FAILED = "refund_failed"
    # The customer approved the mandate and the subscription started.
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    # A subscription charge succeeded: one billing period was paid.
    SUBSCRIPTION_CHARGED = "subscription_charged"
    # A renewal charge failed and the provider is retrying it.
    SUBSCRIPTION_PAST_DUE = "subscription_past_due"
    # The provider gave up retrying; no further charge happens by itself.
    SUBSCRIPTION_HALTED = "subscription_halted"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_ENDED = "subscription_ended"


class PaymentState(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"


class RefundState(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"


def clean_text(value: object, name: str, *, maximum: int, minimum: int = 1) -> str:
    """Return bounded single-line text that is safe inside provider hash strings."""

    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    normalized = value.strip()
    if not minimum <= len(normalized) <= maximum:
        raise ValueError(f"{name} must be {minimum} to {maximum} characters")
    if any(mark in normalized for mark in _FORBIDDEN_TEXT):
        raise ValueError(f"{name} contains a forbidden character")
    return normalized


def require_https_url(value: object, name: str) -> str:
    url = clean_text(value, name, maximum=250)
    parsed = urlsplit(url)
    local = parsed.hostname in {"localhost", "127.0.0.1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError(f"{name} must be an HTTPS URL")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an absolute URL without credentials")
    return url


def require_order_reference(value: object) -> str:
    if not isinstance(value, str) or _ORDER_REFERENCE.fullmatch(value) is None:
        raise ValueError("order reference must be 6 to 25 letters, digits, '_' or '-'")
    return value


def require_refund_key(value: object) -> str:
    if not isinstance(value, str) or _REFUND_KEY.fullmatch(value) is None:
        raise ValueError("refund idempotency key must be 6 to 23 letters or digits")
    return value


def require_provider_name(value: object) -> str:
    if not isinstance(value, str) or _PROVIDER_NAME.fullmatch(value) is None:
        raise ValueError("provider name must be lower-case letters, digits or '_'")
    return value


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in the currency's minor unit (paise, cents)."""

    amount_minor: int
    currency: str

    def __post_init__(self) -> None:
        if type(self.amount_minor) is not int:
            raise ValueError("amount_minor must be an integer")
        if not 0 <= self.amount_minor <= MAX_AMOUNT_MINOR:
            raise ValueError("amount_minor is out of range")
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValueError("currency is not supported")

    @classmethod
    def from_decimal(cls, value: Decimal | int | str, currency: str) -> Money:
        """Build from a major-unit amount, refusing floats and fractions of a minor unit."""

        if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
            raise ValueError("amount must be a decimal, an integer or decimal text")
        code = currency.upper() if isinstance(currency, str) else ""
        if code not in SUPPORTED_CURRENCIES:
            raise ValueError("currency is not supported")
        try:
            major = Decimal(value)
        except InvalidOperation as error:
            raise ValueError("amount is not a decimal number") from error
        if not major.is_finite():
            raise ValueError("amount is not a decimal number")
        minor = major.scaleb(SUPPORTED_CURRENCIES[code])
        if minor != minor.to_integral_value():
            raise ValueError("amount has a fraction of a minor unit")
        return cls(int(minor), code)

    def decimal_text(self) -> str:
        """Exact major-unit text such as ``10.34``, for providers that take decimals."""

        digits = SUPPORTED_CURRENCIES[self.currency]
        whole, fraction = divmod(self.amount_minor, 10**digits)
        return f"{whole}.{fraction:0{digits}d}"


@dataclass(frozen=True, slots=True)
class CheckoutCustomer:
    """The little customer data a provider needs. Pass only what it requires."""

    customer_ref: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Za-z0-9_-]{3,50}", self.customer_ref) is None:
            raise ValueError("customer_ref must be 3 to 50 letters, digits, '_' or '-'")
        if self.name is not None:
            object.__setattr__(self, "name", clean_text(self.name, "name", maximum=60))
        if self.email is not None:
            email = clean_text(self.email, "email", maximum=254, minimum=3)
            if email.count("@") != 1 or " " in email:
                raise ValueError("email must be a single address")
            object.__setattr__(self, "email", email)
        if self.phone is not None and re.fullmatch(r"[0-9]{10}", self.phone) is None:
            raise ValueError("phone must be 10 digits")


@dataclass(frozen=True, slots=True)
class CheckoutOrder:
    """Our order as a provider needs to see it. ``reference`` is our own order key."""

    reference: str
    money: Money
    description: str
    customer: CheckoutCustomer
    return_url: str
    cancel_url: str | None = None
    notify_url: str | None = None

    def __post_init__(self) -> None:
        require_order_reference(self.reference)
        if self.money.amount_minor <= 0:
            raise ValueError("order amount must be greater than zero")
        object.__setattr__(
            self, "description", clean_text(self.description, "description", maximum=100)
        )
        object.__setattr__(self, "return_url", require_https_url(self.return_url, "return_url"))
        if self.cancel_url is not None:
            object.__setattr__(self, "cancel_url", require_https_url(self.cancel_url, "cancel_url"))
        if self.notify_url is not None:
            object.__setattr__(self, "notify_url", require_https_url(self.notify_url, "notify_url"))


@dataclass(frozen=True, slots=True)
class HostedCheckout:
    """What the browser needs to open the provider's payment page. Holds no secret."""

    provider: str
    provider_order_ref: str
    kind: CheckoutKind
    url: str
    fields: Mapping[str, str] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PaymentEvent:
    """One provider callback after its signature was verified.

    ``event_id`` is unique per provider event, so the service can store each
    event once. ``money`` is what the provider says was paid or refunded; the
    service must compare it with its own order copy before it credits anything.
    """

    provider: str
    event_id: str
    kind: PaymentEventKind
    event_type: str
    body_digest: str
    order_reference: str | None = None
    provider_order_ref: str | None = None
    provider_payment_ref: str | None = None
    provider_refund_ref: str | None = None
    money: Money | None = None
    occurred_at: datetime | None = None
    provider_subscription_ref: str | None = None
    provider_plan_ref: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    quantity: int | None = None


@dataclass(frozen=True, slots=True)
class PaymentSnapshot:
    """The provider's current answer for one order, for reconciliation."""

    provider: str
    provider_order_ref: str
    state: PaymentState
    provider_payment_ref: str | None = None
    paid: Money | None = None
    refunded_minor: int | None = None


@dataclass(frozen=True, slots=True)
class RefundReceipt:
    provider: str
    provider_refund_ref: str
    state: RefundState
    money: Money


class PaymentProvider(Protocol):
    """Port implemented by every payment adapter, fake or real."""

    @property
    def name(self) -> str:
        """Stable lower-case provider name, stored with orders and events."""

    @property
    def mode(self) -> PaymentMode:
        """Whether this adapter holds test or live credentials."""

    async def create_checkout(self, order: CheckoutOrder) -> HostedCheckout:
        """Register the order with the provider and return the hosted-page data."""

    def verify_event(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        *,
        now: datetime | None = None,
    ) -> PaymentEvent:
        """Verify a callback's signature over the raw body, then normalise it.

        Raises ``PaymentEventRejected`` when the callback cannot be trusted.
        """

    async def fetch_payment(
        self, *, order_reference: str, provider_order_ref: str
    ) -> PaymentSnapshot:
        """Ask the provider for the order's payment state (server to server)."""

    async def refund(
        self,
        *,
        order_reference: str,
        provider_payment_ref: str,
        money: Money,
        idempotency_key: str,
    ) -> RefundReceipt:
        """Request a refund once. The ledger changes only when the provider confirms."""


__all__ = [
    "MAX_AMOUNT_MINOR",
    "MAX_ORDER_REFERENCE",
    "MAX_REFUND_KEY",
    "MAX_WEBHOOK_BODY_BYTES",
    "SUPPORTED_CURRENCIES",
    "AmbiguousPaymentOutcomeError",
    "CheckoutCustomer",
    "CheckoutKind",
    "CheckoutOrder",
    "HostedCheckout",
    "Money",
    "PaymentEvent",
    "PaymentEventKind",
    "PaymentEventRejected",
    "PaymentMode",
    "PaymentProvider",
    "PaymentSnapshot",
    "PaymentState",
    "RefundAlreadyRequestedError",
    "RefundReceipt",
    "RefundState",
    "clean_text",
    "require_https_url",
    "require_order_reference",
    "require_provider_name",
    "require_refund_key",
]
