"""Shared wire helpers for payment adapters: HTTP calls, parsing and checks.

Error messages carry a provider name and a status code only. Response bodies,
signatures and credentials never reach an exception, a log line or a repr.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from ac_platform.payments.ports import (
    MAX_WEBHOOK_BODY_BYTES,
    AmbiguousPaymentOutcomeError,
    Money,
    PaymentEventRejected,
    PaymentMode,
)
from ac_platform.providers.ports import PermanentProviderError, TransientProviderError


def require_secret(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is not configured")
    normalized = value.strip()
    if len(normalized) < 8 or any(mark.isspace() for mark in normalized):
        raise ValueError(f"{name} is not configured")
    return normalized


def require_mode(value: object) -> PaymentMode:
    if not isinstance(value, PaymentMode):
        raise ValueError("mode must be a PaymentMode")
    return value


def require_timeout(seconds: float) -> httpx.Timeout:
    if not 1 <= seconds <= 60:
        raise ValueError("timeout must be between one and sixty seconds")
    return httpx.Timeout(seconds)


async def send(
    client: httpx.AsyncClient | None,
    method: str,
    url: str,
    *,
    provider: str,
    request_timeout: httpx.Timeout,
    money_moving: bool = False,
    **request: Any,
) -> httpx.Response:
    """Send one request and classify transport and server failures.

    A money-moving call (a refund) that times out or fails on the server side
    has an unknown outcome and must be reconciled, never retried blindly.
    """

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=request_timeout, follow_redirects=False) as owned:
                response = await owned.request(method, url, **request)
        else:
            response = await client.request(method, url, **request)
    except (httpx.TimeoutException, httpx.NetworkError):
        if money_moving:
            raise AmbiguousPaymentOutcomeError(
                f"{provider} outcome is unknown because no response was received"
            ) from None
        raise TransientProviderError(f"{provider} could not be reached") from None
    status = response.status_code
    if status in {425, 429}:
        raise TransientProviderError(f"{provider} returned retryable status {status}")
    if status == 408 or status >= 500:
        if money_moving:
            raise AmbiguousPaymentOutcomeError(
                f"{provider} returned status {status} with an unknown outcome"
            )
        raise TransientProviderError(f"{provider} returned retryable status {status}")
    return response


def require_success(response: httpx.Response, provider: str) -> None:
    if not 200 <= response.status_code < 300:
        raise PermanentProviderError(
            f"{provider} rejected the request with status {response.status_code}"
        )


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _loads(text: str) -> Any:
    return json.loads(
        text,
        parse_float=Decimal,
        parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )


def response_json(response: httpx.Response, provider: str, *, money_moving: bool = False) -> Any:
    """Parse a provider response, keeping decimals exact."""

    try:
        return _loads(response.text)
    except ValueError:
        if money_moving:
            raise AmbiguousPaymentOutcomeError(
                f"{provider} accepted the request but returned an unusable receipt"
            ) from None
        raise PermanentProviderError(f"{provider} returned an unusable response") from None


def event_json(raw_body: bytes, provider: str) -> dict[str, Any]:
    """Parse a verified webhook body as one JSON object."""

    try:
        parsed = _loads(raw_body.decode("utf-8"))
    except ValueError:
        raise PaymentEventRejected(f"{provider} webhook body is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise PaymentEventRejected(f"{provider} webhook body is not a JSON object")
    return parsed


def require_body(raw_body: object, provider: str) -> bytes:
    if not isinstance(raw_body, bytes) or not raw_body:
        raise PaymentEventRejected(f"{provider} webhook body is missing")
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise PaymentEventRejected(f"{provider} webhook body is too large")
    return raw_body


def body_digest(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def header(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup; blank values count as missing."""

    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value.strip() or None
    return None


def child(parent: object, key: str, provider: str) -> Mapping[str, Any]:
    """Return a nested JSON object or refuse the event."""

    value = parent.get(key) if isinstance(parent, Mapping) else None
    if not isinstance(value, Mapping):
        raise PaymentEventRejected(f"{provider} webhook payload is missing {key}")
    return value


def text(parent: Mapping[str, Any], key: str, provider: str, *, maximum: int = 255) -> str:
    """Return a bounded identifier; providers send some ids as integers."""

    value = parent.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise PaymentEventRejected(f"{provider} webhook payload has an unusable {key}")
    return value.strip()


def optional_text(parent: Mapping[str, Any], key: str, *, maximum: int = 255) -> str | None:
    value = parent.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        return None
    return value.strip()


def parse_minor(amount: object, currency: object) -> Money | None:
    """Money from an integer minor-unit amount, or None when it is unusable."""

    if type(amount) is not int or not isinstance(currency, str):
        return None
    try:
        return Money(amount, currency.upper())
    except ValueError:
        return None


def parse_decimal(amount: object, currency: object) -> Money | None:
    """Money from a major-unit decimal amount, or None when it is unusable."""

    if not isinstance(amount, Decimal | int | str) or not isinstance(currency, str):
        return None
    try:
        return Money.from_decimal(amount, currency)
    except ValueError:
        return None


def minor_money(amount: object, currency: object, provider: str) -> Money:
    """Money from a webhook's minor-unit amount; an unusable one refuses the event."""

    money = parse_minor(amount, currency)
    if money is None:
        raise PaymentEventRejected(f"{provider} payload has an unusable amount")
    return money


def decimal_money(amount: object, currency: object, provider: str) -> Money:
    """Money from a webhook's decimal amount; an unusable one refuses the event."""

    money = parse_decimal(amount, currency)
    if money is None:
        raise PaymentEventRejected(f"{provider} payload has an unusable amount")
    return money


def epoch_time(value: object) -> datetime | None:
    if type(value) is not int or not 0 < value < 4_102_444_800:
        return None
    return datetime.fromtimestamp(value, UTC)


def iso_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def current_time(now: datetime | None) -> datetime:
    current = now or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)
