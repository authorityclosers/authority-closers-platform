"""Release-owned public-film delivery through canonical learner authorization.

The two optional demonstration clips belong to an explicitly published tenant
course. This does not compose uploads, external providers or Watch completion.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import Activity
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.services import ActivityDefinition, LearningAccessContext
from ac_platform.media.api_contracts import ActivityMediaDescriptorResponse
from ac_platform.media.bindings import (
    ActivityMediaBindingSnapshot,
    resolve_activity_media_binding_for_learning,
)
from ac_platform.media.database_delivery_authorizer import DatabaseMediaDeliveryAuthorizer
from ac_platform.media.delivery import PrivateMediaDeliveryHandler
from ac_platform.media.errors import MediaConfigurationError, MediaForbidden
from ac_platform.media.policy import MediaCorsPolicy, RangePolicy, SignedMediaDeliveryPort
from ac_platform.media.public_film_import import public_film_catalog
from ac_platform.media.public_film_manifest import (
    MANIFEST_SHA256,
    load_verified_public_film_pack,
)
from ac_platform.media.runtime import MediaRuntime, _derive
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner


def compose_public_film_delivery(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    """No caller-supplied pack, inventory, catalog resolver or authority accepted."""
    # Repeat admission for callers using model_copy/construct rather than Settings
    # validation. All checks precede the immutable package's filesystem reads.
    try:
        settings._validate_public_films()
    except ValueError as error:
        raise MediaConfigurationError(
            "Public-film delivery configuration is unavailable."
        ) from error
    if (
        not settings.media_public_films_delivery_enabled
        or base.environment != settings.environment
        or base.provider_activation_verified
        or base.media_delivery is not None
        or settings.public_learner_tenant_id is None
        or settings.media_public_films_root is None
    ):
        raise MediaConfigurationError("Public-film delivery configuration is unavailable.")
    pack = load_verified_public_film_pack(
        environment=settings.environment,
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
        root=Path(settings.media_public_films_root),
        expected_manifest_sha256=MANIFEST_SHA256,
    )
    pack.require_scope(
        environment=settings.environment,
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
    )
    catalog = public_film_catalog(pack)
    clips = dict(zip(catalog.activity_ids, pack.clips, strict=True))
    origin = str(settings.public_app_url).rstrip("/")

    def activity_resolver(row: object, version: object) -> ActivityDefinition:
        if not catalog.matches_catalog(row, version):
            raise MediaForbidden("This activity is outside the published public-film package.")
        return resolve_catalog_activity(row, version)

    def binding_resolver(
        database: Session, tenant_id: UUID, row: object, version: object
    ) -> ActivityMediaBindingSnapshot | None:
        if (
            tenant_id != pack.tenant_id
            or not isinstance(row, Activity)
            or not catalog.matches_catalog(row, version)
            or row.id not in clips
        ):
            return None
        binding = resolve_activity_media_binding_for_learning(database, tenant_id, row, version)
        if binding is None:
            return None
        clip = clips[row.id]
        if (binding.asset_id, binding.version_id) != (clip.asset_id, clip.version_id):
            return None
        return binding

    ttl = timedelta(minutes=5)
    port = SignedMediaDeliveryPort(
        signer=MediaSigner(
            _derive(settings.session_token_pepper.get_secret_value(), b"public-film-url-v1")
        ),
        delivery_origin=origin,
        playback_ttl=ttl,
        range_policy=RangePolicy(max_bytes=128 * 1024**2),
    )
    cors = MediaCorsPolicy((origin,))
    service = MediaService(
        storage=pack.storage,
        signer=base.service.signer,
        webhook_secret=base.service.webhook_secret,
        delivery_port=port,
        delivery_activity_resolver=activity_resolver,
        playback_ttl=ttl,
        media_config=base.media_config,
    )

    async def descriptor_resolver(
        database: AsyncSession, actor: ActorContext, access: LearningAccessContext
    ) -> ActivityMediaDescriptorResponse:
        clip = clips.get(access.activity.id)
        if (
            actor.tenant_id != pack.tenant_id
            or access.tenant_id != pack.tenant_id
            or access.program_version_id != catalog.program_version_id
            or clip is None
            or (access.activity.media_asset_id, access.activity.media_version_id)
            != (clip.asset_id, clip.version_id)
        ):
            return await base.service.resolve_activity_media_descriptor_for_learner(
                database, actor, access
            )
        return await service.resolve_activity_media_descriptor_for_learner(database, actor, access)

    def handler_factory(database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        if actor.tenant_id != pack.tenant_id:
            raise MediaForbidden("The public-film tenant is unavailable.")
        return PrivateMediaDeliveryHandler(
            storage=pack.storage,
            signer=port.signer,
            delivery_port=port,
            max_object_bytes=128 * 1024**2,
            authorizer=DatabaseMediaDeliveryAuthorizer(
                database, actor, signer=service.signer, activity_resolver=activity_resolver
            ),
            cors_policy=cors,
        )

    return replace(
        base,
        service=service,
        media_delivery=port,
        media_cors_policy=cors,
        activity_media_resolver=binding_resolver,
        media_descriptor_resolver=descriptor_resolver,
        authenticated_delivery_handler_factory=handler_factory,
        playback_policy_resolver=None,
    )
