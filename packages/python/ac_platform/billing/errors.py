"""Problem codes of Contract C1. The UI branches on ``code`` and shows ``detail``."""

from __future__ import annotations

from ac_platform.kernel.errors import DomainError


class BillingForbidden(DomainError):
    code = "billing_forbidden"
    title = "Billing is not available for this account"
    status = 403


class CreditEntryNotFound(DomainError):
    code = "credit_entry_not_found"
    title = "The credit entry does not exist"
    status = 404


class PlanNotFound(DomainError):
    code = "plan_not_found"
    title = "The plan does not exist"
    status = 404


class PackNotFound(DomainError):
    code = "pack_not_found"
    title = "The top-up pack does not exist"
    status = 404


class OrderNotFound(DomainError):
    code = "order_not_found"
    title = "The order does not exist"
    status = 404


class SubscriptionNotFound(DomainError):
    code = "subscription_not_found"
    title = "The subscription does not exist"
    status = 404


class PaymentNotFound(DomainError):
    code = "payment_not_found"
    title = "The payment does not exist"
    status = 404


class NotOnSale(DomainError):
    code = "not_on_sale"
    title = "Not on sale yet"
    status = 409


class SubscriptionExists(DomainError):
    code = "subscription_exists"
    title = "The account already has a subscription"
    status = 409


class TopUpNeedsPeriod(DomainError):
    code = "top_up_needs_period"
    title = "Top-ups need an active subscription period"
    status = 409


class BillingIdempotencyConflict(DomainError):
    code = "idempotency_conflict"
    title = "The idempotency key was used for a different request"
    status = 409


class SubscriptionNotActive(DomainError):
    code = "subscription_not_active"
    title = "The subscription is no longer active"
    status = 409


class PaymentUsed(DomainError):
    code = "payment_used"
    title = "Minutes from this payment were already used"
    status = 409


class BillingIdempotencyKeyRequired(DomainError):
    code = "idempotency_key_required"
    title = "An idempotency key is required"
    status = 428


class SeatsOutOfRange(DomainError):
    code = "seats_out_of_range"
    title = "The seat count is outside the plan's range"
    status = 422


class IntervalNotOffered(DomainError):
    code = "interval_not_offered"
    title = "The plan does not offer that billing interval"
    status = 422


class RefundWindowClosed(DomainError):
    code = "refund_window_closed"
    title = "The refund window has closed"
    status = 422


class BillingValidationFailed(DomainError):
    code = "validation_failed"
    title = "The request is invalid"
    status = 422


class BillingWebhookRejected(DomainError):
    code = "invalid_signature"
    title = "The payment callback signature is invalid"
    status = 400


class BillingRateLimited(DomainError):
    code = "rate_limited"
    title = "Try again in a moment"
    status = 429


class ProviderUnavailable(DomainError):
    code = "provider_unavailable"
    title = "The payment provider did not answer"
    status = 503


__all__ = [
    "BillingForbidden",
    "BillingIdempotencyConflict",
    "BillingIdempotencyKeyRequired",
    "BillingRateLimited",
    "BillingValidationFailed",
    "BillingWebhookRejected",
    "CreditEntryNotFound",
    "IntervalNotOffered",
    "NotOnSale",
    "OrderNotFound",
    "PackNotFound",
    "PaymentNotFound",
    "PaymentUsed",
    "PlanNotFound",
    "ProviderUnavailable",
    "RefundWindowClosed",
    "SeatsOutOfRange",
    "SubscriptionExists",
    "SubscriptionNotActive",
    "SubscriptionNotFound",
    "TopUpNeedsPeriod",
]
