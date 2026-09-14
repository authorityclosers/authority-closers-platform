"""Telemetry event boundary with audit-channel rejection."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from ac_platform.telemetry.redaction import freeze_attributes, redact_attributes

_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,159}$")
_ATTRIBUTE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_IDENTIFIER_VALUE_PATTERN = re.compile(
    r"(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SAFE_ATTRIBUTE_KEYS = frozenset(
    {
        "activity_kind",
        "attempt",
        "batch_size",
        "communication_class",
        "duration_ms",
        "error_code",
        "event_type",
        "held_jobs",
        "held_outbox",
        "job_kind",
        "outcome",
        "provider",
        "recovery_generation",
        "release_channel",
        "retryable",
        "status",
    }
)

_KNOWN_VALUES: dict[str, frozenset[str]] = {
    "activity_kind": frozenset({"assignment", "lesson", "practice", "quiz", "reading", "video"}),
    "communication_class": frozenset({"enrollment_welcome_next_action"}),
    "error_code": frozenset(
        {
            "ambiguous_provider_receipt_error",
            "duplicate_intent_error",
            "email_message_conflict_error",
            "job_state_error",
            "lease_lost_error",
            "permanent_provider_error",
            "provider_error",
            "reconciliation_required_error",
            "timeout_error",
            "transient_provider_error",
            "unknown_job_kind_error",
            "worker_not_ready_error",
        }
    ),
    "event_type": frozenset(
        {
            "delivery.accepted",
            "delivery.failed",
            "enrollment.welcome.requested.v1",
        }
    ),
    "job_kind": frozenset(
        {
            "email.enrollment_welcome.v1",
            "email.conversation_review_invitation.v1",
            "email.identity_reviewer_auth.v1",
            "email.identity_password_reset.v1",
            "email.identity_verification.v1",
            "internal.test.v1",
        }
    ),
    "outcome": frozenset({"dead_lettered", "failed", "retry_wait", "succeeded"}),
    "provider": frozenset({"fake-email", "resend"}),
    "release_channel": frozenset({"development", "production", "staging", "test"}),
    "status": frozenset(
        {
            "active",
            "degraded",
            "dead_letter",
            "held",
            "pending",
            "processing",
            "queued",
            "ready",
            "retry_wait",
            "succeeded",
        }
    ),
}


def _bounded_int(minimum: int, maximum: int) -> Any:
    return lambda value: (
        isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum
    )


_VALUE_RULES: dict[str, Any] = {
    **{
        key: lambda value, allowed=allowed: isinstance(value, str) and value in allowed
        for key, allowed in _KNOWN_VALUES.items()
    },
    "attempt": _bounded_int(0, 100),
    "batch_size": _bounded_int(0, 10_000),
    "duration_ms": lambda value: (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and 0 <= value <= 86_400_000
    ),
    "held_jobs": _bounded_int(0, 10_000),
    "held_outbox": _bounded_int(0, 10_000),
    "recovery_generation": _bounded_int(0, 1_000_000),
    "retryable": lambda value: isinstance(value, bool),
}


class TelemetryCategory(StrEnum):
    """Categories allowed in downstream product/operations telemetry."""

    PRODUCT = "product"
    ANALYTICS = "analytics"
    OPERATIONAL = "operational"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class TelemetryEvent:
    """A redacted signal that can never masquerade as an audit event."""

    name: str
    attributes: Mapping[str, Any]
    category: TelemetryCategory | str = TelemetryCategory.PRODUCT
    tenant_id: UUID | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        normalized_name = self.name.strip()
        if not normalized_name:
            raise ValueError("telemetry event name must not be blank")
        if not _EVENT_NAME_PATTERN.fullmatch(normalized_name):
            raise ValueError("telemetry event name is not in the bounded schema")
        category_value = (
            self.category.value
            if isinstance(self.category, TelemetryCategory)
            else str(self.category)
        )
        if normalized_name.startswith("audit.") or category_value == "audit":
            raise ValueError("audit evidence is not product or operational telemetry")
        if category_value not in {category.value for category in TelemetryCategory}:
            raise ValueError("telemetry category is not supported")
        safe_attributes = redact_attributes(self.attributes)
        if any(not _ATTRIBUTE_KEY_PATTERN.fullmatch(str(key)) for key in safe_attributes):
            raise ValueError("telemetry attribute key is not in the bounded schema")
        disallowed_keys = sorted(set(safe_attributes) - SAFE_ATTRIBUTE_KEYS)
        if disallowed_keys:
            raise ValueError(
                f"telemetry attribute keys are not allowlisted: {', '.join(disallowed_keys)}"
            )
        if any(not _safe_attribute_value(value) for value in safe_attributes.values()):
            raise ValueError("telemetry attributes must use bounded scalar values")
        invalid_values = [
            str(key) for key, value in safe_attributes.items() if not _VALUE_RULES[str(key)](value)
        ]
        if invalid_values:
            raise ValueError(
                "telemetry attribute values are not in the bounded vocabulary: "
                + ", ".join(sorted(invalid_values))
            )
        if self.tenant_id is not None:
            raise ValueError("high-cardinality tenant identifiers are not telemetry attributes")
        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "category", TelemetryCategory(category_value))
        object.__setattr__(self, "attributes", freeze_attributes(safe_attributes))
        occurred_at = self.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        object.__setattr__(self, "occurred_at", occurred_at.astimezone(UTC))


def _safe_attribute_value(value: Any) -> bool:
    if value is None or isinstance(value, bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, str):
        return _IDENTIFIER_VALUE_PATTERN.fullmatch(value) is None
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return len(value) <= 16 and all(
            item is None
            or isinstance(item, bool | int)
            or (isinstance(item, float) and math.isfinite(item))
            or (isinstance(item, str) and _IDENTIFIER_VALUE_PATTERN.fullmatch(item) is None)
            for item in value
        )
    return False


class TelemetrySink(Protocol):
    """Small port implemented by an OTel exporter or an in-memory test sink."""

    def record(self, event: TelemetryEvent) -> None:
        """Accept one already-redacted event."""


class InMemoryTelemetrySink:
    """Deterministic sink for tests; it performs no network/exporter calls."""

    def __init__(self) -> None:
        self.events: list[TelemetryEvent] = []

    def record(self, event: TelemetryEvent) -> None:
        self.events.append(event)


__all__ = [
    "InMemoryTelemetrySink",
    "SAFE_ATTRIBUTE_KEYS",
    "TelemetryCategory",
    "TelemetryEvent",
    "TelemetrySink",
]
