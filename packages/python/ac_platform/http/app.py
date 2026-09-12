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
from ac_platform.http.app_updates import install_app_updates_http
from ac_platform.http.auth import install_identity_http
from ac_platform.http.certificates import install_certificate_http
from ac_platform.http.community import install_community_http
from ac_platform.http.conversation import install_conversation_http
from ac_platform.http.conversation_admin import install_conversation_admin_http
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.course import install_course_http
from ac_platform.http.identity_provider import OAuthIdentityProvider, create_google_provider
from ac_platform.http.learning import (
    ActivityMediaResolver,
    MediaDescriptorResolver,
    PolicyResolver,
    install_learning_http,
)
from ac_platform.http.media import install_media_http
from ac_platform.http.media_delivery import install_media_delivery_http
from ac_platform.http.operations import install_operations_http
from ac_platform.http.planning import install_planning_http
from ac_platform.http.platform import install_platform_http
from ac_platform.http.practice import install_practice_http
from ac_platform.http.problem import problem_response, register_problem_handlers
from ac_platform.http.rate_limits import RateLimitMiddleware
from ac_platform.http.request_context import request_context_middleware
from ac_platform.http.request_limits import RequestBodyLimitMiddleware
from ac_platform.http.studio_media import install_studio_media_http
from ac_platform.http.studio_video_bytes import StudioVideoByteTransport
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.http.telemetry import install_telemetry_http
from ac_platform.media.runtime import MediaRuntime, create_default_media_runtime
from ac_platform.media.studio_video_completion import StudioVideoCompletion

logger = structlog.get_logger()
settings = get_settings()
_DEPLOYMENT_ENVIRONMENTS = {"staging", "production"}
_MEDIA_RUNTIME_INJECTION_ENVIRONMENTS = {"local", "test"}


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
    conversation_intake_runtime: ConversationIntakeRuntime | None = None,
) -> FastAPI:
    # Provider activation is closed in this slice.  There is no immutable
    # externally attested activation boundary, inbox-first/quick-ACK webhook
    # worker, or reviewed app delivery handler in the shipped composition.
    # Dependency injection therefore remains a local/test seam only.
    if settings.environment not in _MEDIA_RUNTIME_INJECTION_ENVIRONMENTS:
        if media_runtime is not None:
            raise RuntimeError("non-local application composition rejects injected media runtimes")
        if settings.media_provider_enabled:
            raise RuntimeError(
                "non-local application composition rejects enabled media provider settings"
            )
    elif media_runtime is not None and media_runtime.environment != settings.environment:
        raise RuntimeError(
            "local/test media runtime injection must match the application environment"
        )
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
    install_practice_http(application, settings=settings, require_actor=require_actor)
    if conversation_intake_runtime is not None and settings.environment not in {"local", "test"}:
        raise RuntimeError(
            "Hosted conversation intake requires its reviewed deployment composition."
        )
    install_conversation_http(
        application,
        settings=settings,
        require_actor=require_actor,
        intake_runtime=conversation_intake_runtime,
    )
    install_conversation_admin_http(
        application,
        settings=settings,
        require_actor=require_actor,
        import_storage=conversation_intake_runtime.storage if conversation_intake_runtime else None,
    )
    install_community_http(application, settings=settings, require_actor=require_actor)
    install_app_updates_http(application, settings=settings, require_actor=require_actor)
    install_platform_http(application, settings=settings, require_actor=require_actor)
    # Static planning paths are registered before the dynamic
    # /v1/learning/{program_id} route so they cannot be parsed as UUIDs.
    install_planning_http(
        application,
        settings=settings,
        require_actor=require_actor,
        legacy_analytics_enabled=False,
    )
    # Learner telemetry is present as a fail-closed API boundary only.  A
    # verified server consent resolver and explicit retention policy must be
    # composed by a later controlled promotion before any row is stored.
    install_telemetry_http(
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
    studio_video_runtime = resolved_media_runtime.studio_video_runtime
    studio_video_transport: StudioVideoByteTransport | None = None
    studio_video_max_source_bytes: int | None = None
    studio_service = resolved_media_runtime.service
    studio_completion: StudioVideoCompletion | None = None
    if studio_video_runtime is not None:
        studio_video_runtime.validate()
        if (
            studio_video_runtime.settings is not settings
            or studio_video_runtime.sessions is not session_factory
            or studio_video_runtime.service.storage is not studio_video_runtime.storage
        ):
            raise RuntimeError(
                "Studio video runtime must share the application's settings and session factory"
            )
        studio_service = studio_video_runtime.service
        studio_completion = studio_video_runtime.completion
        studio_video_max_source_bytes = studio_video_runtime.max_source_bytes
        studio_video_transport = StudioVideoByteTransport(
            storage=studio_video_runtime.storage,
            require_actor=require_actor,
            settings=settings,
        )
    # Deliberately expose one bounded worker without scheduling it in the HTTP
    # process. A reviewed local runner can invoke run_once explicitly.
    application.state.studio_video_worker = (
        None if studio_video_runtime is None else studio_video_runtime.worker
    )
    install_studio_media_http(
        application,
        settings=settings,
        require_actor=require_actor,
        service=studio_service,
        byte_transport=studio_video_transport,
        video_completion=studio_completion,
        video_upload_max_source_bytes=studio_video_max_source_bytes,
        studio_video_runtime=studio_video_runtime,
    )
    delivery_factory = resolved_media_runtime.authenticated_delivery_handler_factory
    if delivery_factory is not None:
        if resolved_media_runtime.media_cors_policy is None:
            raise RuntimeError("authenticated media delivery requires its exact-origin policy")
        install_media_delivery_http(
            application,
            cors_policy=resolved_media_runtime.media_cors_policy,
            require_actor=require_actor,
            authenticated_handler_factory=delivery_factory,
        )
    install_operations_http(
        application,
        settings=settings,
        sessions=session_factory,
        require_actor=require_actor,
    )
    application.add_middleware(
        RequestBodyLimitMiddleware,
        local_avatar_upload_enabled=settings.environment == "local"
        and settings.media_local_avatar_enabled,
        studio_video_upload_max_bytes=studio_video_max_source_bytes,
        conversation_upload_max_bytes=conversation_intake_runtime.storage.max_bytes
        if conversation_intake_runtime
        else None,
    )
    application.add_middleware(
        RateLimitMiddleware,
        trusted_proxy_addresses=settings.rate_limit_trusted_proxy_addresses,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    application.add_middleware(CoachSurfaceMiddleware, settings=settings)
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
                "x-analysis-quote",
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
