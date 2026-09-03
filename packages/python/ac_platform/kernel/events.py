from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast
from uuid import UUID, uuid4

from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import AuthorizationDenied

_EVENT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,159}$")
_CONTEXT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_RELEASE_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_SUPPORTED_ENVIRONMENTS = frozenset({"local", "test", "development", "staging", "production"})
_PAYLOAD_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SENSITIVE_PAYLOAD_KEY_PATTERN = re.compile(
    r"(?:email|e[-_ ]?mail|phone|mobile|address|transcript|recording|audio|"
    r"token|secret|password|ip|device.?id|cookie|prompt|answer|message)",
    re.IGNORECASE,
)
_SENSITIVE_PAYLOAD_VALUE_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[A-Za-z0-9._~+/=-]+|basic\s+[A-Za-z0-9._~+/=-]+|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)\s*[:=]\s*[^\s,;]+|"
    r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{8,}\b|"
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"(?<!\w)(?:\+?\d[\s().-]*){6,14}\d(?!\w)|"
    r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d))"
)
_MAX_PAYLOAD_DEPTH = 6
_MAX_PAYLOAD_KEYS = 32
_MAX_PAYLOAD_SEQUENCE = 32
_MAX_PAYLOAD_STRING_LENGTH = 512
_MAX_PAYLOAD_BYTES = 8192
_MAX_PAYLOAD_INTEGER = 2**63 - 1
LEARNING_EVENT_VERSION = "1.0"

# This is the controlled API/data event catalogue, not a product taxonomy.
# Payload schemas intentionally remain empty until each event's domain fields
# are promoted by the controlled sources.
LEARNING_EVENT_VERSIONS: Mapping[str, str] = MappingProxyType(
    {
        "enrollment.created": "1.0",
        "learning.started": "1.0",
        "module.started": "1.0",
        "activity.opened": "1.0",
        "activity.progressed": "1.0",
        "activity.completed": "1.0",
        "activity.reopened": "1.0",
        "module.completed": "1.0",
        "program.completed": "1.0",
        "next_action.generated": "1.0",
        "streak.changed": "1.0",
    }
)
LEARNING_EVENT_PAYLOAD_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {name: frozenset() for name in LEARNING_EVENT_VERSIONS}
)


