from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
from asyncio import Lock
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from starlette.types import Receive, Scope, Send

from ac_platform.http.request_context import REQUEST_ID_PATTERN


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    name: str
    method: str
    path: re.Pattern[str]
    capacity: int
    refill_seconds: float

    def __post_init__(self) -> None:
        if self.capacity < 1 or self.refill_seconds <= 0:
            raise ValueError("rate-limit capacity and refill window must be positive")


DEFAULT_RATE_LIMIT_RULES = (
    RateLimitRule(
        name="oauth-start",
        method="GET",
        path=re.compile(r"^/v1/auth/google/start$"),
        capacity=20,
        refill_seconds=600,
    ),
    RateLimitRule(
        name="oauth-callback",
        method="GET",
        path=re.compile(r"^/v1/auth/google/callback$"),
        capacity=60,
        refill_seconds=600,
    ),
    RateLimitRule(
        name="public-program-catalog",
        method="GET",
        path=re.compile(r"^/v1/programs(?:/[^/]+)?$"),
        capacity=300,
        refill_seconds=60,
    ),
)


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class InMemoryTokenBucketLimiter:
    """Bounded single-process fallback limiter for the current one-worker API."""

    def __init__(
        self,
        *,
        maximum_buckets: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if maximum_buckets < 1:
            raise ValueError("maximum_buckets must be positive")
        self._maximum_buckets = maximum_buckets
        self._clock = clock
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._lock = Lock()

    async def consume(self, key: str, rule: RateLimitRule) -> tuple[bool, int, int]:
        now = self._clock()
        refill_rate = rule.capacity / rule.refill_seconds
        async with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(rule.capacity), updated_at=now)
                self._buckets[key] = bucket
            else:
                elapsed = max(0.0, now - bucket.updated_at)
                bucket.tokens = min(float(rule.capacity), bucket.tokens + elapsed * refill_rate)
                bucket.updated_at = now
                self._buckets.move_to_end(key)

            allowed = bucket.tokens >= 1
            if allowed:
                bucket.tokens -= 1
                retry_after = 0
            else:
                retry_after = max(1, math.ceil((1 - bucket.tokens) / refill_rate))
            remaining = max(0, math.floor(bucket.tokens))

            while len(self._buckets) > self._maximum_buckets:
                self._buckets.popitem(last=False)
            return allowed, retry_after, remaining


def _header_values(scope: Scope, name: bytes) -> Iterable[bytes]:
    return (value for key, value in scope.get("headers", []) if key.lower() == name)


def _peer_address(scope: Scope) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    client = scope.get("client")
    if not isinstance(client, tuple) or not client:
        return None
    try:
        return ipaddress.ip_address(client[0])
    except ValueError:
        return None


def client_identity(scope: Scope) -> str:
    """Use Cloudflare's address only when a private/loopback proxy delivered it."""

    peer = _peer_address(scope)
    if peer is not None and (peer.is_private or peer.is_loopback):
        forwarded = list(_header_values(scope, b"cf-connecting-ip"))
        if len(forwarded) == 1:
            try:
                return ipaddress.ip_address(forwarded[0].decode("ascii").strip()).compressed
            except (UnicodeDecodeError, ValueError):
                pass
    return "unknown" if peer is None else peer.compressed


def _request_id(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        value = state.get("request_id")
        if isinstance(value, str):
            return value
    for value in _header_values(scope, b"x-request-id"):
        candidate = value.decode("latin-1")
        if REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
    return "unavailable"


def _rule_for(scope: Scope, rules: tuple[RateLimitRule, ...]) -> RateLimitRule | None:
    method = str(scope.get("method", "")).upper()
    path = str(scope.get("path", ""))
    return next(
        (rule for rule in rules if method == rule.method and rule.path.fullmatch(path)),
        None,
    )


async def _send_rate_limited(scope: Scope, send: Send, *, retry_after: int) -> None:
    payload: dict[str, Any] = {
        "type": "https://authorityclosers.com/problems/rate-limited",
        "title": "Too many requests",
        "status": 429,
        "detail": "Too many requests were made to this operation. Try again later.",
        "instance": str(scope.get("path", "/"))[:512],
        "code": "rate_limited",
        "request_id": _request_id(scope),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/problem+json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
                (b"retry-after", str(retry_after).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        rules: tuple[RateLimitRule, ...] = DEFAULT_RATE_LIMIT_RULES,
        limiter: InMemoryTokenBucketLimiter | None = None,
    ) -> None:
        self.app = app
        self.rules = rules
        self.limiter = limiter or InMemoryTokenBucketLimiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        rule = _rule_for(scope, self.rules)
        if rule is None:
            await self.app(scope, receive, send)
            return
        identity = client_identity(scope)
        digest = hashlib.sha256(f"{rule.name}:{identity}".encode()).hexdigest()
        allowed, retry_after, _remaining = await self.limiter.consume(digest, rule)
        if not allowed:
            await _send_rate_limited(scope, send, retry_after=retry_after)
            return
        await self.app(scope, receive, send)
