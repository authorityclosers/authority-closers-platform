"""Prepare request-only lazy work before ASGI startup finishes, without calling endpoints."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from anyio.to_thread import run_sync

if TYPE_CHECKING:
    from fastapi import FastAPI


def warm_request_paths(application: FastAPI, metrics_root: str | None) -> None:
    """Run on a worker thread, before freezing the long-lived startup heap.

    Public ASGI route matching forces FastAPI's lazy included-route contexts to
    compile (dependencies and response validators). An unmatched path cannot run
    handlers, authenticate, access the DB or activate a provider. This also covers
    routes excluded from OpenAPI, without constructing a second huge schema graph.
    """
    from ac_platform.conversation_intelligence import brain4, review_schema
    from ac_platform.conversation_intelligence.cost_metrics import read_store
    from ac_platform.identity import characters
    from ac_platform.telemetry.sales_xray import SALES_XRAY_SURFACE

    scope = {
        "type": "http",
        "path": "/__startup_route_warmup__",
        "root_path": "",
        "method": "GET",
        "headers": [],
        "query_string": b"",
    }
    for route in application.routes:
        route.matches(scope)
    characters.load()
    review_schema.registry()
    review_schema.digest()
    brain4.rubric()
    brain4.guide()
    # Materialize the bounded taxonomy at startup; admission/consent stay per request.
    tuple(SALES_XRAY_SURFACE.events.items())
    read_store(metrics_root)


async def warmup(application: FastAPI, metrics_root: str | None) -> None:
    started = perf_counter()
    await run_sync(warm_request_paths, application, metrics_root)
    structlog.get_logger(__name__).info(
        "request_paths_warmed", duration_ms=round((perf_counter() - started) * 1000, 2)
    )
