from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ac_platform import __version__
from ac_platform.application.settings import get_settings
from ac_platform.db.session import engine
from ac_platform.http.problem import problem_response, register_problem_handlers
from ac_platform.http.request_context import request_context_middleware

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_started", release_id=settings.release_id, environment=settings.environment
    )
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Authority Closers Platform API",
        version=__version__,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    register_problem_handlers(application)

    @application.middleware("http")
    async def request_context(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        return await request_context_middleware(
            request,
            call_next,
            release_id=settings.release_id,
            environment=settings.environment,
        )

    @application.get("/health/live", tags=["operations"])
    async def live() -> dict[str, str]:
        return {"status": "alive", "release_id": settings.release_id}

    @application.get("/health/ready", tags=["operations"])
    async def ready(request: Request) -> Response:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except Exception:
            logger.exception("readiness_database_failed")
            return problem_response(
                request=request,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                code="not_ready",
                title="Service is not ready",
                detail="A critical dependency is unavailable.",
            )
        return JSONResponse({"status": "ready", "release_id": settings.release_id})

    return application


app = create_app()
