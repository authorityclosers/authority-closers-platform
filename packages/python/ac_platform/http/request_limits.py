from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

from starlette.types import Message, Receive, Scope, Send

from ac_platform.http.request_context import REQUEST_ID_PATTERN

MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024
MAX_PROBLEM_INSTANCE_LENGTH = 512
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_DRAFT_PATH = re.compile(r"^/v1/activities/[^/]+/draft$")
_EVIDENCE_PATH = re.compile(r"^/v1/activities/[^/]+/evidence$")
_WEBHOOK_PATH = re.compile(r"^/internal/v1/providers/[^/]+/webhooks$")


def request_body_limit(scope: Scope) -> int:
    path = scope.get("path", "")
    if _DRAFT_PATH.fullmatch(path):
        return 64 * 1024
    if _EVIDENCE_PATH.fullmatch(path):
        return 256 * 1024
    if _WEBHOOK_PATH.fullmatch(path):
        return 512 * 1024
    return MAX_REQUEST_BODY_BYTES


def _header_values(scope: Scope, name: bytes) -> Iterable[bytes]:
    return (value for key, value in scope.get("headers", []) if key.lower() == name)


def _declared_length(scope: Scope) -> int | None:
    lengths: list[int] = []
    for value in _header_values(scope, b"content-length"):
        normalized = value.strip()
        if not normalized or not all(48 <= digit <= 57 for digit in normalized):
            continue
        significant = normalized.lstrip(b"0") or b"0"
        limit_digits = str(MAX_REQUEST_BODY_BYTES).encode("ascii")
        if len(significant) > len(limit_digits):
            lengths.append(MAX_REQUEST_BODY_BYTES + 1)
        else:
            lengths.append(int(significant))
    return max(lengths, default=None)


def _request_id(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, MutableMapping):
        request_id = state.get("request_id")
        if isinstance(request_id, str):
            return request_id
    for value in _header_values(scope, b"x-request-id"):
        candidate = value.decode("latin-1")
        if REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
    return "unavailable"


def _too_large_payload(scope: Scope) -> dict[str, Any]:
    instance = scope.get("path", "/")
    return {
        "type": "https://authorityclosers.com/problems/request-body-too-large",
        "title": "Request body too large",
        "status": 413,
        "detail": "The request body exceeds the permitted size.",
        "instance": instance[:MAX_PROBLEM_INSTANCE_LENGTH],
        "code": "request_body_too_large",
        "request_id": _request_id(scope),
    }


async def _send_too_large(scope: Scope, send: Send) -> None:
    body = json.dumps(_too_large_payload(scope), separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/problem+json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class RequestBodyLimitMiddleware:
    """Reject oversized request bodies before Starlette/FastAPI parses them."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("method", "").upper() in SAFE_METHODS:
            await self.app(scope, receive, send)
            return

        limit = request_body_limit(scope)
        if (_declared_length(scope) or 0) > limit:
            await _send_too_large(scope, send)
            return

        received = 0
        overflowed = False

        async def limited_receive() -> Message:
            nonlocal received, overflowed
            if overflowed:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                received += len(body)
                if received > limit:
                    overflowed = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if overflowed and not response_started:
                return
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, limited_receive, tracked_send)
        if overflowed and not response_started:
            await _send_too_large(scope, send)
