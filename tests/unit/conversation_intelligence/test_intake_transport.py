"""Unit proof for the session-bound, bounded conversation upload transport."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ac_platform.application.settings import Settings
from ac_platform.http.auth import RequestOriginDenied
from ac_platform.http.conversation_intake import (
    ConversationByteTransport,
    ConversationIntakeRuntime,
)


def request_with_body(
    headers: list[tuple[bytes, bytes]], *, query: bytes = b"", body: bytes = b"payload"
) -> tuple[Request, dict[str, int]]:
    received = {"count": 0}

    async def receive() -> dict[str, Any]:
        received["count"] += 1
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "PUT",
        "scheme": "http",
        "path": "/v1/conversation/recordings/recording/source",
        "raw_path": b"/v1/conversation/recordings/recording/source",
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 8000),
        "server": ("localhost", 8000),
    }
    return Request(scope, receive), received


def valid_headers(
    *,
    content_length: str = "16",
    content_type: str = "application/octet-stream",
    origin: str = "http://localhost:3000",
    transfer_encoding: str | None = None,
) -> list[tuple[bytes, bytes]]:
    headers = [
        (b"host", b"localhost"),
        (b"origin", origin.encode()),
        (b"content-length", content_length.encode()),
        (b"content-type", content_type.encode()),
    ]
    if transfer_encoding is not None:
        headers.append((b"transfer-encoding", transfer_encoding.encode()))
    return headers


@pytest.fixture
def transport() -> tuple[ConversationByteTransport, dict[str, int]]:
    calls = {"auth": 0}

    async def require_actor(_request: Request) -> AsyncIterator[object]:
        calls["auth"] += 1
        raise AssertionError("transport validation must finish before authentication")
        yield

    storage = SimpleNamespace(root=Path("C:/ac-intake-storage"), max_bytes=16)
    scratch = SimpleNamespace(root=Path("C:/ac-intake-scratch"), max_bytes=16)
    runtime = cast(
        ConversationIntakeRuntime,
        SimpleNamespace(storage=storage, scratch=scratch, policy=None),
    )
    settings = Settings(_env_file=None, environment="test")
    return ConversationByteTransport(runtime, settings, require_actor), calls


def test_invalid_scope_and_origin_are_rejected_before_auth_or_body_read(transport):
    adapter, calls = transport
    cases = (
        (request_with_body(valid_headers(), query=b"scope=other"), HTTPException, 422),
        (
            request_with_body(valid_headers(origin="https://evil.example")),
            RequestOriginDenied,
            403,
        ),
    )
    for (request, received), error_type, status_code in cases:
        with pytest.raises(error_type) as caught:
            asyncio.run(adapter.accept(request, uuid4(), uuid4()))
        if isinstance(caught.value, HTTPException):
            assert caught.value.status_code == status_code
        else:
            assert caught.value.status == status_code
        assert calls["auth"] == 0
        assert received["count"] == 0


@pytest.mark.parametrize(
    ("name", "headers"),
    [
        ("zero bytes", valid_headers(content_length="0")),
        (
            "missing length",
            [
                (b"host", b"localhost"),
                (b"origin", b"http://localhost:3000"),
                (b"content-type", b"application/octet-stream"),
            ],
        ),
        ("over limit", valid_headers(content_length="17")),
        ("wrong content type", valid_headers(content_type="audio/wav")),
        ("transfer encoding", valid_headers(transfer_encoding="chunked")),
        ("duplicate length", valid_headers() + [(b"content-length", b"16")]),
    ],
)
def test_invalid_upload_headers_are_rejected_before_auth_or_body_read(transport, name, headers):
    del name
    adapter, calls = transport
    request, received = request_with_body(headers)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(adapter.accept(request, uuid4(), uuid4()))
    assert caught.value.status_code == 413
    assert calls["auth"] == 0
    assert received["count"] == 0
