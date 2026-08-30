"""Conservative, recursive telemetry redaction helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

REDACTED = "[REDACTED]"

MAX_ATTRIBUTE_COUNT = 32
MAX_ATTRIBUTE_DEPTH = 6
MAX_KEY_LENGTH = 64
MAX_STRING_LENGTH = 512
MAX_SEQUENCE_LENGTH = 32
MAX_SERIALIZED_BYTES = 8192

_SENSITIVE_KEY_PARTS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bearer",
        "card_number",
        "cookie",
        "credential",
        "cvv",
        "email",
        "id_token",
        "ip_address",
        "password",
        "phone",
        "private_key",
        "refresh_token",
        "secret",
        "security_code",
        "set_cookie",
        "ssn",
        "token",
    }
)

_SECRET_PATTERN = re.compile(
    r"(?i)(?:bearer\s+|basic\s+)[A-Za-z0-9._~+/=-]+|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password)\s*[:=]\s*[^\s,;]+|"
    r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{8,}\b|"
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_IPV6_PATTERN = re.compile(r"(?i)(?<![0-9a-f:])(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?![0-9a-f:])")
_PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){6,14}\d(?!\w)")
_PAYMENT_CARD_PATTERN = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def is_sensitive_key(key: object) -> bool:
    normalized = _normalized_key(key)
    if normalized in _SENSITIVE_KEY_PARTS:
        return True
    return any(
        part in normalized.split("_") for part in _SENSITIVE_KEY_PARTS if "_" not in part
    ) or any(
        phrase in normalized
        for phrase in ("access_token", "refresh_token", "api_key", "private_key", "card_number")
    )


def redact_string(value: str) -> str:
    """Remove common token-shaped material from otherwise useful messages."""

    redacted = _SECRET_PATTERN.sub(REDACTED, value)
    redacted = _EMAIL_PATTERN.sub(REDACTED, redacted)
    redacted = _IPV4_PATTERN.sub(REDACTED, redacted)
    redacted = _IPV6_PATTERN.sub(REDACTED, redacted)
    redacted = _PAYMENT_CARD_PATTERN.sub(REDACTED, redacted)
    return _PHONE_PATTERN.sub(REDACTED, redacted)


def sanitize_error(error: str | BaseException, *, max_length: int = 2000) -> str:
    """Return a bounded error safe for durable operational storage."""

    if max_length < 1:
        raise ValueError("max_length must be positive")
    try:
        value = str(error).strip()
    except Exception:  # pragma: no cover - defensive against hostile exceptions
        value = "operation failed"
    sanitized = redact_string(value)
    return sanitized[:max_length] or "operation failed"


def redact(value: Any, *, max_depth: int = 8) -> Any:
    """Return a redacted copy without mutating the caller's attributes."""

    if max_depth < 0:
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return REDACTED
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if is_sensitive_key(key) else redact(item, max_depth=max_depth - 1)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact(item, max_depth=max_depth - 1) for item in value]
    return redact_string(str(value))


def redact_attributes(attributes: Mapping[str, Any], *, max_depth: int = 8) -> dict[str, Any]:
    """Redact and validate a telemetry attribute mapping.

    Telemetry is intentionally a bounded signal channel. Oversized or
    structurally unbounded values are rejected before they reach an exporter;
    this keeps a caller from turning metrics/traces into an accidental data
    dump.
    """

    if not isinstance(attributes, Mapping):
        raise TypeError("telemetry attributes must be a mapping")
    if len(attributes) > MAX_ATTRIBUTE_COUNT:
        raise ValueError("telemetry attributes exceed the bounded attribute count")
    max_depth = min(max_depth, MAX_ATTRIBUTE_DEPTH)
    redacted = redact(attributes, max_depth=max_depth)
    if not isinstance(redacted, dict):
        raise TypeError("telemetry attributes must be a mapping")
    _validate_bounded(redacted, depth=0)
    import json

    serialized_size = len(json.dumps(redacted, sort_keys=True, default=str).encode("utf-8"))
    if serialized_size > MAX_SERIALIZED_BYTES:
        raise ValueError("telemetry attributes exceed the bounded serialized size")
    return redacted


def freeze_attributes(value: Any, *, depth: int = 0) -> Any:
    """Recursively freeze already-redacted telemetry values."""

    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): freeze_attributes(item, depth=depth + 1) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(freeze_attributes(item, depth=depth + 1) for item in value)
    return value


def _validate_bounded(value: Any, *, depth: int) -> None:
    if depth > MAX_ATTRIBUTE_DEPTH:
        raise ValueError("telemetry attributes exceed the bounded depth")
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ValueError("telemetry string attribute exceeds the bounded length")
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_ATTRIBUTE_COUNT:
            raise ValueError("telemetry nested attributes exceed the bounded count")
        for key, item in value.items():
            if len(str(key)) > MAX_KEY_LENGTH:
                raise ValueError("telemetry attribute key exceeds the bounded length")
            _validate_bounded(item, depth=depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if len(value) > MAX_SEQUENCE_LENGTH:
            raise ValueError("telemetry sequence attribute exceeds the bounded length")
        for item in value:
            _validate_bounded(item, depth=depth + 1)


__all__ = [
    "MAX_ATTRIBUTE_COUNT",
    "MAX_ATTRIBUTE_DEPTH",
    "MAX_KEY_LENGTH",
    "MAX_SERIALIZED_BYTES",
    "MAX_SEQUENCE_LENGTH",
    "MAX_STRING_LENGTH",
    "REDACTED",
    "freeze_attributes",
    "is_sensitive_key",
    "redact",
    "redact_attributes",
    "redact_string",
    "sanitize_error",
]
