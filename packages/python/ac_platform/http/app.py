from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ac_platform import __version__
from ac_platform.application.settings import get_settings
from ac_platform.db.session import engine, session_factory
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import install_identity_http
from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.course import install_course_http
from ac_platform.http.identity_provider import OAuthIdentityProvider, create_google_provider
from ac_platform.http.learning import install_learning_http
from ac_platform.http.operations import install_operations_http
from ac_platform.http.problem import problem_response, register_problem_handlers
from ac_platform.http.request_context import request_context_middleware
from ac_platform.http.request_limits import RequestBodyLimitMiddleware

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_started", release_id=settings.release_id, environment=settings.environment
    )
    yield
    await engine.dispose()


def create_app(*, identity_provider: OAuthIdentityProvider | None = None) -> FastAPI:
    configured_identity_provider = identity_provider
    if configured_identity_provider is None and settings.google_oauth_configured:
        client_secret = settings.google_oauth_client_secret
        client_id = settings.google_oauth_client_id
        if client_secret is None or client_id is None:
            raise RuntimeError("validated Google OAuth settings are incomplete")
        configured_identity_provider = create_google_provider(
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
        )
    application = FastAPI(
        title="Authority Closers Platform API",
        version=__version__,
        docs_url="/docs" if settings.environment not in {"staging", "production"} else None,
        openapi_url=(
            "/openapi.json" if settings.environment not in {"staging", "production"} else None
        ),
        redoc_url=None,
        lifespan=lifespan,
    )
    register_problem_handlers(application)
    require_actor = install_identity_http(
        application,
        settings=settings,
        sessions=session_factory,
        provider=configured_identity_provider,
    )
    install_course_http(
        application,
        settings=settings,
        sessions=session_factory,
        require_actor=require_actor,
    )
    install_learning_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )
    install_certificate_http(
        application,
        require_actor=require_actor,
    )
    install_admin_learning_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )
    install_operations_http(
        application,
        settings=settings,
        sessions=session_factory,
        require_actor=require_actor,
    )
    application.add_middleware(RequestBodyLimitMiddleware)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "authorization",
            "content-type",
            "idempotency-key",
            "if-match",
            "x-request-id",
        ],
        expose_headers=["etag", "x-request-id", "x-ac-release-id"],
        max_age=600,
    )

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
