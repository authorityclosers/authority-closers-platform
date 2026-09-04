"""Server-owned contracts for the bounded learner product-analytics intake.

This module is deliberately narrower than the canonical learning-event
envelope.  It accepts only the bounded proposal analytics names currently
defined for the learner planning surface and stores observations in the
disposable ``analytics_events`` table.  The intake cannot create progress, completion,
entitlement, payment, access, audit, or scoring facts.

The HTTP adapter supplies the authenticated actor and a server-owned consent
resolver.  A missing resolver or retention policy is a configuration error,
so the default application composition remains fail-closed.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.planning import PROPOSED_ANALYTICS_EVENTS

# These limits are contract limits, not a claim about product metric
# semantics.  They keep retries and browser/offline batches bounded while a
# later volume-specific edge can be introduced behind the admission seam.
MAX_BATCH_EVENTS = 50
MAX_EVENT_PAYLOAD_BYTES = 4 * 1024
MAX_BATCH_BYTES = 64 * 1024
MAX_PAYLOAD_FIELDS = 20
MAX_EVENT_AGE = timedelta(days=7)
MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_RETENTION_DAYS = 3650

TELEMETRY_PURPOSE = "product_analytics"
TELEMETRY_PROVENANCE_SOURCE = "authenticated_learner_api"
TELEMETRY_PROVENANCE_VERSION = "learner-product-telemetry-v1"

# These are route templates owned by the learner application.  Intake stores
# only one of these exact values; it never stores an arbitrary path, query
# string, route parameter, or client-provided URL.
LEARNER_ROUTE_TEMPLATES: tuple[str, ...] = (
    "/home",
    "/progress",
    "/calendar",
    "/learning/plans",
    "/learning/up-next",
    "/learning/insights",
)
_ALLOWED_ROUTE_TEMPLATES = frozenset(LEARNER_ROUTE_TEMPLATES)


@dataclass(frozen=True, slots=True)
class LearnerAnalyticsEventDefinition:
    """Immutable server-owned schema entry for one analytics event."""

    event_version: str
    allowed_payload_keys: tuple[str, ...]
    requires_period: bool


# Copy the controlled planning proposal into frozen values so callers cannot
# mutate the registry through this intake module.  New event names require a
# controlled taxonomy change; arbitrary client event names are never accepted.
LEARNER_PRODUCT_ANALYTICS_EVENTS: Mapping[str, LearnerAnalyticsEventDefinition] = MappingProxyType(
    {
        name: LearnerAnalyticsEventDefinition(
            event_version=str(definition["event_version"]),
            allowed_payload_keys=tuple(definition["allowed_payload_keys"]),
            requires_period=bool(definition["requires_period"]),
        )
        for name, definition in PROPOSED_ANALYTICS_EVENTS.items()
    }
)

_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SESSION_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_PAYLOAD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,48}$")
_PII_KEY_PATTERN = re.compile(
    r"(?:email|e[-_ ]?mail|phone|mobile|address|name|transcript|audio|recording|"
    r"token|secret|password|ip|device.?id|cookie|prompt|answer|message|url)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?:\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+|"
    r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9_-]+|"
    r"\b(?:eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b|"
    r"\b(?:\d[ -]?){13,19}\b|"
    r"\b(?:\+?\d[\d ()-]{7,}\d)\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"(?:\b(?:password|secret|access[_ -]?token|api[_ -]?key)\s*[:=]))",
    re.IGNORECASE,
)


class TelemetryConsentStatus(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"


class TelemetryConsent(BaseModel):
    """Authoritative consent supplied by server composition, never the client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TelemetryConsentStatus
    purpose: str = Field(default=TELEMETRY_PURPOSE, min_length=1, max_length=64)
    policy_version: str = Field(min_length=1, max_length=64)
    captured_at: datetime
    tenant_id: UUID
    person_id: UUID
    session_id: UUID

    @field_validator("purpose", "policy_version")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("consent values must not be blank")
        return normalized

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("captured_at must include a timezone")
        return value.astimezone(UTC)


