from __future__ import annotations

import asyncio
import ipaddress
import re

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncClient

from ac_platform.http.rate_limits import (
    InMemoryTokenBucketLimiter,
    RateLimitMiddleware,
    RateLimitRule,
    client_identity,
)


def _rule() -> RateLimitRule:
    return RateLimitRule(
        name="test-operation",
        method="GET",
        path=re.compile(r"^/limited$"),
        capacity=2,
        refill_seconds=60,
    )


def _app(
    *,
    clock: list[float],
    trusted_proxy_addresses: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address] = frozenset(),
) -> RateLimitMiddleware:
    application = FastAPI()

    @application.get("/limited")
    async def limited() -> PlainTextResponse:
        return PlainTextResponse("accepted")

    limiter = InMemoryTokenBucketLimiter(clock=lambda: clock[0])
    return RateLimitMiddleware(
        application,
        rules=(_rule(),),
        limiter=limiter,
        trusted_proxy_addresses=trusted_proxy_addresses,
    )


async def test_token_bucket_limits_and_refills_without_cross_client_leakage() -> None:
    clock = [0.0]
    application = _app(clock=clock)
    first_transport = ASGITransport(app=application, client=("8.8.8.8", 1000))
    second_transport = ASGITransport(app=application, client=("1.1.1.1", 1001))
    async with (
        AsyncClient(transport=first_transport, base_url="http://test") as first,
        AsyncClient(transport=second_transport, base_url="http://test") as second,
    ):
        assert (await first.get("/limited")).status_code == 200
        assert (await first.get("/limited")).status_code == 200
        rejected = await first.get("/limited", headers={"x-request-id": "rate-test"})
        assert (await second.get("/limited")).status_code == 200
        clock[0] = 30.0
        refilled = await first.get("/limited")

    assert rejected.status_code == 429
    assert rejected.headers["retry-after"] == "30"
    assert rejected.headers["cache-control"] == "no-store"
    assert rejected.json()["request_id"] == "rate-test"
    assert refilled.status_code == 200


async def test_cloudflare_address_is_trusted_only_from_a_private_proxy_peer() -> None:
    clock = [0.0]
    application = _app(
        clock=clock,
        trusted_proxy_addresses=frozenset({ipaddress.ip_address("172.20.0.2")}),
    )
    private_proxy = ASGITransport(app=application, client=("172.20.0.2", 1000))
    untrusted_private_peer = ASGITransport(app=application, client=("172.20.0.3", 1000))
    public_peer = ASGITransport(app=application, client=("9.9.9.9", 1000))
    async with (
        AsyncClient(transport=private_proxy, base_url="http://test") as proxied,
        AsyncClient(transport=untrusted_private_peer, base_url="http://test") as private_direct,
        AsyncClient(transport=public_peer, base_url="http://test") as direct,
    ):
        for _ in range(2):
            assert (
                await proxied.get("/limited", headers={"cf-connecting-ip": "8.8.8.8"})
            ).status_code == 200
        assert (
            await proxied.get("/limited", headers={"cf-connecting-ip": "8.8.8.8"})
        ).status_code == 429
        assert (
            await proxied.get("/limited", headers={"cf-connecting-ip": "1.1.1.1"})
        ).status_code == 200

        for forwarded in ("8.8.8.8", "1.1.1.1"):
            assert (
                await private_direct.get("/limited", headers={"cf-connecting-ip": forwarded})
            ).status_code == 200
        assert (
            await private_direct.get("/limited", headers={"cf-connecting-ip": "4.4.4.4"})
        ).status_code == 429

        for forwarded in ("8.8.8.8", "1.1.1.1"):
            assert (
                await direct.get("/limited", headers={"cf-connecting-ip": forwarded})
            ).status_code == 200
        assert (
            await direct.get("/limited", headers={"cf-connecting-ip": "4.4.4.4"})
        ).status_code == 429


def test_client_identity_rejects_invalid_or_duplicated_forwarding_values() -> None:
    base_scope = {
        "type": "http",
        "client": ("172.20.0.2", 1000),
    }

    trusted = frozenset({ipaddress.ip_address("172.20.0.2")})
    assert client_identity(
        {**base_scope, "headers": [(b"cf-connecting-ip", b"8.8.8.8")]},
        trusted_proxy_addresses=trusted,
    ) == ("8.8.8.8")
    assert (
        client_identity(
            {
                **base_scope,
                "headers": [
                    (b"cf-connecting-ip", b"8.8.8.8"),
                    (b"cf-connecting-ip", b"1.1.1.1"),
                ],
            },
            trusted_proxy_addresses=trusted,
        )
        == "172.20.0.2"
    )
    assert (
        client_identity(
            {**base_scope, "headers": [(b"cf-connecting-ip", b"not-an-address")]},
            trusted_proxy_addresses=trusted,
        )
        == "172.20.0.2"
    )


async def test_capacity_saturation_does_not_reset_an_exhausted_client() -> None:
    clock = [0.0]
    limiter = InMemoryTokenBucketLimiter(maximum_buckets=2, clock=lambda: clock[0])
    rule = RateLimitRule(
        name="saturation",
        method="GET",
        path=re.compile(r"^/limited$"),
        capacity=1,
        refill_seconds=60,
    )

    assert (await limiter.consume("victim", rule))[0] is True
    assert (await limiter.consume("victim", rule))[0] is False
    assert (await limiter.consume("other", rule))[0] is True
    saturated = await limiter.consume("attacker", rule)
    still_exhausted = await limiter.consume("victim", rule)

    assert saturated == (False, 60, 0)
    assert still_exhausted[0] is False


async def test_expired_buckets_are_purged_before_new_identity_admission() -> None:
    clock = [0.0]
    limiter = InMemoryTokenBucketLimiter(maximum_buckets=2, clock=lambda: clock[0])
    rule = _rule()

    assert (await limiter.consume("first", rule))[0] is True
    assert (await limiter.consume("second", rule))[0] is True
    clock[0] = 61.0

    assert (await limiter.consume("replacement", rule))[0] is True


async def test_concurrent_requests_cannot_oversubscribe_one_bucket() -> None:
    limiter = InMemoryTokenBucketLimiter(clock=lambda: 0.0)
    rule = RateLimitRule(
        name="concurrent",
        method="GET",
        path=re.compile(r"^/limited$"),
        capacity=10,
        refill_seconds=60,
    )

    results = await asyncio.gather(*(limiter.consume("same-client", rule) for _ in range(100)))

    assert sum(1 for allowed, _retry, _remaining in results if allowed) == 10
