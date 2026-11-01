"""Half an emoji never reaches a route (orchestrator, 1 Nov 2026).

Text cut mid-emoji leaves a lone UTF-16 surrogate, which a browser's JSON writes as an escape
(``\\ud83d``). A plain ``str`` field accepts it, and the request then fails as a 500 when the
text is saved (PostgreSQL refuses it) or answered back (UTF-8 cannot carry it). This middleware
drops every lone surrogate from a JSON body's strings, keys too, before any route reads it.

It acts only on ``application/json`` bodies whose raw bytes hold such an escape, within the
route's size limit; every other request keeps its exact bytes and its own receive, so uploads
still stream. It sits inside RequestBodyLimitMiddleware, which has already bounded the body and
hands it over whole. A body that is not valid JSON passes through untouched. One log line counts
the drops on a route; never the text.
"""

from __future__ import annotations

import json
import re
from typing import Any

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ac_platform.http.request_limits import SAFE_METHODS, request_body_limit

# A JSON escape for any surrogate half (a whole emoji's pair matches too; only lone ones go).
_ESCAPE = re.compile(rb"\\u[dD][89a-fA-F][0-9a-fA-F]{2}")
_HALF = re.compile(r"[\ud800-\udfff]")


def _header(scope: Scope, name: bytes) -> list[bytes]:
    return [value for key, value in scope.get("headers", ()) if key.lower() == name]


def _json_within_limit(scope: Scope) -> bool:
    types = _header(scope, b"content-type")
    if len(types) != 1 or types[0].split(b";", 1)[0].strip().lower() != b"application/json":
        return False
    lengths = _header(scope, b"content-length")
    if len(lengths) != 1 or not lengths[0].isdigit():
        return False
    return int(lengths[0]) <= request_body_limit(scope)


def whole_text(body: bytes) -> tuple[bytes, int]:
    """``body`` without lone surrogates in its strings and keys, and how many went. The same
    bytes when it has none or is not JSON."""
    if not _ESCAPE.search(body):
        return body, 0
    try:
        value = json.loads(body)
    except ValueError:
        return body, 0
    dropped = 0

    def clean(item: Any) -> Any:
        nonlocal dropped
        if isinstance(item, str):
            kept, count = _HALF.subn("", item)
            dropped += count
            return kept
        if isinstance(item, list):
            return [clean(part) for part in item]
        if isinstance(item, dict):
            return {clean(key): clean(part) for key, part in item.items()}
        return item

    cleaned = clean(value)
    if not dropped:
        return body, 0
    return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), dropped


class WholeTextMiddleware:
    """A JSON body without half an emoji, before validation (see the module's note)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method", "").upper() in SAFE_METHODS
            or not _json_within_limit(scope)
        ):
            await self.app(scope, receive, send)
            return
        chunks: list[bytes] = []
        disconnected = False
        while True:
            message = await receive()
            if message.get("type") == "http.request":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                disconnected = True
                break
        body, dropped = whole_text(b"".join(chunks))
        if dropped:
            # A fresh logger each time, so it follows the logging set up now.
            structlog.get_logger(__name__).info(
                "json_half_characters_dropped",
                method=scope.get("method"),
                path=scope.get("path"),
                count=dropped,
            )
            headers = [
                (k, v) for k, v in scope.get("headers", ()) if k.lower() != b"content-length"
            ]
            headers.append((b"content-length", str(len(body)).encode("ascii")))
            scope = {**scope, "headers": headers}
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            if disconnected:
                return {"type": "http.disconnect"}
            return await receive()

        await self.app(scope, replay, send)
