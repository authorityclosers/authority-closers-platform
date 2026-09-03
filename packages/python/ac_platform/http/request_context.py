from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = structlog.get_logger()


def safe_request_id(candidate: str | None) -> str:
    if candidate is not None and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return str(uuid4())


async def request_context_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
    *,
    release_id: str,
    environment: str,
) -> Response:
    request_id = safe_request_id(request.headers.get("x-request-id"))
    request.state.request_id = request_id
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            release_id=release_id,
            environment=environment,
        )
        raise
    duration_ms = round((perf_counter() - started) * 1000, 2)
    response.headers["x-request-id"] = request_id
    response.headers["x-ac-release-id"] = release_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    logger.info(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        release_id=release_id,
        environment=environment,
    )
    return response
