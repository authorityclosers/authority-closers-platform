from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
from asyncio import Lock
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
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
        name="password-register",
        method="POST",
        path=re.compile(r"^/v1/auth/password/register$"),
        capacity=5,
        refill_seconds=900,
    ),
    RateLimitRule(
        name="password-login",
        method="POST",
        path=re.compile(r"^/v1/auth/password/login$"),
        capacity=10,
        refill_seconds=600,
    ),
    RateLimitRule(
        name="password-recovery",
        method="POST",
        path=re.compile(r"^/v1/auth/password/recovery$"),
        capacity=5,
        refill_seconds=900,
    ),
    RateLimitRule(
        name="password-resend-verification",
        method="POST",
        path=re.compile(r"^/v1/auth/password/resend-verification$"),
        capacity=5,
        refill_seconds=900,
    ),
    RateLimitRule(
        name="password-verify",
        method="POST",
        path=re.compile(r"^/v1/auth/password/verify$"),
        capacity=20,
        refill_seconds=600,
    ),
    RateLimitRule(
        name="password-reset",
        method="POST",
        path=re.compile(r"^/v1/auth/password/reset$"),
        capacity=5,
        refill_seconds=900,
    ),
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
    expires_at: float


@dataclass(slots=True)
class _Partition:
    buckets: dict[str, _Bucket] = field(default_factory=dict)
    overflow: _Bucket | None = None
    next_maintenance_at: float | None = None


class InMemoryTokenBucketLimiter:
    """Bounded per-rule single-process limiter with a shared overflow bucket."""

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
        self._partitions: dict[str, _Partition] = {}
        self._lock = Lock()

    @staticmethod
    def _refilled_tokens(bucket: _Bucket, now: float, rule: RateLimitRule) -> float:
        elapsed = max(0.0, now - bucket.updated_at)
        refill_rate = rule.capacity / rule.refill_seconds
        return min(float(rule.capacity), bucket.tokens + elapsed * refill_rate)

    @classmethod
    def _reclaimable_at(cls, bucket: _Bucket, rule: RateLimitRule) -> float:
        refill_rate = rule.capacity / rule.refill_seconds
        seconds_to_full = max(0.0, float(rule.capacity) - bucket.tokens) / refill_rate
        return min(bucket.expires_at, bucket.updated_at + seconds_to_full)

    @classmethod
    def _maintain_partition(
        cls,
        partition: _Partition,
        now: float,
        rule: RateLimitRule,
        maximum_buckets: int,
    ) -> None:
        if partition.next_maintenance_at is not None and now < partition.next_maintenance_at:
            return
        expired = [key for key, bucket in partition.buckets.items() if bucket.expires_at <= now]
        for key in expired:
            del partition.buckets[key]
        if len(partition.buckets) >= maximum_buckets:
            reclaimable = [
                (bucket.updated_at, key)
                for key, bucket in partition.buckets.items()
                if cls._refilled_tokens(bucket, now, rule) >= rule.capacity
            ]
            if reclaimable:
                _, key = min(reclaimable)
                del partition.buckets[key]
        partition.next_maintenance_at = min(
            (cls._reclaimable_at(bucket, rule) for bucket in partition.buckets.values()),
            default=None,
        )

    @staticmethod
    def _new_bucket(now: float, rule: RateLimitRule) -> _Bucket:
        return _Bucket(
            tokens=float(rule.capacity),
            updated_at=now,
            # A fixed lifetime prevents an attacker from pinning admission state
            # forever by refreshing arbitrary identities.
            expires_at=now + rule.refill_seconds,
        )

    @classmethod
    def _consume_bucket(
        cls,
        bucket: _Bucket,
        now: float,
        rule: RateLimitRule,
    ) -> tuple[bool, int, int]:
        refill_rate = rule.capacity / rule.refill_seconds
        bucket.tokens = cls._refilled_tokens(bucket, now, rule)
        bucket.updated_at = max(now, bucket.updated_at)
        allowed = bucket.tokens >= 1
        if allowed:
            bucket.tokens -= 1
            retry_after = 0
        else:
            seconds_until_token = max(0.0, (1 - bucket.tokens) / refill_rate)
            retry_after = max(1, math.ceil(seconds_until_token - 1e-9))
        return allowed, retry_after, max(0, math.floor(bucket.tokens))

    async def consume(self, key: str, rule: RateLimitRule) -> tuple[bool, int, int]:
        now = self._clock()
        async with self._lock:
            partition = self._partitions.setdefault(rule.name, _Partition())
            self._maintain_partition(partition, now, rule, self._maximum_buckets)
            bucket = partition.buckets.get(key)
            if bucket is None:
                if len(partition.buckets) >= self._maximum_buckets:
                    overflow = partition.overflow
                    if overflow is None or overflow.expires_at <= now:
                        overflow = self._new_bucket(now, rule)
                        partition.overflow = overflow
                    return self._consume_bucket(overflow, now, rule)
                bucket = self._new_bucket(now, rule)
                partition.buckets[key] = bucket
            outcome = self._consume_bucket(bucket, now, rule)
            reclaimable_at = self._reclaimable_at(bucket, rule)
            if (
                partition.next_maintenance_at is None
                or reclaimable_at < partition.next_maintenance_at
            ):
                partition.next_maintenance_at = reclaimable_at
            return outcome


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


def _normalized_client_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> str:
    if isinstance(address, ipaddress.IPv4Address):
        return address.compressed
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped.compressed
    network = ipaddress.ip_network((address, 64), strict=False)
    return f"{network.network_address.compressed}/64"


def client_identity(
    scope: Scope,
    *,
    trusted_proxy_addresses: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address] = frozenset(),
) -> str:
    """Use Cloudflare's address only when an explicitly trusted proxy delivered it."""

    peer = _peer_address(scope)
    if peer is not None and peer in trusted_proxy_addresses:
        forwarded = list(_header_values(scope, b"cf-connecting-ip"))
        if len(forwarded) == 1:
            try:
                return _normalized_client_address(
                    ipaddress.ip_address(forwarded[0].decode("ascii").strip())
                )
            except (UnicodeDecodeError, ValueError):
                pass
    return "unknown" if peer is None else _normalized_client_address(peer)


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
        trusted_proxy_addresses: frozenset[
            ipaddress.IPv4Address | ipaddress.IPv6Address
        ] = frozenset(),
    ) -> None:
        self.app = app
        self.rules = rules
        self.limiter = limiter or InMemoryTokenBucketLimiter()
        self.trusted_proxy_addresses = trusted_proxy_addresses

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        rule = _rule_for(scope, self.rules)
        if rule is None:
            await self.app(scope, receive, send)
            return
        identity = client_identity(
            scope,
            trusted_proxy_addresses=self.trusted_proxy_addresses,
        )
        digest = hashlib.sha256(f"{rule.name}:{identity}".encode()).hexdigest()
        allowed, retry_after, _remaining = await self.limiter.consume(digest, rule)
        if not allowed:
            await _send_rate_limited(scope, send, retry_after=retry_after)
            return
        await self.app(scope, receive, send)
