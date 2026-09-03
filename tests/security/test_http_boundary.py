from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from httpx import ASGITransport, AsyncByteStream, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from ac_platform.http.app import app
from ac_platform.http.request_limits import (
    MAX_MEDIA_CAPTION_BYTES,
    MAX_MEDIA_WEBHOOK_BYTES,
    MAX_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    request_body_limit,
)


class ChunkedBody(AsyncByteStream):
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk


def test_media_routes_use_explicit_bounded_body_limits() -> None:
    assert request_body_limit({"path": "/v1/media/asset/captions"}) == MAX_MEDIA_CAPTION_BYTES
    assert (
        request_body_limit({"path": "/internal/v1/media/providers/video/webhooks"})
        == MAX_MEDIA_WEBHOOK_BYTES
    )
    assert request_body_limit({"path": "/v1/media/asset/playback-token"}) == MAX_REQUEST_BODY_BYTES


def _body_limit_app() -> RequestBodyLimitMiddleware:
    test_app = FastAPI()

    @test_app.api_route(
        "/v1/activities/{activity_id}/draft",
        methods=["PUT"],
    )
    async def draft(request: Request) -> PlainTextResponse:
        await request.body()
        return PlainTextResponse("accepted")

    @test_app.api_route(
        "/v1/activities/{activity_id}/evidence",
        methods=["POST"],
    )
    async def evidence(request: Request) -> PlainTextResponse:
        await request.body()
        return PlainTextResponse("accepted")

    @test_app.api_route("/health/live", methods=["GET", "HEAD", "OPTIONS"])
    async def health(request: Request) -> PlainTextResponse:
        await request.body()
        return PlainTextResponse("accepted")

    @test_app.api_route("/internal/v1/providers/{provider}/webhooks", methods=["POST"])
    async def webhook(request: Request) -> PlainTextResponse:
        await request.body()
        return PlainTextResponse("accepted")

    @test_app.post("/ignored-body")
    async def ignored_body() -> PlainTextResponse:
        return PlainTextResponse("accepted")

    return RequestBodyLimitMiddleware(test_app)


async def test_content_length_is_rejected_before_the_endpoint_reads_the_body() -> None:
    transport = ASGITransport(app=_body_limit_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/v1/activities/123/draft",
            content=b"x" * (64 * 1024 + 1),
            headers={"x-request-id": "security-test"},
        )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "https://authorityclosers.com/problems/request-body-too-large",
        "title": "Request body too large",
        "status": 413,
        "detail": "The request body exceeds the permitted size.",
        "instance": "/v1/activities/123/draft",
        "code": "request_body_too_large",
        "request_id": "security-test",
    }


async def test_streamed_body_is_counted_without_buffering_and_exact_limit_succeeds() -> None:
    transport = ASGITransport(app=_body_limit_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/v1/activities/123/evidence",
            content=ChunkedBody(b"x" * (128 * 1024), b"x" * (128 * 1024)),
        )
        rejected = await client.post(
            "/v1/activities/123/evidence",
            content=ChunkedBody(b"x" * (256 * 1024), b"x"),
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 413
    assert rejected.headers["content-type"] == "application/problem+json"
    assert "x" * 32 not in rejected.text


async def test_streamed_limit_is_enforced_before_a_bodyless_endpoint_runs() -> None:
    transport = ASGITransport(app=_body_limit_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/ignored-body",
            content=ChunkedBody(b"x" * MAX_REQUEST_BODY_BYTES, b"x"),
        )

    assert response.status_code == 413
    assert response.headers["content-type"] == "application/problem+json"


async def test_fragment_flood_is_coalesced_and_replay_delegates_disconnect() -> None:
    fragment_count = 100_000
    origin_receive_calls = 0
    downstream_messages: list[Message] = []

    async def origin_receive() -> Message:
        nonlocal origin_receive_calls
        origin_receive_calls += 1
        if origin_receive_calls <= fragment_count:
            return {"type": "http.request", "body": b"x", "more_body": True}
        if origin_receive_calls == fragment_count + 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        return {"type": "http.disconnect"}

    async def downstream(_scope: Scope, receive: Receive, _send: Send) -> None:
        downstream_messages.append(await receive())
        downstream_messages.append(await receive())

    async def unused_send(_message: Message) -> None:
        raise AssertionError("The downstream test app must not send a response")

    middleware = RequestBodyLimitMiddleware(downstream)
    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/fragmented",
            "headers": [],
        },
        origin_receive,
        unused_send,
    )

    assert origin_receive_calls == fragment_count + 2
    assert downstream_messages == [
        {
            "type": "http.request",
            "body": b"x" * fragment_count,
            "more_body": False,
        },
        {"type": "http.disconnect"},
    ]


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_global_limit_and_safe_method_body_behavior(method: str) -> None:
    transport = ASGITransport(app=_body_limit_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        rejected = await client.post(
            "/health/live",
            content=b"x" * (MAX_REQUEST_BODY_BYTES + 1),
        )
        accepted_get = await client.request(
            method,
            "/health/live",
            content=ChunkedBody(b"x" * (MAX_REQUEST_BODY_BYTES + 1)),
        )

    assert rejected.status_code == 413
    assert accepted_get.status_code == 200


async def test_shipped_app_413_keeps_request_context_security_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put(
            "/v1/activities/123/draft",
            content=b"x" * (64 * 1024 + 1),
            headers={"x-request-id": "boundary-request"},
        )

    assert response.status_code == 413
    assert response.headers["x-request-id"] == "boundary-request"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_provider_webhook_limit_is_512_kibibytes() -> None:
    transport = ASGITransport(app=_body_limit_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        accepted = await client.post(
            "/internal/v1/providers/provider/webhooks",
            content=ChunkedBody(b"x" * (512 * 1024)),
        )
        rejected = await client.post(
            "/internal/v1/providers/provider/webhooks",
            content=ChunkedBody(b"x" * (512 * 1024), b"x"),
        )

    assert accepted.status_code == 200
    assert rejected.status_code == 413


async def test_api_emits_baseline_security_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"


async def test_cors_allows_only_configured_origin_and_headers() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.options(
            "/health/live",
            headers={
                "origin": "http://localhost:3000",
                "access-control-request-method": "GET",
                "access-control-request-headers": "x-request-id",
            },
        )
        denied = await client.options(
            "/health/live",
            headers={
                "origin": "https://attacker.example",
                "access-control-request-method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


async def test_untrusted_host_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://evil.example") as client:
        response = await client.get("/health/live")

    assert response.status_code == 400
