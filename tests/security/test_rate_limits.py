from __future__ import annotations

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


def _app(*, clock: list[float]) -> RateLimitMiddleware:
    application = FastAPI()

    @application.get("/limited")
    async def limited() -> PlainTextResponse:
        return PlainTextResponse("accepted")

    limiter = InMemoryTokenBucketLimiter(clock=lambda: clock[0])
    return RateLimitMiddleware(application, rules=(_rule(),), limiter=limiter)


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
    application = _app(clock=clock)
    private_proxy = ASGITransport(app=application, client=("172.20.0.2", 1000))
    public_peer = ASGITransport(app=application, client=("9.9.9.9", 1000))
    async with (
        AsyncClient(transport=private_proxy, base_url="http://test") as proxied,
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

    assert client_identity({**base_scope, "headers": [(b"cf-connecting-ip", b"8.8.8.8")]}) == (
        "8.8.8.8"
    )
    assert (
        client_identity(
            {
                **base_scope,
                "headers": [
                    (b"cf-connecting-ip", b"8.8.8.8"),
                    (b"cf-connecting-ip", b"1.1.1.1"),
                ],
            }
        )
        == "172.20.0.2"
    )
    assert (
        client_identity({**base_scope, "headers": [(b"cf-connecting-ip", b"not-an-address")]})
        == "172.20.0.2"
    )