class LearnerTelemetryEvent(BaseModel):
    """One client observation with no client-owned tenant or person fields."""

    model_config = ConfigDict(extra="forbid")

    # UUIDs are controlled replay keys.  Opaque client strings are not
    # accepted because they can become an unbounded secret/PII sink.
    event_id: UUID
    event_name: str = Field(min_length=1, max_length=96)
    event_version: str = Field(default="1.0", min_length=1, max_length=16)
    occurred_at: datetime
    session_id: UUID
    route: str | None = Field(default=None, max_length=180)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: UUID) -> UUID:
        if value.int == 0:
            raise ValueError("event_id must not be the nil UUID")
        return value

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, value: str) -> str:
        normalized = value.strip()
        if not _EVENT_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("event_name must use the bounded taxonomy schema")
        return normalized

    @field_validator("event_version")
    @classmethod
    def validate_event_version(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event_version must not be blank")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: UUID) -> UUID:
        if not _SESSION_ID_PATTERN.fullmatch(str(value)):
            raise ValueError("session_id must be a UUID session identifier")
        return value

    @field_validator("route")
    @classmethod
    def validate_route(cls, value: str | None) -> str | None:
        if value is not None and value not in _ALLOWED_ROUTE_TEMPLATES:
            raise ValueError("route must be a server-owned learner route template")
        return value

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > MAX_PAYLOAD_FIELDS:
            raise ValueError(f"payload may contain at most {MAX_PAYLOAD_FIELDS} fields")
        for key, item in value.items():
            if not _PAYLOAD_KEY_PATTERN.fullmatch(key) or _PII_KEY_PATTERN.search(key):
                raise ValueError("payload keys must be bounded, allowlisted, and non-PII")
            if not _safe_scalar(item):
                raise ValueError("payload values must be finite bounded scalar values")
            if isinstance(item, str) and (len(item) > 256 or _SENSITIVE_VALUE_PATTERN.search(item)):
                raise ValueError("payload values must not contain secrets or personal data")
        serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        if len(serialized.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError("payload exceeds the bounded serialized size")
        return value


class LearnerTelemetryBatch(BaseModel):
    """A bounded batch; the event IDs are the replay/idempotency keys."""

    model_config = ConfigDict(extra="forbid")

    events: list[LearnerTelemetryEvent] = Field(
        min_length=1,
        max_length=MAX_BATCH_EVENTS,
        description="At most 50 observations per authenticated request.",
    )

    @field_validator("events")
    @classmethod
    def validate_unique_event_ids(
        cls, value: list[LearnerTelemetryEvent]
    ) -> list[LearnerTelemetryEvent]:
        event_ids = [event.event_id for event in value]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id must be unique within a batch")
        return value

    def serialized_size(self) -> int:
        return len(self.model_dump_json().encode("utf-8"))


# Descriptive aliases for adapters that refer to transport contracts rather
# than the learner surface name.  Both names point to the same schema class.
TelemetryEventRequest = LearnerTelemetryEvent
TelemetryBatchRequest = LearnerTelemetryBatch


class TelemetryAdmission(Protocol):
    """Required tenant-aware admission seam for telemetry writes.

    A deployment must compose this with a durable/distributed quota at the
    API edge or queue boundary before enabling writes.  The in-process HTTP
    rate limit is only a coarse abuse shield and is not an admission
    authority.
    """

    def admit(
        self, *, tenant_id: UUID, event_count: int, payload_bytes: int
    ) -> bool | Awaitable[bool]:
        """Return false when the intake should fail before touching storage."""


# The resolver receives the active caller-owned transaction/session.  A
# production implementation must use it to read the authoritative grant and
# lock/re-check it immediately before the event insert; client consent is
# never an authority and a request-scoped cached value is insufficient.
TelemetryConsentResolver = Callable[
    [object, ActorContext], TelemetryConsent | None | Awaitable[TelemetryConsent | None]
]


def _safe_scalar(value: Any) -> bool:
    if value is None or isinstance(value, bool | int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("telemetry timestamps must include a timezone")
    return value.astimezone(UTC)


def validate_batch_size(batch: LearnerTelemetryBatch) -> int:
    """Return canonical JSON bytes and reject oversized batches."""

    size = batch.serialized_size()
    if size > MAX_BATCH_BYTES:
        raise ValueError("telemetry batch exceeds the bounded serialized size")
    return size


def validate_event_timestamp(*, occurred_at: datetime, now: datetime) -> datetime:
    occurred = ensure_utc(occurred_at)
    current = ensure_utc(now)
    if occurred > current + MAX_FUTURE_SKEW:
        raise ValueError("telemetry timestamp is outside the permitted future skew")
    if occurred < current - MAX_EVENT_AGE:
        raise ValueError("telemetry timestamp is outside the permitted retention intake window")
    return occurred


__all__ = [
    "LEARNER_PRODUCT_ANALYTICS_EVENTS",
    "LEARNER_ROUTE_TEMPLATES",
    "MAX_BATCH_BYTES",
    "MAX_BATCH_EVENTS",
    "MAX_EVENT_AGE",
    "MAX_EVENT_PAYLOAD_BYTES",
    "MAX_FUTURE_SKEW",
    "MAX_PAYLOAD_FIELDS",
    "MAX_RETENTION_DAYS",
    "LearnerTelemetryBatch",
    "LearnerAnalyticsEventDefinition",
    "LearnerTelemetryEvent",
    "TELEMETRY_PROVENANCE_SOURCE",
    "TELEMETRY_PROVENANCE_VERSION",
    "TELEMETRY_PURPOSE",
    "TelemetryAdmission",
    "TelemetryBatchRequest",
    "TelemetryConsent",
    "TelemetryConsentResolver",
    "TelemetryConsentStatus",
    "TelemetryEventRequest",
    "ensure_utc",
    "validate_batch_size",
    "validate_event_timestamp",
]
