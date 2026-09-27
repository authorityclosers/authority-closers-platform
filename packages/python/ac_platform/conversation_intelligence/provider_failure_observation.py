"""Strict, content-free observations for complete or truncated provider failures.

This object records transport facts only. It does not decide whether a failed
request may be retried or whether a provider charge is zero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

PROVIDER_FAILURE_OBSERVATION_SCHEMA = "ac.sales_xray.provider_failure_observation/1"
MAX_ERROR_RESPONSE_BODY_BYTES = 16_384
MAX_RETRY_AFTER_SECONDS = 3_600

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_DIAGNOSTIC_CATEGORIES = frozenset(
    {
        "credential_reported_exposed",
        "key_invalid",
        "key_service_restriction",
        "billing_configuration",
        "location_restriction",
        "model_or_endpoint_unavailable",
        "permission_denied",
        "service_disabled",
        "structured_schema_complexity",
        "structured_schema_depth",
        "structured_schema_null",
        "structured_schema_rejected",
    }
)


@dataclass(frozen=True, slots=True)
class ProviderFailureObservation:
    """A sanitized, attempt-bound HTTP failure observation."""

    reservation_id: str
    attempt_id: str
    quote_fingerprint: str
    provider: str
    model: str
    operation: str
    input_sha256: str
    http_status: int
    response_body_complete: bool
    response_body_observed_bytes: int
    response_body_sha256: str | None
    provider_request_id_sha256: str | None
    retry_after_seconds: int | None
    diagnostic_category: str | None

    def __post_init__(self) -> None:
        for value in (
            self.reservation_id,
            self.attempt_id,
            self.provider,
            self.model,
            self.operation,
        ):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError("invalid provider failure observation")
        for value in (self.quote_fingerprint, self.input_sha256):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError("invalid provider failure observation")
        if (
            type(self.http_status) is not int
            or not 100 <= self.http_status <= 599
            or self.http_status == 200
        ):
            raise ValueError("invalid provider failure observation")
        if type(self.response_body_complete) is not bool:
            raise ValueError("invalid provider failure observation")
        if (
            type(self.response_body_observed_bytes) is not int
            or not 0 <= self.response_body_observed_bytes <= MAX_ERROR_RESPONSE_BODY_BYTES
        ):
            raise ValueError("invalid provider failure observation")
        if self.response_body_complete:
            if (
                not isinstance(self.response_body_sha256, str)
                or _SHA256.fullmatch(self.response_body_sha256) is None
            ):
                raise ValueError("invalid provider failure observation")
        elif self.response_body_sha256 is not None:
            raise ValueError("invalid provider failure observation")
        if self.provider_request_id_sha256 is not None and (
            not isinstance(self.provider_request_id_sha256, str)
            or _SHA256.fullmatch(self.provider_request_id_sha256) is None
        ):
            raise ValueError("invalid provider failure observation")
        if self.retry_after_seconds is not None and (
            type(self.retry_after_seconds) is not int
            or not 0 <= self.retry_after_seconds <= MAX_RETRY_AFTER_SECONDS
        ):
            raise ValueError("invalid provider failure observation")
        if self.diagnostic_category is not None and (
            not isinstance(self.diagnostic_category, str)
            or self.diagnostic_category not in _DIAGNOSTIC_CATEGORIES
        ):
            raise ValueError("invalid provider failure observation")

    def as_dict(self) -> dict[str, Any]:
        """Return the exact versioned JSON shape used by the broker frame."""

        return {
            "schema": PROVIDER_FAILURE_OBSERVATION_SCHEMA,
            "reservation_id": self.reservation_id,
            "attempt_id": self.attempt_id,
            "quote_fingerprint": self.quote_fingerprint,
            "provider": self.provider,
            "model": self.model,
            "operation": self.operation,
            "input_sha256": self.input_sha256,
            "http_status": self.http_status,
            "response_body_complete": self.response_body_complete,
            "response_body_observed_bytes": self.response_body_observed_bytes,
            "response_body_sha256": self.response_body_sha256,
            "provider_request_id_sha256": self.provider_request_id_sha256,
            "retry_after_seconds": self.retry_after_seconds,
            "diagnostic_category": self.diagnostic_category,
        }

    @classmethod
    def from_dict(cls, value: object) -> ProviderFailureObservation:
        """Validate an untrusted broker value without coercing JSON types."""

        expected = {
            "schema",
            "reservation_id",
            "attempt_id",
            "quote_fingerprint",
            "provider",
            "model",
            "operation",
            "input_sha256",
            "http_status",
            "response_body_complete",
            "response_body_observed_bytes",
            "response_body_sha256",
            "provider_request_id_sha256",
            "retry_after_seconds",
            "diagnostic_category",
        }
        if (
            type(value) is not dict
            or set(value) != expected
            or value.get("schema") != PROVIDER_FAILURE_OBSERVATION_SCHEMA
        ):
            raise ValueError("invalid provider failure observation")
        return cls(
            reservation_id=value["reservation_id"],
            attempt_id=value["attempt_id"],
            quote_fingerprint=value["quote_fingerprint"],
            provider=value["provider"],
            model=value["model"],
            operation=value["operation"],
            input_sha256=value["input_sha256"],
            http_status=value["http_status"],
            response_body_complete=value["response_body_complete"],
            response_body_observed_bytes=value["response_body_observed_bytes"],
            response_body_sha256=value["response_body_sha256"],
            provider_request_id_sha256=value["provider_request_id_sha256"],
            retry_after_seconds=value["retry_after_seconds"],
            diagnostic_category=value["diagnostic_category"],
        )
