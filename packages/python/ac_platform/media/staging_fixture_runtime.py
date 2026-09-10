"""Narrow opt-in delivery for two reviewed public-film staging activities.

This is not an S3/provider approval, upload pipeline, or instructional playback
policy. Every byte is in the pinned read-only inventory; ordinary learning and
persisted browser-session/grant authorization still run on every byte request.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY, Activity, ProgramVersion
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
from ac_platform.media.runtime import MediaRuntime, _derive
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.media.staging_fixture_manifest import (
    MANIFEST_SHA256,
    VerifiedStagingFixturePack,
    load_verified_staging_fixture_pack,
)
from ac_platform.seed.application import _stable_id
from ac_platform.seed.technical_media_fixture_v2 import (
    technical_media_identity,
    technical_media_seed,
)


def compose_staging_fixture_delivery(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    """Internal default composition; no caller-owned pack or resolver is accepted."""
    if (
        not settings.media_staging_public_films_delivery_enabled
        or not settings.media_stress_fixtures_enabled
        or settings.environment not in {"staging", "test"}
        or settings.public_learner_tenant_id is None
        or not settings.media_stress_fixtures_cache_root
        or settings.media_provider_enabled
        or base.environment != settings.environment
        or base.provider_activation_verified
        or base.media_delivery is not None
    ):
        raise MediaConfigurationError("staging public-film delivery configuration is unavailable")
    origin = str(settings.public_app_url).rstrip("/")
    if origin not in {
        "https://staging.authorityclosers.com",
        "https://learner-staging.authorityclosers.com",
    }:
        raise MediaConfigurationError("staging public films require the exact learner origin")
    pack = load_verified_staging_fixture_pack(
        environment=settings.environment,
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
        root=Path(settings.media_stress_fixtures_cache_root),
        expected_manifest_sha256=MANIFEST_SHA256,
    )
    pack.require_scope(
        environment=settings.environment,
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
    )
    return _compose_verified_delivery(settings, base, pack, origin)


def compose_local_fixture_delivery(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    """Explicit loopback sandbox, reusing the exact isolated-test film bytes.

    Does not accept live sessions, enrollments, source URLs or remote storage.
    Staging entrypoint and deployed provider gates remain unchanged.
    """
    origin = str(settings.public_app_url).rstrip("/")
    parsed = urlsplit(origin)
    if (
        settings.environment != "local"
        or base.environment != "local"
        or not settings.media_local_public_films_delivery_enabled
        or not settings.media_stress_fixtures_enabled
        or settings.media_staging_public_films_delivery_enabled
        or settings.media_provider_enabled
        or base.provider_activation_verified
        or base.media_delivery is not None
        or settings.public_learner_tenant_id is None
        or not settings.media_stress_fixtures_cache_root
        or parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "learner.localhost"}
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise MediaConfigurationError("local public films require the explicit loopback sandbox")
    pack = load_verified_staging_fixture_pack(
        environment="test",
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
        root=Path(settings.media_stress_fixtures_cache_root),
        expected_manifest_sha256=MANIFEST_SHA256,
    )
    pack.require_scope(
        environment="test",
        release_id=settings.release_id,
        tenant_id=settings.public_learner_tenant_id,
    )
    return _compose_verified_delivery(settings, base, pack, origin, local=True)


def _compose_verified_delivery(
    settings: Settings,
    base: MediaRuntime,
    pack: VerifiedStagingFixturePack,
    origin: str,
    *,
    local: bool = False,
) -> MediaRuntime:
    program_id, version_id, _, activity_ids = technical_media_identity(settings.release_id)
    seed = technical_media_seed(settings.release_id)
    clips = dict(zip(activity_ids, pack.clips, strict=True))
    # Access evaluation loads the complete prerequisite graph, not only the
    # requested video. Resolve exact package metadata for that graph while
    # keeping all actual media binding/delivery limited to the two film clips.
    catalog_entries = {
        _stable_id("activity", f"{seed.content_digest}:{module.position}:{activity.position}"): (
            _stable_id("module", f"{seed.content_digest}:{module.position}"),
            activity,
        )
        for module in seed.modules
        for activity in module.activities
    }

    def matching_catalog(row: object, version: object) -> bool:
        if not isinstance(row, Activity) or not isinstance(version, ProgramVersion):
            return False
        entry = catalog_entries.get(row.id)
        if entry is None:
            return False
        module_id, expected_activity = entry
        return (
            row.program_id == version.program_id == program_id
            and row.program_version_id == version.id == version_id
            and row.module_id == module_id
            and row.scope == version.scope == "global"
            and row.owner_key == version.owner_key == GLOBAL_CATALOG_OWNER_KEY
            and row.tenant_id is None
            and version.tenant_id is None
            and row.kind == expected_activity.kind
            and row.title == expected_activity.title
            and row.prompt == expected_activity.prompt
            and row.position == expected_activity.position
            and row.is_required == expected_activity.is_required
            and version.content_digest == seed.content_digest
            and version.content_source_ref == seed.source_ref
            and version.content_seed_kind == "technical-validation"
        )

    def activity_resolver(row: object, version: object) -> ActivityDefinition:
        if not matching_catalog(row, version):
            raise MediaForbidden("This activity is outside the staging public-film package.")
        return resolve_catalog_activity(row, version)

    def binding_resolver(
        database: Session, tenant_id: UUID, row: object, version: object
    ) -> ActivityMediaBindingSnapshot | None:
        if (
            tenant_id != pack.tenant_id
            or not matching_catalog(row, version)
            or not isinstance(row, Activity)
            or row.id not in clips
        ):
            return None
        binding = resolve_activity_media_binding_for_learning(database, tenant_id, row, version)
        if binding is None:
            return None
        clip = clips[binding.activity_id]
        if (binding.asset_id, binding.version_id) != (clip.asset_id, clip.version_id):
            return None
        return binding

    ttl = timedelta(minutes=5)
    port = SignedMediaDeliveryPort(
        signer=MediaSigner(
            _derive(settings.session_token_pepper.get_secret_value(), b"staging-film-url-v1")
        ),
        delivery_origin=origin,
        playback_ttl=ttl,
        range_policy=RangePolicy(max_bytes=128 * 1024**2),
        allow_loopback_http=local,
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
            or access.program_version_id != version_id
            or clip is None
            or (access.activity.media_asset_id, access.activity.media_version_id)
            != (clip.asset_id, clip.version_id)
        ):
            # Other courses retain their normal inert metadata and never receive
            # this fixture-only port or a persisted delivery grant.
            return await base.service.resolve_activity_media_descriptor_for_learner(
                database, actor, access
            )
        return await service.resolve_activity_media_descriptor_for_learner(database, actor, access)

    def handler_factory(database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        if actor.tenant_id != pack.tenant_id:
            raise MediaForbidden("The staging public-film tenant is unavailable.")
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
        # Serving a clip cannot grant official Watch completion or evidence.
        playback_policy_resolver=None,
    )