class _FrozenJsonObject(dict[str, Any]):
    """A JSON mapping that cannot be changed through ordinary dict methods."""

    def __setitem__(self, _key: str, _value: Any) -> None:
        raise TypeError("validated learning payloads are immutable")

    def __delitem__(self, _key: str) -> None:
        raise TypeError("validated learning payloads are immutable")

    def clear(self) -> None:
        raise TypeError("validated learning payloads are immutable")

    def pop(self, _key: str, _default: Any = None) -> Any:
        raise TypeError("validated learning payloads are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("validated learning payloads are immutable")

    def setdefault(self, _key: str, _default: Any = None) -> Any:
        raise TypeError("validated learning payloads are immutable")

    def update(self, *_args: object, **_kwargs: Any) -> None:
        raise TypeError("validated learning payloads are immutable")

    # Mypy compares dict.__ior__ to dict.__or__ for this subclass; the
    # runtime method deliberately raises for every supported dict operand.
    def __ior__(self, _value: object, /) -> _FrozenJsonObject:  # type: ignore[override,misc]
        raise TypeError("validated learning payloads are immutable")

    def __deepcopy__(self, memo: dict[int, object]) -> _FrozenJsonObject:
        existing = memo.get(id(self))
        if isinstance(existing, _FrozenJsonObject):
            return existing
        copied = _FrozenJsonObject()
        memo[id(self)] = copied
        dict.update(
            copied,
            {key: copy.deepcopy(value, memo) for key, value in self.items()},
        )
        return copied

    def copy(self) -> dict[str, Any]:
        return {key: _materialize_learning_payload(value) for key, value in self.items()}


class EventCategory(StrEnum):
    DOMAIN_FACT = "domain_fact"
    AUDIT = "audit"
    ANALYTICS = "analytics"
    OPERATIONAL = "operational"
    COST = "cost"


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    name: str
    category: EventCategory
    aggregate_type: str
    aggregate_id: UUID
    tenant_id: UUID | None
    payload: dict[str, Any]
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_id: UUID = field(default_factory=uuid4)

    def __post_init__(self) -> None:
        if not self.name or not self.aggregate_type:
            raise ValueError("Event name and aggregate type are required.")
        if self.category is EventCategory.AUDIT and self.tenant_id is None:
            raise ValueError("Audit events require an explicit tenant boundary.")


@dataclass(frozen=True, slots=True, init=False)
class _ValidatedTrace:
    value: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("trace values are issued by the projection factory")


@dataclass(frozen=True, slots=True, init=False)
class _ValidatedReleaseIdentity:
    value: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("release identities are issued by the projection factory")


@dataclass(frozen=True, slots=True, init=False)
class _ValidatedClock:
    _clock: Callable[[], datetime]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("clock values are issued by the projection factory")

    def now(self) -> datetime:
        return self._clock()


@dataclass(frozen=True, slots=True, init=False)
class _ValidatedMembership:
    tenant_id: UUID
    person_id: UUID
    role: str
    person_revision: int
    session_revision: int
    tenant_revision: int
    membership_revision: int

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("membership values are issued by the projection factory")


@dataclass(frozen=True, slots=True, init=False)
class _ValidatedLearningEventContext:
    """Private shape context; it does not confer authorization in-process."""

    actor: ActorContext
    membership: _ValidatedMembership
    subject_id: UUID
    trace: _ValidatedTrace
    release: _ValidatedReleaseIdentity
    clock: _ValidatedClock

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("projection contexts are issued by the projection factory")


@dataclass(frozen=True, slots=True, init=False)
class ValidatedLearningEventProjection:
    """Immutable contract projection; in-process construction is not authorization."""

    event_name: str
    event_version: str
    occurred_at: datetime
    event_id: UUID
    tenant_id: UUID
    actor_id: UUID
    subject_id: UUID
    trace_id: str
    release_sha: str
    payload: Mapping[str, Any]

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError(
            "ValidatedLearningEventProjection is created by the projection factory; "
            "in-process construction does not authorize anything"
        )

    def to_contract(self) -> dict[str, Any]:
        """Return a detached JSON-safe representation of the validated projection."""

        return {
            "event_id": str(self.event_id),
            "event_name": self.event_name,
            "event_version": self.event_version,
            "occurred_at": self.occurred_at.isoformat().replace("+00:00", "Z"),
            "tenant_id": str(self.tenant_id),
            "actor_id": str(self.actor_id),
            "subject_id": str(self.subject_id),
            "trace_id": self.trace_id,
            "release_sha": self.release_sha,
            "payload": _materialize_learning_payload(self.payload),
        }


def _build_validated_learning_event_projection(
    event: EventEnvelope,
    *,
    context: _ValidatedLearningEventContext,
) -> ValidatedLearningEventProjection:
    """Build a bounded projection after integration validation checks."""

    if not isinstance(event, EventEnvelope):
        raise TypeError("learning projection source must be an EventEnvelope")
    if not isinstance(context, _ValidatedLearningEventContext):
        raise TypeError("learning projection context must come from the projection factory")
    if event.category is not EventCategory.DOMAIN_FACT:
        raise ValueError("learning projections accept approved domain facts, not audit events")
    if type(event.name) is not str or _EVENT_NAME_PATTERN.fullmatch(event.name) is None:
        raise ValueError("learning event name is not in the bounded schema")
    if event.name.startswith("audit."):
        raise ValueError("learning projections accept approved domain facts, not audit events")
    if not isinstance(event.event_id, UUID):
        raise TypeError("learning event event_id must be a UUID")
    if event.tenant_id is None or event.tenant_id != context.membership.tenant_id:
        raise AuthorizationDenied("learning event tenant does not match the supplied membership")
    expected_version = LEARNING_EVENT_VERSIONS.get(event.name)
    if expected_version is None:
        raise ValueError("event is not an approved learning event")
    normalized_payload = _validate_learning_payload(event.name, event.payload)
    occurred_at = _require_aware_utc(event.occurred_at, "learning event occurred_at")
    now = _require_aware_utc(context.clock.now(), "projection clock")
    if occurred_at > now:
        raise ValueError("learning event occurred_at cannot be in the future")
    projection = object.__new__(ValidatedLearningEventProjection)
    values = {
        "event_name": event.name,
        "event_version": expected_version,
        "occurred_at": occurred_at,
        "event_id": event.event_id,
        "tenant_id": context.membership.tenant_id,
        "actor_id": context.actor.person_id,
        "subject_id": context.subject_id,
        "trace_id": context.trace.value,
        "release_sha": context.release.value,
        "payload": _freeze_learning_payload(normalized_payload),
    }
    for field_name, value in values.items():
        object.__setattr__(projection, field_name, value)
    return projection


def _build_validated_learning_event_context(
    *,
    actor_context: object,
    trace: _ValidatedTrace,
    release: _ValidatedReleaseIdentity,
    clock: _ValidatedClock,
    subject_id: UUID | None = None,
) -> _ValidatedLearningEventContext:
    """Create private shape context; it does not establish authorization."""

    actor, membership = _validate_actor_membership(actor_context)
    resolved_subject = actor.person_id if subject_id is None else subject_id
    if not isinstance(resolved_subject, UUID):
        raise TypeError("learning event subject_id must be a UUID")
    try:
        actor.require_self(resolved_subject)
    except AuthorizationDenied as error:
        raise AuthorizationDenied(
            "cross-subject learning projection requires an external authorization boundary"
        ) from error
    if not isinstance(trace, _ValidatedTrace):
        raise TypeError("learning event trace must come from the projection factory")
    if not isinstance(release, _ValidatedReleaseIdentity):
        raise TypeError("learning event release must come from the projection factory")
    if not isinstance(clock, _ValidatedClock):
        raise TypeError("learning event clock must come from the projection factory")
    context = object.__new__(_ValidatedLearningEventContext)
    for field_name, value in {
        "actor": actor,
        "membership": membership,
        "subject_id": resolved_subject,
        "trace": trace,
        "release": release,
        "clock": clock,
    }.items():
        object.__setattr__(context, field_name, value)
    return context


def _validate_actor_membership(
    actor_context: object,
) -> tuple[ActorContext, _ValidatedMembership]:
    """Validate the shape of an integration-supplied actor/membership context."""

    actor = getattr(actor_context, "actor", None)
    if (
        not isinstance(actor, ActorContext)
        or not isinstance(actor.person_id, UUID)
        or not isinstance(actor.tenant_id, UUID)
    ):
        raise AuthorizationDenied("an integration-supplied tenant-scoped actor is required")
    membership_role = getattr(actor_context, "membership_role", None)
    person_revision = getattr(actor_context, "person_revision", None)
    session_revision = getattr(actor_context, "session_revision", None)
    tenant_revision = getattr(actor_context, "tenant_revision", None)
    membership_revision = getattr(actor_context, "membership_revision", None)
    if (
        not isinstance(membership_role, str)
        or not membership_role.strip()
        or not _nonnegative_int(person_revision)
        or not _nonnegative_int(session_revision)
        or not _nonnegative_int(tenant_revision)
        or not _nonnegative_int(membership_revision)
    ):
        raise AuthorizationDenied("an integration-supplied membership context is required")
    membership = object.__new__(_ValidatedMembership)
    for field_name, value in {
        "tenant_id": actor.tenant_id,
        "person_id": actor.person_id,
        "role": membership_role,
        "person_revision": person_revision,
        "session_revision": session_revision,
        "tenant_revision": tenant_revision,
        "membership_revision": membership_revision,
    }.items():
        object.__setattr__(membership, field_name, value)
    return actor, membership


def _validated_trace_from_request_id(request_id: str) -> _ValidatedTrace:
    """Validate the bounded request/correlation ID supplied by integration code."""

    if not isinstance(request_id, str) or _CONTEXT_ID_PATTERN.fullmatch(request_id) is None:
        raise ValueError("request trace is not in the bounded schema")
    trace = object.__new__(_ValidatedTrace)
    object.__setattr__(trace, "value", request_id)
    return trace


def _validated_release_identity_from_settings(settings: object) -> _ValidatedReleaseIdentity:
    """Validate configured/baked release identity supplied by integration code."""

    environment = getattr(settings, "environment", None)
    release_id = getattr(settings, "release_id", None)
    if (
        type(environment) is not str
        or environment not in _SUPPORTED_ENVIRONMENTS
        or type(release_id) is not str
    ):
        raise TypeError("validated application settings are required for release identity")
    if _RELEASE_SHA_PATTERN.fullmatch(release_id) is None:
        raise ValueError("configured release identity must be a full lowercase Git SHA")
    if environment in {"staging", "production"}:
        from ac_platform.application.release_identity import require_baked_release_id

        release_id = require_baked_release_id(release_id)
    release = object.__new__(_ValidatedReleaseIdentity)
    object.__setattr__(release, "value", release_id)
    return release


def _validated_clock(clock: Callable[[], datetime]) -> _ValidatedClock:
    """Wrap a clock supplied by integration code for bounded timestamp validation."""

    if not callable(clock):
        raise TypeError("projection clock must be callable")

    validated_clock = object.__new__(_ValidatedClock)
    object.__setattr__(validated_clock, "_clock", clock)
    return validated_clock


def _validate_learning_payload(event_name: str, payload: object) -> Any:
    if type(payload) is not dict:
        raise TypeError("learning event payload must be a plain JSON object")
    allowed_keys = LEARNING_EVENT_PAYLOAD_KEYS[event_name]
    keys = set(payload)
    for key in keys:
        if type(key) is not str or _PAYLOAD_KEY_PATTERN.fullmatch(key) is None:
            raise ValueError("learning event payload keys must be bounded strings")
        if _SENSITIVE_PAYLOAD_KEY_PATTERN.search(key):
            raise ValueError("learning event payload contains a prohibited sensitive field")
    unexpected = sorted(keys - allowed_keys)
    if unexpected:
        raise ValueError(
            f"learning event payload keys are not allowlisted for {event_name}: "
            + ", ".join(unexpected)
        )
    normalized = _copy_json_value(payload, depth=0, active_ids=set(), path="payload")
    try:
        serialized = json.dumps(
            normalized,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("learning event payload must be JSON serializable") from error
    if len(serialized.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("learning event payload exceeds the bounded serialized size")
    return normalized


def _copy_json_value(value: object, *, depth: int, active_ids: set[int], path: str) -> Any:
    if depth > _MAX_PAYLOAD_DEPTH:
        raise ValueError("learning event payload exceeds the bounded depth")
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        if abs(value) > _MAX_PAYLOAD_INTEGER:
            raise ValueError(f"{path} integer exceeds the bounded range")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} float must be finite")
        return value
    if type(value) is str:
        if len(value) > _MAX_PAYLOAD_STRING_LENGTH:
            raise ValueError(f"{path} string exceeds the bounded length")
        if _SENSITIVE_PAYLOAD_VALUE_PATTERN.search(value):
            raise ValueError(f"{path} contains prohibited sensitive data")
        return value
    if type(value) not in {dict, list}:
        raise TypeError(f"{path} contains a non-JSON-safe value")
    value_id = id(value)
    if value_id in active_ids:
        raise ValueError("learning event payload contains a cycle")
    active_ids.add(value_id)
    try:
        if type(value) is dict:
            mapping = cast(dict[object, object], value)
            if len(mapping) > _MAX_PAYLOAD_KEYS:
                raise ValueError(f"{path} exceeds the bounded object size")
            normalized: dict[str, Any] = {}
            for key, item in mapping.items():
                if type(key) is not str or _PAYLOAD_KEY_PATTERN.fullmatch(key) is None:
                    raise ValueError(f"{path} contains an invalid object key")
                if _SENSITIVE_PAYLOAD_KEY_PATTERN.search(key):
                    raise ValueError(f"{path} contains a prohibited sensitive field")
                normalized[key] = _copy_json_value(
                    item,
                    depth=depth + 1,
                    active_ids=active_ids,
                    path=f"{path}.{key}",
                )
            return normalized
        sequence = cast(list[object], value)
        if len(sequence) > _MAX_PAYLOAD_SEQUENCE:
            raise ValueError(f"{path} exceeds the bounded sequence size")
        return [
            _copy_json_value(
                item,
                depth=depth + 1,
                active_ids=active_ids,
                path=f"{path}[{index}]",
            )
            for index, item in enumerate(sequence)
        ]
    finally:
        active_ids.remove(value_id)


def _freeze_learning_payload(value: object) -> Any:
    if type(value) is dict:
        return _FrozenJsonObject(
            {key: _freeze_learning_payload(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze_learning_payload(item) for item in value)
    return value


def _materialize_learning_payload(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _materialize_learning_payload(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_materialize_learning_payload(item) for item in value]
    return value


def _require_aware_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


__all__ = [
    "EventCategory",
    "EventEnvelope",
    "LEARNING_EVENT_PAYLOAD_KEYS",
    "LEARNING_EVENT_VERSION",
    "LEARNING_EVENT_VERSIONS",
    "ValidatedLearningEventProjection",
]
