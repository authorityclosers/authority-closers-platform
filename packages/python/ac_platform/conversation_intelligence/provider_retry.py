"""Bounded transport retry assessment, separate from dispatch and money authority.

A complete empty refusal can be eligible for another attempt without proving
that the provider did no work or charged nothing. Worker claim limits are only
an additional ceiling; they never grant another external attempt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from ac_platform.conversation_intelligence.entitlements import Reservation
from ac_platform.conversation_intelligence.provider_failure_observation import (
    ProviderFailureObservation,
)
from ac_platform.outbox.repository import RetryPolicy

RetryState = Literal[
    "transport_retry_eligible",
    "reconciliation_required",
    "non_retryable",
    "claim_limit_exhausted",
    "authorization_window_exhausted",
]
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderRetryAssessment:
    state: RetryState
    not_before: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "not_before": None if self.not_before is None else self.not_before.isoformat(),
            "dispatch_authorized": False,
            "provider_charge_state": "unresolved",
        }


def assess_provider_retry(
    observation: ProviderFailureObservation,
    reservation: Reservation,
    *,
    observed_at: datetime,
    claim_count: int,
    claim_limit: int,
) -> ProviderRetryAssessment:
    """Assess one original response; do not schedule, reserve, refund or dispatch.

    Use the original durable observation time, so replay cannot move the retry
    deadline. Binding failures are errors, not retry classifications. A future
    coordinator must also check current consent, source, frozen route, retention,
    identity, execution permission and separately approved attempt/budget bounds.
    """

    if (
        type(claim_count) is not int
        or type(claim_limit) is not int
        or not 1 <= claim_count <= claim_limit <= 25
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise ValueError("invalid provider retry assessment bounds")
    observed_at = observed_at.astimezone(UTC)
    # Validate typed objects again at this boundary without JSON coercion.
    observation = ProviderFailureObservation.from_dict(observation.as_dict())
    reservation = Reservation.from_dict(reservation.as_dict())
    quote = reservation.quote
    if (
        reservation.state not in {"in_flight", "uncertain"}
        or observation.reservation_id != reservation.reservation_id
        or observation.attempt_id != reservation.attempt_id
        or observation.quote_fingerprint != quote.fingerprint
        or observation.provider != quote.provider_id
        or observation.model != quote.provider_model
        or observation.operation != quote.operation
        or observation.input_sha256 != quote.input_sha256
        or observed_at.timestamp() < quote.created_at_epoch
    ):
        raise ValueError("provider retry observation binding mismatch")
    if (
        not observation.response_body_complete
        or observation.response_body_observed_bytes != 0
        or observation.response_body_sha256 != _EMPTY_SHA256
    ):
        return ProviderRetryAssessment("reconciliation_required")
    if (
        observation.http_status not in _RETRY_STATUSES
        or observation.diagnostic_category is not None
    ):
        return ProviderRetryAssessment("non_retryable")
    if claim_count >= claim_limit:
        return ProviderRetryAssessment("claim_limit_exhausted")
    delay = RetryPolicy(max_attempts=claim_limit).delay_for_attempt(
        claim_count, jitter_key=observation.attempt_id
    )
    # Retry-After is a minimum wait, even when it exceeds our backoff cap.
    # A server wait outside the accepted execution window prevents retry.
    delay = max(delay, timedelta(seconds=observation.retry_after_seconds or 0))
    not_before = observed_at + delay
    if not_before.timestamp() >= min(
        quote.expires_at_epoch, reservation.permission.expires_at_epoch
    ):
        return ProviderRetryAssessment("authorization_window_exhausted")
    return ProviderRetryAssessment("transport_retry_eligible", not_before)
