"""Local Studio uploads to ordinary, enrollment-authorized learner playback.

Upload admission selects a private store; it does not grant playback. Each URL
and byte request still uses the existing approved binding, persisted grant,
browser session, enrollment and prerequisite checks. Existing avatar/film paths
keep their own handlers. No failed signature is retried against another handler.
This composition does not approve an instructional watch policy or a deployment.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import MultipleResultsFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.services import LearningAccessContext
from ac_platform.media.api_contracts import ActivityMediaDescriptorResponse
from ac_platform.media.bindings import (
    ActivityMediaBindingSnapshot,
    resolve_activity_media_binding_for_learning,
)
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.delivery import (
    MediaDeliveryResult,
    MediaTokenType,
    PrivateMediaDeliveryHandler,
)
from ac_platform.media.errors import MediaConfigurationError, MediaForbidden
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaBindingState,
    MediaUploadIntent,
    MediaVersion,
    StudioVideoUpload,
)
from ac_platform.media.policy import (
    MediaCorsPolicy,
    RangeMode,
    RangePolicy,
    SignedMediaDeliveryPort,
)
from ac_platform.media.runtime import MediaRuntime, _derive
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner

HandlerFactory = Callable[[Session, ActorContext], PrivateMediaDeliveryHandler]
DescriptorResolver = Callable[
    [AsyncSession, ActorContext, LearningAccessContext], Awaitable[ActivityMediaDescriptorResponse]
]


def _upload_program(database: Session, tenant: UUID, asset: UUID, version: UUID) -> UUID | None:
    # Immutable provenance, independent of processing/readiness. A revoked or
    # retired upload must keep routing to its own denying handler, not fallback.
    query = (
        select(StudioVideoUpload.program_id)
        .join(
            MediaUploadIntent,
            (MediaUploadIntent.id == StudioVideoUpload.upload_id)
            & (MediaUploadIntent.tenant_id == StudioVideoUpload.tenant_id),
        )
        .where(
            StudioVideoUpload.tenant_id == tenant,
            MediaUploadIntent.tenant_id == tenant,
            MediaUploadIntent.asset_id == asset,
            MediaUploadIntent.version_id == version,
        )
        .limit(2)
    )
    try:
        program = database.execute(query).scalar_one_or_none()
    except MultipleResultsFound as error:
        raise MediaForbidden("The video upload provenance is ambiguous.") from error
    if program is not None and (type(program) is not UUID or not program.int):
        raise MediaForbidden("The video upload provenance is unavailable.")
    return program


def _matches_upload_program(
    binding: ActivityMediaBindingSnapshot | ActivityMediaBinding, tenant: UUID, program: UUID
) -> bool:
    return (
        binding.tenant_id == tenant
        and binding.program_scope == "tenant"
        and binding.program_owner_key == tenant
        and program == binding.program_id
    )


def _owns_key(database: Session, actor: ActorContext, key: str) -> bool:
    parts = key.split("/")
    if len(parts) < 7 or parts[0] != "tenants" or parts[2:4] != ["media", "video"]:
        return False
    try:
        tenant, asset, version = (UUID(parts[index]) for index in (1, 4, 5))
    except (ValueError, TypeError):
        return False
    if tenant != actor.tenant_id or any(
        str(value) != parts[index]
        for value, index in zip((tenant, asset, version), (1, 4, 5), strict=True)
    ):
        return False
    if parts[6] == "original" and _upload_program(database, tenant, asset, version) is not None:
        return True
    media_version = database.scalar(
        select(MediaVersion).where(
            MediaVersion.tenant_id == tenant,
            MediaVersion.asset_id == asset,
            MediaVersion.id == version,
            MediaVersion.state == "ready",
        )
    )
    if not isinstance(media_version, MediaVersion) or (
        key != media_version.object_key and not key.startswith(media_version.object_key + "/")
    ):
        return False
    return (
        database.scalar(
            select(ActivityMediaBinding.id).where(
                ActivityMediaBinding.tenant_id == tenant,
                ActivityMediaBinding.asset_id == asset,
                ActivityMediaBinding.version_id == version,
                ActivityMediaBinding.program_scope == "global",
                ActivityMediaBinding.program_owner_key == GLOBAL_CATALOG_OWNER_KEY,
                ActivityMediaBinding.state == MediaBindingState.APPROVED.value,
            )
        )
        is not None
    )


class _StudioHandler(PrivateMediaDeliveryHandler):
    """Select a handler by immutable storage provenance, never by failed auth."""

    def __init__(
        self,
        *,
        database: Session,
        actor: ActorContext,
        service: MediaService,
        port: SignedMediaDeliveryPort,
        cors: MediaCorsPolicy,
        previous: HandlerFactory | None,
        max_object_bytes: int,
    ) -> None:
        self.database, self.actor, self.previous = database, actor, previous
        checker = DatabaseMediaDeliveryAuthorizer(
            database, actor, signer=service.signer, activity_resolver=resolve_catalog_activity
        )

        def authorize(claims: Mapping[str, object], kind: MediaTokenType) -> bool:
            if kind != "playback" or not checker.authorize(claims, kind):
                return False
            binding = database.get(ActivityMediaBinding, UUID(str(claims.get("binding_id"))))
            return (
                binding is not None
                and binding.tenant_id == actor.tenant_id
                and binding.state == MediaBindingState.APPROVED.value
                and (
                    (
                        binding.program_scope == "global"
                        and binding.program_owner_key == GLOBAL_CATALOG_OWNER_KEY
                    )
                    or (
                        binding.program_scope == "tenant"
                        and binding.program_owner_key == actor.tenant_id
                        and _upload_program(
                            database, actor.tenant_id, binding.asset_id, binding.version_id
                        )
                        == binding.program_id
                    )
                )
            )

        super().__init__(
            storage=service.storage,
            signer=port.signer,
            delivery_port=port,
            cors_policy=cors,
            authorizer=authorize,
            max_object_bytes=max_object_bytes,
        )

    def serve(
        self,
        *,
        token: str,
        token_type: str,
        object_key: str,
        method: str = "GET",
        origin: str | None = None,
        range_header: str | None = None,
        now: datetime | None = None,
    ) -> MediaDeliveryResult:
        if _owns_key(self.database, self.actor, object_key):
            selected = super().serve
        elif self.previous is not None:
            selected = self.previous(self.database, self.actor).serve
        else:
            raise MediaForbidden("The signed media object is not available.")
        return selected(
            token=token,
            token_type=token_type,
            object_key=object_key,
            method=method,
            origin=origin,
            range_header=range_header,
            now=now,
        )


@dataclass(frozen=True)
class _StudioHandlerFactory:
    service: MediaService
    port: SignedMediaDeliveryPort
    cors: MediaCorsPolicy
    previous: HandlerFactory | None
    max_object_bytes: int

    def __call__(self, database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        return _StudioHandler(
            database=database,
            actor=actor,
            service=self.service,
            port=self.port,
            cors=self.cors,
            previous=self.previous,
            max_object_bytes=self.max_object_bytes,
        )


def _compose_studio_video_delivery(
    settings: Settings,
    base: MediaRuntime,
    *,
    filesystem_runtime: bool,
) -> MediaRuntime:
    """Connect one explicit filesystem upload graph to normal learner delivery."""
    studio = base.studio_video_runtime
    allowed_environments = (
        {"test", "staging", "production"}
        if filesystem_runtime
        else {
            "local",
            "test",
        }
    )
    if (
        settings.environment not in allowed_environments
        or (filesystem_runtime and not settings.media_filesystem_enabled)
        or (not filesystem_runtime and settings.environment not in {"local", "test"})
        or base.environment != settings.environment
        or studio is None
        or studio.settings is not settings
        or settings.media_provider_enabled
        or base.provider_activation_verified
        or isinstance(base.authenticated_delivery_handler_factory, _StudioHandlerFactory)
    ):
        raise MediaConfigurationError(
            "Studio delivery requires one exact filesystem upload runtime."
            if filesystem_runtime
            else "Studio delivery requires one exact local/test upload runtime."
        )
    studio.validate()
    origin = str(settings.public_app_url).rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme == "http"
            and parsed.hostname not in {"localhost", "127.0.0.1", "learner.localhost"}
        )
        or (
            settings.environment == "local"
            and parsed.hostname not in {"localhost", "127.0.0.1", "learner.localhost"}
        )
        or (
            filesystem_runtime
            and settings.environment in {"staging", "production"}
            and origin
            not in {
                "https://learner-staging.authorityclosers.com",
                "https://learner.authorityclosers.com",
            }
        )
        or (base.media_delivery is not None and base.media_delivery.delivery_origin != origin)
        or (
            base.media_cors_policy is not None
            and base.media_cors_policy.allowed_origins != (origin,)
        )
    ):
        raise MediaConfigurationError("Studio delivery requires the exact learner origin.")
    ttl = studio.service.playback_ttl
    port = SignedMediaDeliveryPort(
        signer=MediaSigner(
            _derive(settings.session_token_pepper.get_secret_value(), b"studio-video-url-v1")
        ),
        delivery_origin=origin,
        playback_ttl=ttl,
        range_policy=RangePolicy(
            mode=RangeMode.SINGLE if settings.media_allow_range_requests else RangeMode.DENY,
            max_bytes=studio.storage.max_object_bytes,
        ),
        allow_loopback_http=parsed.scheme == "http",
    )
    cors = MediaCorsPolicy((origin,))
    service = MediaService(
        storage=studio.storage,
        signer=studio.service.signer,
        webhook_secret=studio.service.webhook_secret,
        delivery_port=port,
        delivery_activity_resolver=resolve_catalog_activity,
        playback_ttl=ttl,
    )

    def binding_resolver(database: Session, tenant: UUID, row: object, version: object) -> object:
        binding = resolve_activity_media_binding_for_learning(database, tenant, row, version)
        if binding is not None:
            if (
                binding.program_scope == "global"
                and binding.program_owner_key == GLOBAL_CATALOG_OWNER_KEY
            ):
                return binding
            admitted_program = _upload_program(
                database, tenant, binding.asset_id, binding.version_id
            )
            if admitted_program is not None:
                # A known Studio upload never falls back into a different
                # store/signer when its course admission does not match.
                return (
                    binding if _matches_upload_program(binding, tenant, admitted_program) else None
                )
        prior = base.activity_media_resolver
        return prior(database, tenant, row, version) if prior else None

    async def descriptor_resolver(
        database: AsyncSession, actor: ActorContext, access: LearningAccessContext
    ) -> ActivityMediaDescriptorResponse:
        if actor.tenant_id is None:
            raise MediaForbidden("The learner media tenant is unavailable.")
        tenant = actor.tenant_id
        asset, version = access.activity.media_asset_id, access.activity.media_version_id
        admitted_program = None
        if asset is not None and version is not None:
            admitted_program = await database.run_sync(
                lambda db: _upload_program(db, tenant, asset, version)
            )
        if admitted_program is not None:
            if (
                access.activity.program_scope != "tenant"
                or access.activity.program_owner_key != tenant
                or admitted_program != access.activity.program_id
            ):
                return ActivityMediaDescriptorResponse(
                    state="unavailable", reason="activity_media_not_available"
                )
            return await service.resolve_activity_media_descriptor_for_learner(
                database, actor, access
            )
        if (
            getattr(access.activity, "program_scope", None) == "global"
            and access.activity.program_owner_key == GLOBAL_CATALOG_OWNER_KEY
        ):
            return await service.resolve_activity_media_descriptor_for_learner(
                database, actor, access
            )
        prior = base.media_descriptor_resolver
        if prior:
            return await cast(DescriptorResolver, prior)(database, actor, access)
        return ActivityMediaDescriptorResponse(
            state="unavailable", reason="activity_media_not_available"
        )

    return replace(
        base,
        # Keep the base service/port for avatar and technical-film operations.
        media_delivery=base.media_delivery or port,
        media_cors_policy=base.media_cors_policy or cors,
        activity_media_resolver=binding_resolver,
        media_descriptor_resolver=descriptor_resolver,
        authenticated_delivery_handler_factory=_StudioHandlerFactory(
            service,
            port,
            cors,
            base.authenticated_delivery_handler_factory,
            studio.storage.max_object_bytes,
        ),
    )


def compose_local_studio_video_delivery(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    """Connect an explicit local/test upload graph to normal learner delivery."""

    return _compose_studio_video_delivery(settings, base, filesystem_runtime=False)


def compose_filesystem_studio_video_delivery(
    settings: Settings, base: MediaRuntime
) -> MediaRuntime:
    """Connect the deployment filesystem graph to authenticated delivery."""

    return _compose_studio_video_delivery(settings, base, filesystem_runtime=True)


__all__ = [
    "compose_filesystem_studio_video_delivery",
    "compose_local_studio_video_delivery",
]
