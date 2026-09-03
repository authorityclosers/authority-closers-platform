from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ac_platform import __version__
from ac_platform.application.settings import Settings, get_settings
from ac_platform.db.session import engine, session_factory
from ac_platform.http.admin_learning import install_admin_learning_http
from ac_platform.http.auth import install_identity_http
from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.course import install_course_http
from ac_platform.http.identity_provider import OAuthIdentityProvider, create_google_provider
from ac_platform.http.learning import (
    ActivityMediaResolver,
    MediaDescriptorResolver,
    PolicyResolver,
    install_learning_http,
)
from ac_platform.http.media import install_media_http
from ac_platform.http.operations import install_operations_http
from ac_platform.http.planning import install_planning_http
from ac_platform.http.problem import problem_response, register_problem_handlers
from ac_platform.http.rate_limits import RateLimitMiddleware
from ac_platform.http.request_context import request_context_middleware
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.media.runtime import MediaRuntime, create_default_media_runtime

logger = structlog.get_logger()
settings = get_settings()
_DEPLOYMENT_ENVIRONMENTS = {"staging", "production"}


def _google_provider_from_settings(settings: Settings) -> OAuthIdentityProvider:
    if not settings.google_oauth_configured:
        raise RuntimeError(
            "staging and production application composition requires a configured Google OAuth pair"
        )
    client_secret = settings.google_oauth_client_secret
    client_id = settings.google_oauth_client_id
    if client_secret is None or client_id is None:
        raise RuntimeError("validated Google OAuth settings are incomplete")
    return create_google_provider(
        client_id=client_id,
        client_secret=client_secret.get_secret_value(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "application_started", release_id=settings.release_id, environment=settings.environment
    )
    yield
    await engine.dispose()


def create_app(
    *,
    identity_provider: OAuthIdentityProvider | None = None,
    media_runtime: MediaRuntime | None = None,
) -> FastAPI:
    configured_identity_provider: OAuthIdentityProvider | None
    if settings.environment in _DEPLOYMENT_ENVIRONMENTS:
        if identity_provider is not None:
            raise RuntimeError(
                "staging and production application composition rejects injected identity providers"
            )
        configured_identity_provider = _google_provider_from_settings(settings)
    else:
        configured_identity_provider = identity_provider
        if configured_identity_provider is None and settings.google_oauth_configured:
            configured_identity_provider = _google_provider_from_settings(settings)
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
    # Static planning paths are registered before the dynamic
    # /v1/learning/{program_id} route so they cannot be parsed as UUIDs.
    install_planning_http(
        application,
        settings=settings,
        require_actor=require_actor,
    )
    resolved_media_runtime = media_runtime or create_default_media_runtime(settings)
    install_learning_http(
        application,
        settings=settings,
        require_actor=require_actor,
        activity_media_resolver=cast(
            ActivityMediaResolver | None, resolved_media_runtime.activity_media_resolver
        ),
        media_descriptor_resolver=cast(
            MediaDescriptorResolver | None, resolved_media_runtime.media_descriptor_resolver
        ),
        policy_resolver=(
            cast(PolicyResolver, resolved_media_runtime.playback_policy_resolver)
            if resolved_media_runtime.learning_playback_composed
            else None
        ),
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
    install_media_http(
        application,
        settings=settings,
        sessions=session_factory,
        require_actor=require_actor,
        runtime=resolved_media_runtime,
    )
    install_operations_http(
        application,
        settings=settings,
        sessions=session_factory,
        require_actor=require_actor,
    )
    application.add_middleware(RequestBodyLimitMiddleware)
    application.add_middleware(
        RateLimitMiddleware,
        trusted_proxy_addresses=settings.rate_limit_trusted_proxy_addresses,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.environment in {"local", "test", "development"}:
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
                "x-playback-token",
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
