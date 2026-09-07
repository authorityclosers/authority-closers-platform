"""Transactional media lifecycle commands over the existing SQL boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaBindingResponse,
    ActivityMediaDescriptorResponse,
    AvatarVariantResponse,
    CaptionCreateRequest,
    CaptionResponse,
    HeartbeatResponse,
    MediaAssetResponse,
    MediaDeliveryResponse,
    MediaHeartbeatRequest,
    MediaVersionResponse,
    PlaybackRequest,
    PlaybackResponse,
    ProfileAvatarResponse,
    ProfileAvatarVersionResponse,
    RenditionResponse,
    ResumeResponse,
    RetireResponse,
    UploadCompleteRequest,
    UploadIntentRequest,
    UploadIntentResponse,
    VideoWebhookRequest,
)
from ac_platform.media.bindings import (
    ActivityMediaBindingSnapshot,
    binding_response,
    resolve_activity_media_binding,
    resolve_activity_media_binding_for_learning,
)
from ac_platform.media.config import MediaProviderActivationVerifier, MediaProviderConfig
from ac_platform.media.contracts import (
    EphemeralMediaUrl,
    MediaAssetId,
    MediaAssetVersion,
    MediaVersionId,
    create_media_authorization_context,
)
from ac_platform.media.database_delivery_authorizer import (
    DeliveryActivityResolver,
    activity_delivery_fingerprint,
    activity_delivery_scope,
    grant_token,
    require_activity_delivery_access,
)
from ac_platform.media.errors import (
    MediaBadRequest,
    MediaConfigurationError,
    MediaConflict,
    MediaForbidden,
    MediaNotFound,
    MediaProcessingError,
    MediaQuotaExceeded,
    MediaScannerUnavailable,
    MediaStorageUnavailable,
)
from ac_platform.media.lifecycle import (
    MediaLifecycleHooks,
    MediaObjectReference,
    MediaRetentionPolicy,
    NoopMediaLifecycleHooks,
)
from ac_platform.media.models import (
    ActivityMediaBinding,
    CaptionKind,
    CaptionState,
    DeliveryProtocol,
    MediaAsset,
    MediaBindingState,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPlaybackGrant,
    MediaPurpose,
    MediaQuotaUsage,
    MediaRendition,
    MediaResumeState,
    MediaUploadIntent,
    MediaVersion,
    MediaWebhookInbox,
)
from ac_platform.media.policy import PersistedMediaGrantScope, SignedMediaDeliveryPort
from ac_platform.media.processing import (
    FailClosedProcessor,
    MediaProcessor,
    ProcessedCaption,
    ProcessingQuota,
    inspect_hls_playlist_inventory,
)
from ac_platform.media.scanner import ContentScanner, FailClosedScanner
from ac_platform.media.signing import MediaSigner
from ac_platform.media.storage import (
    PrivateObjectStorage,
    StorageUploadIntent,
    StoredObjectMetadata,
)

if TYPE_CHECKING:
    from ac_platform.learning.services import LearningAccessContext
    from ac_platform.media.staging_fixture_manifest import VerifiedStagingFixturePack

_CONTENT_TYPES: dict[MediaPurpose, frozenset[str]] = {
    MediaPurpose.AVATAR: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaPurpose.IMAGE: frozenset({"image/jpeg", "image/png", "image/webp"}),
    MediaPurpose.VIDEO: frozenset({"video/mp4", "video/webm"}),
    MediaPurpose.RESOURCE: frozenset({"application/pdf", "application/zip", "text/plain"}),
    MediaPurpose.CAPTIONS: frozenset({"text/vtt", "application/json", "text/plain"}),
    MediaPurpose.TRANSCRIPT: frozenset({"application/json", "text/plain", "text/vtt"}),
}
_RENDITION_CONTENT_TYPES: dict[DeliveryProtocol, frozenset[str]] = {
    DeliveryProtocol.HLS: frozenset({"application/vnd.apple.mpegurl", "application/x-mpegurl"}),
    DeliveryProtocol.PROGRESSIVE: frozenset({"video/mp4", "video/webm"}),
}
MediaPlaybackAuthorizer = Callable[[Session, ActorContext, MediaAsset], bool]
_FAILURE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_WEBHOOK_TIMESTAMP_TOLERANCE = timedelta(minutes=5)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_measured_duration(value: object | None, *, maximum: int) -> float:
    """Return a finite bounded duration required by READY video state."""

    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise MediaConflict("A ready video requires a validated measured duration.")
    if value > maximum:
        raise MediaQuotaExceeded("The media duration exceeds the processing quota.")
    return float(value)


class _BoundedMediaHeadReader:
    """Bound storage metadata reads during one untrusted processing attempt."""

    def __init__(self, storage: PrivateObjectStorage, maximum: int) -> None:
        self._storage = storage
        self._maximum = maximum
        self._used = 0
        self.seen: dict[str, StoredObjectMetadata | None] = {}

    def head(self, object_key: str) -> StoredObjectMetadata | None:
        if self._used >= self._maximum:
            raise MediaQuotaExceeded("The media processing head-operation quota was exceeded.")
        self._used += 1
        try:
            result = self._storage.head(object_key)
            self.seen[object_key] = result
            return result
        except MediaStorageUnavailable:
            raise
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media storage adapter could not inspect media output."
            ) from error


class MediaService:
    """Own media object/version state while leaving learning progress canonical."""

    def __init__(
        self,
        *,
        storage: PrivateObjectStorage,
        signer: MediaSigner,
        webhook_secret: bytes | str,
        scanner: ContentScanner | None = None,
        processor: MediaProcessor | None = None,
        playback_authorizer: MediaPlaybackAuthorizer | None = None,
        upload_ttl: timedelta = timedelta(minutes=15),
        playback_ttl: timedelta = timedelta(minutes=15),
        max_upload_bytes: int = 512 * 1024 * 1024,
        quota_window: timedelta = timedelta(hours=1),
        quota_bytes_per_actor: int = 2 * 1024 * 1024 * 1024,
        quota_uploads_per_actor: int = 100,
        lifecycle_hooks: MediaLifecycleHooks | None = None,
        retention_policy: MediaRetentionPolicy | None = None,
        processing_quota: ProcessingQuota | None = None,
        delivery_port: SignedMediaDeliveryPort | None = None,
        delivery_activity_resolver: DeliveryActivityResolver | None = None,
        media_config: MediaProviderConfig | None = None,
        activation_verifier: MediaProviderActivationVerifier | None = None,
    ) -> None:
        self.storage = storage
        self.signer = signer
        self.webhook_secret = (
            webhook_secret.encode("utf-8")
            if isinstance(webhook_secret, str)
            else bytes(webhook_secret)
        )
        if len(self.webhook_secret) < 32:
            raise ValueError("media webhook secret must be at least 32 bytes")
        self.scanner = scanner or FailClosedScanner()
        self.processor = processor or FailClosedProcessor()
        self.playback_authorizer = playback_authorizer
        self.upload_ttl = upload_ttl
        self.playback_ttl = playback_ttl
        self.max_upload_bytes = max_upload_bytes
        self.quota_window = quota_window
        self.quota_bytes_per_actor = quota_bytes_per_actor
        self.quota_uploads_per_actor = quota_uploads_per_actor
        self.lifecycle_hooks = lifecycle_hooks or NoopMediaLifecycleHooks()
        self.retention_policy = retention_policy
        self.processing_quota = processing_quota or ProcessingQuota()
        self.media_config = media_config
        self.activation_verifier = activation_verifier
        # A signed URL issuer is not an application delivery handler. Keep
        # playback unavailable unless the caller explicitly composes the
        # reviewed app route/session/grant/CORS/range boundary.
        self.delivery_port = delivery_port
        # Separate explicit composition from ordinary owner-media playback.
        # Merely injecting a signer does not activate learner delivery.
        self.delivery_activity_resolver = delivery_activity_resolver

    def _provider_activation_verified(self) -> bool:
        """Permit the legacy verifier seam only for local/test contract tests.

        The deployed application never reaches this branch: provider webhooks
        are unmounted and non-local composition rejects activation settings.
        """

        return (
            self.media_config is not None
            and self.media_config.environment in {"local", "test"}
            and self.media_config.activation_verified(self.activation_verifier)
        )

    def register_verified_staging_fixture_source(
        self,
        database: Session,
        actor: ActorContext,
        pack: VerifiedStagingFixturePack,
        fixture_id: str,
        *,
        environment: str,
        release_id: str,
    ) -> MediaVersion:
        """Register only a sealed test-package source, never caller-declared READY.

        The owning import application supplies the transaction and audit. The
        ordinary upload/provider paths and their gates remain unchanged.
        """
        from ac_platform.identity.models import Person
        from ac_platform.media.staging_fixture_manifest import VerifiedStagingFixturePack
        from ac_platform.tenancy.models import Membership, Tenant

        if not isinstance(pack, VerifiedStagingFixturePack):
            raise MediaForbidden("A verified staging fixture package is required.")
        tenant_id = self._tenant(actor)
        pack.require_scope(environment=environment, release_id=release_id, tenant_id=tenant_id)
        if self.storage is not pack.storage:
            raise MediaForbidden("The verified fixture storage is not composed.")
        authorized = database.scalar(
            select(Membership)
            .join(Person, Person.id == Membership.person_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == actor.person_id,
                Membership.role.in_(("admin", "owner")),
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Person.status == "active",
                Tenant.status == "active",
            )
            .with_for_update()
        )
        if authorized is None:
            raise MediaForbidden("Persisted tenant administrator authority is required.")
        clip = next((item for item in pack.clips if item.spec.fixture_id == fixture_id), None)
        if clip is None:
            raise MediaForbidden("The staging fixture is outside the approved package.")
        expected = next(
            item for item in clip.spec.objects if item.path == clip.spec.progressive_path
        )
        head = self.storage.head(clip.source_key)
        if head is None or (
            head.content_length != expected.content_length
            or head.content_type != "video/mp4"
            or head.checksum_sha256 != expected.sha256
        ):
            raise MediaForbidden("The verified staging source bytes changed.")
        scan = self.scanner.scan(
            storage=self.storage,
            object_key=clip.source_key,
            declared_content_type="video/mp4",
            content_length=head.content_length,
            checksum_sha256=head.checksum_sha256,
        )
        if not scan.clean or scan.verified_checksum_sha256 != expected.sha256:
            raise MediaForbidden("The verified staging source inspection is unavailable.")
        existing = database.scalar(
            select(MediaVersion).where(MediaVersion.id == clip.version_id).with_for_update()
        )
        asset = database.scalar(
            select(MediaAsset).where(MediaAsset.id == clip.asset_id).with_for_update()
        )
        if existing is not None or asset is not None:
            if (
                existing is None
                or asset is None
                or (
                    asset.tenant_id != tenant_id
                    or asset.owner_person_id != actor.person_id
                    or asset.purpose != "video"
                    or asset.state == MediaLifecycle.RETIRED.value
                    or existing.tenant_id != tenant_id
                    or existing.asset_id != asset.id
                    or existing.object_key != clip.source_key
                    or existing.checksum_sha256 != expected.sha256
                    or existing.actual_bytes != expected.content_length
                    or existing.content_type != "video/mp4"
                    or existing.state
                    not in {MediaLifecycle.PROCESSING.value, MediaLifecycle.READY.value}
                )
            ):
                raise MediaConflict("The deterministic fixture identity is occupied or changed.")
            return existing
        now = self._now()
        asset = MediaAsset(
            id=clip.asset_id,
            tenant_id=tenant_id,
            owner_person_id=actor.person_id,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.PROCESSING.value,
            created_at=now,
            updated_at=now,
        )
        database.add(asset)
        database.flush()
        version = MediaVersion(
            id=clip.version_id,
            tenant_id=tenant_id,
            asset_id=asset.id,
            version_number=1,
            purpose=MediaPurpose.VIDEO.value,
            state=MediaLifecycle.PROCESSING.value,
            content_type="video/mp4",
            declared_bytes=expected.content_length,
            actual_bytes=expected.content_length,
            checksum_sha256=expected.sha256,
            object_key=clip.source_key,
            storage_version_id=head.storage_version_id,
            created_at=now,
            updated_at=now,
        )
        database.add(version)
        database.flush()
        return version

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _fingerprint(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _safe_failure_code(value: str | None, *, fallback: str) -> str:
        return value if value and _FAILURE_CODE.fullmatch(value) else fallback

    @staticmethod
    def _secure_media_url(value: str, *, description: str) -> str:
        try:
            return EphemeralMediaUrl(value).value
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                f"The private media adapter returned an invalid {description} URL."
            ) from error

    def _signed_delivery_url(
        self,
        *,
        actor: ActorContext,
        asset: MediaAsset,
        version: MediaVersion,
        object_key: str,
        expires_at: datetime,
        kind: str,
        supports_range: bool,
        session_id: UUID | str | None = None,
    ) -> str:
        """Issue only an application-route URL, never a provider URL."""

        if self.delivery_port is None:
            raise MediaConflict("Media delivery is not composed for this runtime.")
        authorization = create_media_authorization_context(
            tenant_id=str(self._tenant(actor)),
            person_id=str(actor.person_id),
            session_id=str(session_id or actor.session_id),
        )
        signed = self.delivery_port.issue(
            authorization=authorization,
            activity_id=f"media-asset-{asset.id}",
            activity_version=f"media-version-{version.id}",
            media_version=MediaAssetVersion(
                MediaAssetId(str(asset.id)),
                MediaVersionId(str(version.id)),
            ),
            object_key=object_key,
            now=expires_at - self.delivery_port.playback_ttl,
            kind=kind,
            supports_range=supports_range,
        )
        return self._secure_media_url(signed.url.value, description="signed media delivery")

    @staticmethod
    def _tenant(actor: ActorContext) -> UUID:
        if actor.tenant_id is None:
            raise MediaForbidden("An active tenant context is required for media operations.")
        return actor.tenant_id

    @staticmethod
    def _manager(actor: ActorContext) -> bool:
        # Content authoring is the existing server-owned capability for media
        # that is not a self-owned profile avatar.
        return "catalog_write" in actor.permissions

    def _require_read(self, actor: ActorContext, asset: MediaAsset) -> None:
        tenant_id = self._tenant(actor)
        if asset.tenant_id != tenant_id:
            raise MediaForbidden("The media resource is outside the active tenant context.")
        if asset.owner_person_id != actor.person_id and not self._manager(actor):
            raise MediaForbidden("The actor is not authorized to read this media.")

    def _require_playback(self, database: Session, actor: ActorContext, asset: MediaAsset) -> None:
        self._require_read(actor, asset)
        if asset.owner_person_id == actor.person_id:
            return
        if self.playback_authorizer is None or not self.playback_authorizer(database, actor, asset):
            raise MediaForbidden(
                "An explicit learning-scope authorization is required for playback."
            )

    def _require_write(
        self, actor: ActorContext, *, purpose: MediaPurpose, asset: MediaAsset | None
    ) -> None:
        tenant_id = self._tenant(actor)
        if asset is not None and asset.tenant_id != tenant_id:
            raise MediaForbidden("The media resource is outside the active tenant context.")
        if purpose is MediaPurpose.AVATAR and (
            asset is None or asset.owner_person_id == actor.person_id
        ):
            return
        if not self._manager(actor):
            raise MediaForbidden("The actor is not authorized to write this media.")

    def resolve_activity_media_binding_for_learning(
        self,
        database: Session,
        tenant_id: UUID,
        catalog_activity: object,
        catalog_version: object,
    ) -> ActivityMediaBindingSnapshot | None:
        """Resolve a ready approved binding for an already selected activity.

        Learning access is still established by ``SqlAlchemyLearningRepository``;
        this callback only enriches that trusted scope with media identity and
        duration.  It never resolves by activity id alone.
        """

        if str(getattr(catalog_activity, "kind", "")).upper() != MediaPurpose.VIDEO.name:
            return None
        return resolve_activity_media_binding_for_learning(
            database, tenant_id, catalog_activity, catalog_version
        )

    def bind_activity_media(
        self,
        database: Session,
        actor: ActorContext,
        request: ActivityMediaBindingRequest,
        *,
        idempotency_key: str,
    ) -> ActivityMediaBindingResponse:
        """Append a human-approved, tenant-scoped activity/media binding.

        The command can only reference a ready application-owned video version
        and a published immutable catalog activity.  Supersession is explicit
        and historical rows are retained.
        """

        if not idempotency_key or len(idempotency_key) > 128:
            raise MediaBadRequest(
                "A bounded Idempotency-Key is required for activity media bindings."
            )
        if not self._manager(actor):
            raise MediaForbidden("The actor is not authorized to approve activity media.")
        tenant_id = self._tenant(actor)

        from ac_platform.catalog.models import Activity as CatalogActivity
        from ac_platform.catalog.models import ProgramVersion as CatalogProgramVersion

        activity = database.scalar(
            select(CatalogActivity)
            .where(CatalogActivity.id == request.activity_id)
            .with_for_update()
        )
        if activity is None:
            raise MediaNotFound("The learning activity was not found.")
        requested_activity_scope = (
            request.activity_id,
            request.module_id,
            request.program_version_id,
            request.program_id,
            request.program_scope,
            request.program_owner_key,
        )
        actual_activity_scope = (
            activity.id,
            activity.module_id,
            activity.program_version_id,
            activity.program_id,
            activity.scope,
            activity.owner_key,
        )
        if requested_activity_scope != actual_activity_scope:
            raise MediaForbidden("The activity scope does not match the server catalog row.")
        if activity.scope == "tenant" and activity.tenant_id != tenant_id:
            raise MediaForbidden("The activity is outside the active tenant context.")
        if str(activity.kind).upper() != MediaPurpose.VIDEO.name:
            raise MediaBadRequest("Only video activities can receive lesson media.")
        catalog_version = database.scalar(
            select(CatalogProgramVersion).where(
                CatalogProgramVersion.id == activity.program_version_id,
                CatalogProgramVersion.program_id == activity.program_id,
                CatalogProgramVersion.scope == activity.scope,
                CatalogProgramVersion.owner_key == activity.owner_key,
            )
        )
        if catalog_version is None or catalog_version.status not in {"published", "superseded"}:
            raise MediaConflict("Only published catalog activities can receive approved media.")

        asset = self._asset(database, actor, request.asset_id, lock=True)
        self._require_write(actor, purpose=MediaPurpose.VIDEO, asset=asset)
        if asset.purpose != MediaPurpose.VIDEO.value or asset.state == MediaLifecycle.RETIRED.value:
            raise MediaConflict("Only active video media can be approved for an activity.")
        version = database.scalar(
            select(MediaVersion)
            .where(
                MediaVersion.tenant_id == tenant_id,
                MediaVersion.asset_id == asset.id,
                MediaVersion.id == request.version_id,
            )
            .with_for_update()
        )
        if version is None:
            raise MediaNotFound("The media version was not found.")
        if (
            version.purpose != MediaPurpose.VIDEO.value
            or version.state != MediaLifecycle.READY.value
        ):
            raise MediaConflict("Only a ready video version can be approved for an activity.")

        activity_version = request.activity_version or f"activity:{activity.id}"
        fingerprint = self._fingerprint(
            {
                "activity_id": str(activity.id),
                "module_id": str(activity.module_id),
                "program_version_id": str(activity.program_version_id),
                "program_id": str(activity.program_id),
                "program_scope": activity.scope,
                "program_owner_key": str(activity.owner_key),
                "asset_id": str(asset.id),
                "version_id": str(version.id),
                "activity_version": activity_version,
                "approval_reference": request.approval_reference,
                "supersedes_binding_id": (
                    str(request.supersedes_binding_id)
                    if request.supersedes_binding_id is not None
                    else None
                ),
            }
        )
        existing = database.scalar(
            select(ActivityMediaBinding)
            .where(
                ActivityMediaBinding.tenant_id == tenant_id,
                ActivityMediaBinding.approved_by_person_id == actor.person_id,
                ActivityMediaBinding.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise MediaConflict(
                    "The activity media idempotency key was reused with different data."
                )
            return binding_response(existing)

        current = database.scalar(
            select(ActivityMediaBinding)
            .where(
                ActivityMediaBinding.tenant_id == tenant_id,
                ActivityMediaBinding.activity_id == activity.id,
                ActivityMediaBinding.module_id == activity.module_id,
                ActivityMediaBinding.program_version_id == activity.program_version_id,
                ActivityMediaBinding.program_id == activity.program_id,
                ActivityMediaBinding.program_scope == activity.scope,
                ActivityMediaBinding.program_owner_key == activity.owner_key,
                ActivityMediaBinding.state == MediaBindingState.APPROVED.value,
            )
            .with_for_update()
        )
        prior: ActivityMediaBinding | None = None
        if request.supersedes_binding_id is not None:
            prior = database.scalar(
                select(ActivityMediaBinding)
                .where(
                    ActivityMediaBinding.tenant_id == tenant_id,
                    ActivityMediaBinding.id == request.supersedes_binding_id,
                )
                .with_for_update()
            )
            if prior is None:
                raise MediaNotFound("The superseded activity media binding was not found.")
            prior_scope = (
                prior.activity_id,
                prior.module_id,
                prior.program_version_id,
                prior.program_id,
                prior.program_scope,
                prior.program_owner_key,
            )
            if (
                prior_scope != actual_activity_scope
                or prior.state != MediaBindingState.APPROVED.value
            ):
                raise MediaConflict(
                    "The superseded binding is not the current approved activity media."
                )
            if current is None or current.id != prior.id:
                raise MediaConflict("The superseded binding is not the current activity media.")
        elif current is not None:
            raise MediaConflict(
                "An approved activity media binding already exists; supersession is explicit."
            )

        now = self._now()
        if prior is not None:
            prior.state = MediaBindingState.SUPERSEDED.value
            prior.superseded_at = now
            prior.updated_at = now
        binding = ActivityMediaBinding(
            tenant_id=tenant_id,
            activity_id=activity.id,
            module_id=activity.module_id,
            program_version_id=activity.program_version_id,
            program_id=activity.program_id,
            program_scope=activity.scope,
            program_owner_key=activity.owner_key,
            activity_version=activity_version,
            asset_id=asset.id,
            version_id=version.id,
            state=MediaBindingState.APPROVED.value,
            approval_reference=request.approval_reference,
            approved_by_person_id=actor.person_id,
            approved_at=now,
            supersedes_binding_id=prior.id if prior is not None else None,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            created_at=now,
            updated_at=now,
        )
        database.add(binding)
        try:
            database.flush()
        except IntegrityError as error:
            raise MediaConflict(
                "The activity media binding changed concurrently; retry the idempotent command."
            ) from error
        return binding_response(binding)

    def resolve_activity_media_descriptor_for_learner(
        self,
        database: Session,
        actor: ActorContext,
        access: LearningAccessContext,
    ) -> ActivityMediaDescriptorResponse:
        """Return safe media metadata after learning scope is already resolved."""

        activity = getattr(access, "activity", None)
        if (
            activity is None
            or str(getattr(activity, "kind", "")).upper() != MediaPurpose.VIDEO.name
        ):
            return ActivityMediaDescriptorResponse(
                state="unavailable",
                reason="activity_media_not_available",
            )
        tenant_id = self._tenant(actor)
        snapshot = resolve_activity_media_binding(
            database,
            tenant_id=tenant_id,
            activity_id=activity.id,
            module_id=activity.module_id,
            program_version_id=access.program_version_id,
            program_id=activity.program_id,
            program_scope=activity.program_scope,
            program_owner_key=activity.program_owner_key,
        )
        if snapshot is None:
            return ActivityMediaDescriptorResponse(
                state="unavailable",
                reason="approved_activity_media_binding_unavailable",
            )
        version = database.scalar(
            select(MediaVersion).where(
                MediaVersion.tenant_id == tenant_id,
                MediaVersion.asset_id == snapshot.asset_id,
                MediaVersion.id == snapshot.version_id,
            )
        )
        if version is None:
            return ActivityMediaDescriptorResponse(
                state="unavailable",
                reason="approved_media_version_unavailable",
            )
        projected = self._version_response(database, version, include_sources=False)
        descriptor = ActivityMediaDescriptorResponse(
            state="approved",
            reason="approved_media_delivery_not_composed",
            binding_id=snapshot.binding_id,
            media_id=snapshot.asset_id,
            media_version_id=snapshot.version_id,
            activity_version=snapshot.activity_version,
            content_type=snapshot.content_type,
            duration_seconds=snapshot.duration_seconds,
            width=snapshot.width,
            height=snapshot.height,
            renditions=projected.renditions if projected is not None else [],
            captions=projected.captions if projected is not None else [],
            delivery=None,
            playback_available=False,
        )
        if self.delivery_port is None or self.delivery_activity_resolver is None:
            return descriptor
        if access.actor != actor or access.person_id != actor.person_id:
            raise MediaForbidden("The activity delivery actor is unavailable.")
        now = self._now().replace(microsecond=0)
        require_activity_delivery_access(
            database,
            actor,
            snapshot,
            access.enrollment_id,
            activity_resolver=self.delivery_activity_resolver,
            now=now,
        )
        rows = database.scalars(
            select(MediaRendition)
            .where(
                MediaRendition.tenant_id == tenant_id,
                MediaRendition.asset_id == snapshot.asset_id,
                MediaRendition.version_id == snapshot.version_id,
            )
            .order_by(MediaRendition.bitrate_kbps.desc(), MediaRendition.id)
        ).all()
        hls = next((row for row in rows if row.protocol == DeliveryProtocol.HLS.value), None)
        progressive = next(
            (row for row in rows if row.protocol == DeliveryProtocol.PROGRESSIVE.value), None
        )
        if hls is None and progressive is None:
            return descriptor.model_copy(
                update={"state": "blocked", "reason": "approved_media_rendition_unavailable"}
            )
        fingerprint = activity_delivery_fingerprint(
            activity_delivery_scope(actor, snapshot, access.enrollment_id)
        )
        grant = database.scalar(
            select(MediaPlaybackGrant)
            .where(
                MediaPlaybackGrant.tenant_id == tenant_id,
                MediaPlaybackGrant.actor_person_id == actor.person_id,
                MediaPlaybackGrant.request_fingerprint == fingerprint,
                MediaPlaybackGrant.revoked_at.is_(None),
                MediaPlaybackGrant.expires_at > now,
            )
            .order_by(MediaPlaybackGrant.created_at.desc())
            .limit(1)
        )
        if grant is None:
            grant_id = uuid4()
            grant = MediaPlaybackGrant(
                id=grant_id,
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                session_id=uuid4(),
                asset_id=snapshot.asset_id,
                version_id=snapshot.version_id,
                token_nonce=uuid4().hex,
                created_at=now,
                expires_at=now + self.delivery_port.playback_ttl,
                idempotency_key=f"activity-delivery:{grant_id}",
                request_fingerprint=fingerprint,
            )
            grant.token_digest = self.signer.digest(grant_token(grant, self.signer))
            database.add(grant)
            database.flush()
        elif not hmac.compare_digest(
            grant.token_digest, self.signer.digest(grant_token(grant, self.signer))
        ):
            raise MediaForbidden("The activity delivery grant is unavailable.")
        authorized = snapshot.as_authorized_media_version(actor)
        grant_scope = PersistedMediaGrantScope(grant.id, access.enrollment_id, snapshot.binding_id)

        def signed_url(key: str, *, supports_range: bool) -> str:
            # All derivatives share the original grant window, not a refreshed
            # TTL. Actual byte requests must use the authenticated DB authorizer.
            return self.delivery_port.issue(  # type: ignore[union-attr]
                authorization=authorized.authorization,
                activity_id=authorized.activity_id,
                activity_version=authorized.activity_version,
                media_version=authorized.media_version,
                object_key=key,
                now=_as_utc(grant.created_at),
                supports_range=supports_range,
                grant_scope=grant_scope,
            ).url.value

        captions = database.scalars(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == tenant_id,
                MediaCaptionTrack.version_id == snapshot.version_id,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
            .order_by(MediaCaptionTrack.id)
        ).all()
        return descriptor.model_copy(
            update={
                "reason": "approved_media_delivery_available",
                "playback_available": True,
                "delivery": MediaDeliveryResponse(
                    protocol=DeliveryProtocol.HLS
                    if hls is not None
                    else DeliveryProtocol.PROGRESSIVE,
                    manifest_url=signed_url(hls.object_key, supports_range=False) if hls else None,
                    progressive_url=signed_url(progressive.object_key, supports_range=True)
                    if progressive
                    else None,
                ),
                "captions": [
                    self._caption_response(
                        caption, include_source_url=False, expires_at=None
                    ).model_copy(
                        update={"source_url": signed_url(caption.object_key, supports_range=False)}
                    )
                    for caption in captions
                ],
            }
        )

    @staticmethod
    def _upload_key(
        tenant_id: UUID, purpose: MediaPurpose, asset_id: UUID, version_id: UUID
    ) -> str:
        return f"tenants/{tenant_id}/media/{purpose.value}/{asset_id}/{version_id}/original"

    @staticmethod
    def _child_key(version: MediaVersion, key: str) -> bool:
        prefix = f"tenants/{version.tenant_id}/media/"
        return (
            key.startswith(prefix)
            and key.startswith(version.object_key + "/")
            and ".." not in key
            and "\\" not in key
            and not any(character.isspace() for character in key)
            and all(ord(character) >= 0x20 and ord(character) != 0x7F for character in key)
        )

    @staticmethod
    def _object_reference(version: MediaVersion) -> MediaObjectReference:
        return MediaObjectReference(
            tenant_id=version.tenant_id,
            asset_id=version.asset_id,
            version_id=version.id,
            object_key=version.object_key,
        )

    def _version_object_references(
        self, database: Session, version: MediaVersion
    ) -> tuple[MediaObjectReference, ...]:
        """Return every private object owned by a version for retention hooks."""

        keys = [version.object_key]
        keys.extend(
            row.object_key
            for row in database.scalars(
                select(MediaRendition).where(
                    MediaRendition.tenant_id == version.tenant_id,
                    MediaRendition.version_id == version.id,
                )
            ).all()
        )
        keys.extend(
            row.object_key
            for row in database.scalars(
                select(MediaCaptionTrack).where(
                    MediaCaptionTrack.tenant_id == version.tenant_id,
                    MediaCaptionTrack.version_id == version.id,
                )
            ).all()
        )
        if isinstance(version.avatar_variants, list):
            keys.extend(
                str(item.get("object_key"))
                for item in version.avatar_variants
                if isinstance(item, dict) and item.get("object_key")
            )
        inventory_reader = getattr(self.lifecycle_hooks, "object_references", None)
        if callable(inventory_reader):
            try:
                tracked = inventory_reader(self._object_reference(version))
            except Exception as error:
                raise MediaStorageUnavailable(
                    "The media lifecycle inventory could not be read."
                ) from error
            keys.extend(
                item.object_key for item in tracked if isinstance(item, MediaObjectReference)
            )
        references: list[MediaObjectReference] = []
        seen: set[str] = set()
        for key in keys:
            if (
                not isinstance(key, str)
                or key in seen
                or not self._child_key(version, key)
                and key != version.object_key
            ):
                continue
            seen.add(key)
            references.append(
                MediaObjectReference(
                    tenant_id=version.tenant_id,
                    asset_id=version.asset_id,
                    version_id=version.id,
                    object_key=key,
                )
            )
        return tuple(references)

    def _record_cleanup_failure(
        self,
        reference: MediaObjectReference,
        *,
        object_keys: tuple[str, ...],
        reason_code: str,
    ) -> None:
        """Require a retryable lifecycle record when orphan cleanup fails."""

        recorder = getattr(self.lifecycle_hooks, "outputs_cleanup_failed", None)
        if not callable(recorder) or isinstance(self.lifecycle_hooks, NoopMediaLifecycleHooks):
            raise MediaStorageUnavailable(
                "The media output cleanup failed and no retryable lifecycle hook is composed."
            )
        try:
            recorder(reference, object_keys=object_keys, reason_code=reason_code)
        except Exception as error:
            raise MediaStorageUnavailable(
                "The media output cleanup failure could not be recorded for retry."
            ) from error

    def _cleanup_processor_outputs(
        self,
        result: object | None,
        *,
        version: MediaVersion,
        reason_code: str = "MEDIA_OUTPUT_CLEANUP_FAILED",
    ) -> None:
        """Clean failed output and record any orphan as a retryable event."""

        source_key = version.object_key
        object_keys = getattr(result, "object_keys", ()) if result is not None else ()
        known_keys = tuple(object_keys) if isinstance(object_keys, tuple | list) else ()
        listing_failed = False
        # A processor can fail after writing an object but before it returns a
        # ProcessingResult.  The per-version prefix is the only recoverable
        # inventory available at that point; use a bounded adapter listing so
        # those partial bytes do not become orphaned private media.
        try:
            listed = self.storage.list_prefix(source_key)
        except Exception:
            listed = ()
            listing_failed = True
        if isinstance(listed, tuple | list):
            known_keys = (*known_keys, *listed)
        candidates: list[str] = []
        for object_key in dict.fromkeys(known_keys):
            if not isinstance(object_key, str):
                continue
            if object_key == source_key:
                continue
            if (
                not object_key.startswith(source_key + "/")
                or ".." in object_key
                or "\\" in object_key
            ):
                continue
            candidates.append(object_key)
        failed_keys: list[str] = []
        for object_key in candidates:
            try:
                self.storage.delete(object_key)
            except Exception:
                failed_keys.append(object_key)
        if listing_failed or failed_keys:
            self._record_cleanup_failure(
                self._object_reference(version),
                object_keys=tuple(failed_keys or candidates),
                reason_code=("MEDIA_OUTPUT_CLEANUP_LIST_FAILED" if listing_failed else reason_code),
            )

    def _delete_object_best_effort(
        self,
        object_key: str,
        *,
        reference: MediaObjectReference,
    ) -> None:
        """Remove one new object or record its retryable cleanup event."""

        try:
            self.storage.delete(object_key)
        except Exception:
            self._record_cleanup_failure(
                reference,
                object_keys=(object_key,),
                reason_code="MEDIA_OBJECT_CLEANUP_FAILED",
            )

    def _asset(
        self, database: Session, actor: ActorContext, asset_id: UUID, *, lock: bool = False
    ) -> MediaAsset:
        statement = select(MediaAsset).where(
            MediaAsset.id == asset_id, MediaAsset.tenant_id == self._tenant(actor)
        )
        if lock:
            statement = statement.with_for_update()
        asset = database.scalar(statement)
        if asset is None:
            raise MediaNotFound("The media resource was not found.")
        return asset

    @staticmethod
    def _version(
        database: Session, actor: ActorContext, version_id: UUID, *, lock: bool = False
    ) -> MediaVersion:
        if actor.tenant_id is None:
            raise MediaForbidden("An active tenant context is required for media operations.")
        statement = select(MediaVersion).where(
            MediaVersion.id == version_id, MediaVersion.tenant_id == actor.tenant_id
        )
        if lock:
            statement = statement.with_for_update()
        version = database.scalar(statement)
        if version is None:
            raise MediaNotFound("The media version was not found.")
        return version

    def _reserve_quota(self, database: Session, actor: ActorContext, content_length: int) -> int:
        tenant_id = self._tenant(actor)
        now = self._now()
        seconds = int(self.quota_window.total_seconds())
        epoch = int(now.timestamp())
        window_start = datetime.fromtimestamp(epoch - (epoch % seconds), UTC)
        usage = database.scalar(
            select(MediaQuotaUsage)
            .where(
                MediaQuotaUsage.tenant_id == tenant_id,
                MediaQuotaUsage.actor_person_id == actor.person_id,
                MediaQuotaUsage.window_start == window_start,
            )
            .with_for_update()
        )
        if usage is None:
            usage = MediaQuotaUsage(
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                window_start=window_start,
                upload_count=0,
                bytes_reserved=0,
            )
            try:
                with database.begin_nested():
                    database.add(usage)
                    database.flush()
            except IntegrityError:
                usage = database.scalar(
                    select(MediaQuotaUsage)
                    .where(
                        MediaQuotaUsage.tenant_id == tenant_id,
                        MediaQuotaUsage.actor_person_id == actor.person_id,
                        MediaQuotaUsage.window_start == window_start,
                    )
                    .with_for_update()
                )
                if usage is None:
                    raise MediaConflict(
                        "The media quota changed concurrently; retry the command."
                    ) from None
        if (
            usage.upload_count >= self.quota_uploads_per_actor
            or usage.bytes_reserved + content_length > self.quota_bytes_per_actor
        ):
            raise MediaQuotaExceeded("The bounded media upload quota has been exceeded.")
        usage.upload_count += 1
        usage.bytes_reserved += content_length
        return min(content_length, self.max_upload_bytes)

    def create_upload_intent(
        self,
        database: Session,
        actor: ActorContext,
        request: UploadIntentRequest,
        *,
        idempotency_key: str,
    ) -> UploadIntentResponse:
        if not idempotency_key or len(idempotency_key) > 128:
            raise MediaBadRequest(
                "A bounded Idempotency-Key is required for media upload commands."
            )
        if request.content_length > self.max_upload_bytes:
            raise MediaQuotaExceeded("The media object exceeds the configured byte limit.")
        if request.content_type not in _CONTENT_TYPES[request.purpose]:
            raise MediaBadRequest("The media content type is not allowed for this purpose.")
        asset: MediaAsset | None = None
        if request.asset_id is not None:
            asset = self._asset(database, actor, request.asset_id, lock=True)
        elif request.purpose is MediaPurpose.AVATAR:
            asset = database.scalar(
                select(MediaAsset)
                .where(
                    MediaAsset.tenant_id == self._tenant(actor),
                    MediaAsset.owner_person_id == actor.person_id,
                    MediaAsset.purpose == MediaPurpose.AVATAR.value,
                    MediaAsset.state != MediaLifecycle.RETIRED.value,
                )
                .order_by(MediaAsset.updated_at.desc())
                .with_for_update()
            )
        self._require_write(actor, purpose=request.purpose, asset=asset)
        fingerprint = self._fingerprint(request.model_dump(mode="json"))
        existing = database.scalar(
            select(MediaUploadIntent)
            .where(
                MediaUploadIntent.tenant_id == self._tenant(actor),
                MediaUploadIntent.actor_person_id == actor.person_id,
                MediaUploadIntent.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise MediaConflict(
                    "The idempotency key was already used for a different media request."
                )
            version = self._version(database, actor, existing.version_id)
            return self._upload_response(existing, version)

        if asset is not None and asset.purpose != request.purpose.value:
            raise MediaConflict("A media asset cannot change purpose across versions.")
        if asset is None:
            asset = MediaAsset(
                tenant_id=self._tenant(actor),
                owner_person_id=actor.person_id,
                purpose=request.purpose.value,
                state=MediaLifecycle.UPLOADING.value,
            )
            database.add(asset)
            database.flush()
        supersedes_version_id = request.supersedes_version_id or asset.current_version_id
        if supersedes_version_id is not None:
            superseded = database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == supersedes_version_id,
                    MediaVersion.tenant_id == asset.tenant_id,
                    MediaVersion.asset_id == asset.id,
                )
            )
            if superseded is None:
                raise MediaConflict("The superseded version is not part of this media asset.")
        max_number = (
            database.scalar(
                select(func.max(MediaVersion.version_number)).where(
                    MediaVersion.asset_id == asset.id
                )
            )
            or 0
        )
        version_id = uuid4()
        version = MediaVersion(
            id=version_id,
            tenant_id=asset.tenant_id,
            asset_id=asset.id,
            version_number=max_number + 1,
            purpose=request.purpose.value,
            state=MediaLifecycle.UPLOADING.value,
            content_type=request.content_type,
            declared_bytes=request.content_length,
            checksum_sha256=request.checksum_sha256,
            object_key=self._upload_key(asset.tenant_id, request.purpose, asset.id, version_id),
            supersedes_version_id=supersedes_version_id,
            avatar_crop=request.crop.model_dump(mode="json") if request.crop else None,
        )
        max_bytes = self._reserve_quota(database, actor, request.content_length)
        expires_at = self._now() + self.upload_ttl
        try:
            upload_intent = self.storage.create_upload_intent(
                object_key=version.object_key,
                content_type=version.content_type,
                content_length=version.declared_bytes,
                checksum_sha256=version.checksum_sha256,
                expires_at=expires_at,
            )
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media storage adapter could not issue an upload intent."
            ) from error
        database.add(version)
        intent = MediaUploadIntent(
            tenant_id=asset.tenant_id,
            actor_person_id=actor.person_id,
            asset_id=asset.id,
            version_id=version.id,
            object_key=version.object_key,
            filename=request.filename,
            content_type=version.content_type,
            declared_bytes=version.declared_bytes,
            checksum_sha256=version.checksum_sha256,
            expires_at=expires_at,
            max_bytes=max_bytes,
            state=MediaLifecycle.UPLOADING.value,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            crop=version.avatar_crop,
        )
        asset.state = MediaLifecycle.UPLOADING.value
        database.add(intent)
        database.flush()
        return self._upload_response(intent, version, storage_intent=upload_intent)

    def _upload_response(
        self,
        intent: MediaUploadIntent,
        version: MediaVersion,
        *,
        storage_intent: StorageUploadIntent | None = None,
    ) -> UploadIntentResponse:
        if storage_intent is None:
            try:
                storage_intent = self.storage.create_upload_intent(
                    object_key=intent.object_key,
                    content_type=intent.content_type,
                    content_length=intent.declared_bytes,
                    checksum_sha256=intent.checksum_sha256,
                    expires_at=intent.expires_at,
                )
            except Exception as error:
                raise MediaStorageUnavailable(
                    "The private media storage adapter could not issue an upload intent."
                ) from error
        upload_url = self._secure_media_url(storage_intent.upload_url, description="upload")
        return UploadIntentResponse(
            upload_id=intent.id,
            media_id=intent.asset_id,
            media_version_id=intent.version_id,
            version_number=version.version_number,
            state=MediaLifecycle(intent.state),
            object_key=intent.object_key,
            upload_url=upload_url,
            upload_headers=storage_intent.headers,
            expires_at=intent.expires_at,
            max_bytes=intent.max_bytes,
        )

    def complete_upload(
        self,
        database: Session,
        actor: ActorContext,
        upload_id: UUID,
        request: UploadCompleteRequest,
        *,
        idempotency_key: str,
        expected_purpose: MediaPurpose | None = None,
    ) -> MediaAssetResponse:
        if not idempotency_key or len(idempotency_key) > 128:
            raise MediaBadRequest(
                "A bounded Idempotency-Key is required for media upload commands."
            )
        intent = database.scalar(
            select(MediaUploadIntent)
            .where(
                MediaUploadIntent.id == upload_id,
                MediaUploadIntent.tenant_id == self._tenant(actor),
            )
            .with_for_update()
        )
        if intent is None:
            raise MediaNotFound("The media upload intent was not found.")
        asset = self._asset(database, actor, intent.asset_id, lock=True)
        version = self._version(database, actor, intent.version_id, lock=True)
        if expected_purpose is not None and version.purpose != expected_purpose.value:
            raise MediaBadRequest("The upload intent does not match this media route.")
        self._require_write(actor, purpose=MediaPurpose(version.purpose), asset=asset)
        fingerprint = self._fingerprint(
            request.model_dump(mode="json") | {"idempotency_key": idempotency_key}
        )
        if intent.completion_fingerprint is not None:
            if intent.completion_fingerprint != fingerprint:
                raise MediaConflict(
                    "The upload completion idempotency key was reused with different data."
                )
            return self._asset_response(database, actor, asset)
        if intent.state != MediaLifecycle.UPLOADING.value:
            raise MediaConflict("The media upload is not in a completable state.")
        if self._now() >= _as_utc(intent.expires_at):
            raise MediaConflict("The media upload intent has expired.")
        if request.duration_seconds is not None and (
            not math.isfinite(request.duration_seconds)
            or request.duration_seconds > self.processing_quota.max_duration_seconds
        ):
            raise MediaQuotaExceeded("The media duration exceeds the processing quota.")
        try:
            head = self.storage.head(intent.object_key)
        except Exception as error:
            raise MediaStorageUnavailable(
                "The private media storage adapter could not inspect the upload."
            ) from error
        if head is None:
            raise MediaConflict("The uploaded media object was not found.")
        self._verify_uploaded_object(intent, version, head, request)
        try:
            scan = self.scanner.scan(
                storage=self.storage,
                object_key=intent.object_key,
                declared_content_type=intent.content_type,
                content_length=head.content_length,
                checksum_sha256=request.checksum_sha256
                or intent.checksum_sha256
                or head.checksum_sha256,
            )
        except MediaScannerUnavailable:
            raise
        except Exception as error:
            raise MediaScannerUnavailable(
                "The media safety scanner could not inspect the upload."
            ) from error
        expected_checksum = (
            request.checksum_sha256 or intent.checksum_sha256 or head.checksum_sha256
        )
        if not scan.clean:
            return self._mark_failed(
                database,
                actor,
                asset,
                version,
                intent,
                fingerprint,
                scan.reason_code or "MEDIA_CONTENT_REJECTED",
            )
        if (
            not scan.verified_checksum_sha256
            or expected_checksum.lower() != scan.verified_checksum_sha256.lower()
        ):
            return self._mark_failed(
                database,
                actor,
                asset,
                version,
                intent,
                fingerprint,
                "MEDIA_CONTENT_SCAN_UNVERIFIED",
            )
        now = self._now()
        version.actual_bytes = head.content_length
        version.checksum_sha256 = expected_checksum
        version.storage_version_id = head.storage_version_id
        # UploadCompleteRequest.duration_seconds is caller metadata only.  A
        # video can become READY only after an internal processor/inspector
        # measures its duration; never persist the client declaration as the
        # canonical duration used by playback and heartbeat.
        version.width = request.width
        version.height = request.height
        version.state = MediaLifecycle.PROCESSING.value
        version.updated_at = now
        intent.state = MediaLifecycle.PROCESSING.value
        intent.completion_fingerprint = fingerprint
        if asset.current_version_id is None:
            asset.state = MediaLifecycle.PROCESSING.value
        database.flush()
        return self._asset_response(database, actor, asset)

    @staticmethod
    def _verify_uploaded_object(
        intent: MediaUploadIntent,
        version: MediaVersion,
        head: StoredObjectMetadata,
        request: UploadCompleteRequest,
    ) -> None:
        actual_bytes = request.actual_bytes or head.content_length
        if actual_bytes != intent.declared_bytes or head.content_length != intent.declared_bytes:
            raise MediaConflict("The uploaded media size does not match the declared size.")
        expected = request.checksum_sha256 or intent.checksum_sha256
        if expected and (
            not head.checksum_sha256 or expected.lower() != head.checksum_sha256.lower()
        ):
            raise MediaConflict("The uploaded media checksum does not match the declared checksum.")
        if version.content_type != head.content_type.lower().split(";", 1)[0].strip():
            # MIME sniffing is performed by the scanner; this metadata check
            # prevents a provider from silently changing the upload contract.
            raise MediaConflict("The uploaded media content type does not match the upload intent.")
        if request.storage_version_id and request.storage_version_id != head.storage_version_id:
            raise MediaConflict("The storage object version does not match the completion request.")

    def _mark_failed(
        self,
        database: Session,
        actor: ActorContext,
        asset: MediaAsset,
        version: MediaVersion,
        intent: MediaUploadIntent,
        fingerprint: str,
        failure_code: str,
    ) -> MediaAssetResponse:
        now = self._now()
        version.state = MediaLifecycle.FAILED.value
        version.processing_error = self._safe_failure_code(
            failure_code, fallback="MEDIA_CONTENT_REJECTED"
        )
        version.updated_at = now
        intent.state = MediaLifecycle.FAILED.value
        intent.completion_fingerprint = fingerprint
        if asset.current_version_id is None:
            asset.state = MediaLifecycle.FAILED.value
        else:
            current = database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == asset.current_version_id,
                    MediaVersion.tenant_id == asset.tenant_id,
                )
            )
            asset.state = current.state if current is not None else MediaLifecycle.FAILED.value
        asset.updated_at = now
        database.flush()
        return self._asset_response(database, actor, asset)

    def _persist_processor_caption(
        self,
        database: Session,
        version: MediaVersion,
        caption: ProcessedCaption,
        *,
        head_reader: Callable[[str], StoredObjectMetadata | None] | None = None,
    ) -> int:
        """Persist processor-passthrough captions without replacing history."""

        read_head = head_reader or self.storage.head
        if not self._child_key(version, caption.object_key):
            raise MediaConflict("The media processor returned an out-of-scope caption.")
        if caption.source_object_key is None or caption.source_checksum_sha256 is None:
            raise MediaConflict("The media processor returned caption provenance without proof.")
        if not self._child_key(version, caption.source_object_key) and not (
            caption.source_object_key.startswith(f"tenants/{version.tenant_id}/")
        ):
            raise MediaConflict("The media caption source is outside the tenant scope.")
        source_head = read_head(caption.source_object_key)
        if (
            source_head is None
            or not source_head.checksum_sha256
            or not _SHA256.fullmatch(source_head.checksum_sha256)
            or source_head.checksum_sha256.lower() != caption.source_checksum_sha256.lower()
        ):
            raise MediaConflict("The media caption source checksum is unverified.")
        head = read_head(caption.object_key)
        if head is None:
            raise MediaConflict("The media processor returned an unavailable caption.")
        if head.content_type.lower().split(";", 1)[0].strip() != caption.content_type:
            raise MediaConflict("The media processor returned an unverified caption MIME.")
        if caption.content_length is None or caption.content_length != head.content_length:
            raise MediaConflict("The media processor returned an unverified caption size.")
        if (
            not head.checksum_sha256
            or not _SHA256.fullmatch(head.checksum_sha256)
            or head.checksum_sha256.lower() != caption.source_checksum_sha256.lower()
        ):
            raise MediaConflict("The media processor returned an unverified caption checksum.")
        try:
            scan = self.scanner.scan(
                storage=self.storage,
                object_key=caption.object_key,
                declared_content_type=caption.content_type,
                content_length=head.content_length,
                checksum_sha256=head.checksum_sha256,
            )
        except MediaScannerUnavailable:
            raise
        except Exception as error:
            raise MediaScannerUnavailable(
                "The media caption safety scanner could not inspect the output."
            ) from error
        if not scan.clean:
            if scan.reason_code == "SCANNER_NOT_CONFIGURED":
                raise MediaScannerUnavailable("The media caption safety scanner is not configured.")
            raise MediaConflict("The media processor returned an unsafe caption.")
        if (
            not scan.verified_checksum_sha256
            or scan.verified_checksum_sha256.lower() != head.checksum_sha256.lower()
        ):
            raise MediaConflict("The media caption safety scan did not verify its checksum.")
        caption_kind = CaptionKind(caption.kind).value
        existing = database.scalar(
            select(MediaCaptionTrack).where(
                MediaCaptionTrack.tenant_id == version.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.id == caption.id,
            )
        )
        if existing is not None:
            if existing.object_key != caption.object_key:
                raise MediaConflict("The media processor reused a caption identity.")
            return head.content_length
        prior = database.scalars(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == version.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.language == caption.language,
                MediaCaptionTrack.kind == caption_kind,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
            .order_by(MediaCaptionTrack.created_at.desc(), MediaCaptionTrack.id.desc())
            .with_for_update()
        ).all()
        for row in prior:
            row.state = CaptionState.SUPERSEDED.value
        database.add(
            MediaCaptionTrack(
                id=caption.id,
                tenant_id=version.tenant_id,
                version_id=version.id,
                language=caption.language,
                kind=caption_kind,
                state=CaptionState.READY.value,
                content_type=caption.content_type,
                object_key=caption.object_key,
                is_default=caption.is_default,
                supersedes_caption_id=caption.supersedes_caption_id
                or (prior[0].id if prior else None),
            )
        )
        return head.content_length

    def process_version(
        self, database: Session, actor: ActorContext, version_id: UUID
    ) -> MediaAssetResponse:
        version = self._version(database, actor, version_id, lock=True)
        asset = self._asset(database, actor, version.asset_id, lock=True)
        self._require_write(actor, purpose=MediaPurpose(version.purpose), asset=asset)
        if version.state != MediaLifecycle.PROCESSING.value:
            raise MediaConflict("The media version is not awaiting processing.")
        result = None
        head_budget = _BoundedMediaHeadReader(
            self.storage, self.processing_quota.max_head_operations
        )
        try:
            source_head = head_budget.head(version.object_key)
            if source_head is None:
                raise MediaConflict("The media source is unavailable for processing.")
            if (
                isinstance(source_head.content_length, bool)
                or not isinstance(source_head.content_length, int)
                or source_head.content_length <= 0
            ):
                raise MediaConflict("The media source size is unverified.")
            self.processing_quota.check_source(source_head.content_length)
            source_content_type = source_head.content_type.lower().split(";", 1)[0].strip()
            if source_content_type != version.content_type:
                raise MediaConflict("The media source MIME is unverified.")
            if (
                version.actual_bytes is not None
                and source_head.content_length != version.actual_bytes
            ):
                raise MediaConflict("The media source changed after upload completion.")
            if version.checksum_sha256 is not None and (
                not source_head.checksum_sha256
                or not _SHA256.fullmatch(source_head.checksum_sha256)
                or source_head.checksum_sha256.lower() != version.checksum_sha256.lower()
            ):
                raise MediaConflict("The media source checksum is unverified.")
            result = self.processor.process(
                storage=self.storage,
                version_id=version.id,
                purpose=MediaPurpose(version.purpose),
                source_key=version.object_key,
                content_type=version.content_type,
                crop=version.avatar_crop,
            )
            self.processing_quota.check_result(result)
            inventory = tuple(result.object_keys)
            required_objects = (
                {rendition.object_key for rendition in result.renditions}
                | {caption.object_key for caption in result.captions}
                | {variant.object_key for variant in result.avatar_variants}
            )
            if result.hls_manifest is not None:
                required_objects.update(result.hls_manifest.object_keys)
            if not required_objects.issubset(inventory):
                raise MediaConflict("The media processor returned an incomplete object inventory.")
            for object_key in inventory:
                if object_key == version.object_key:
                    continue
                if not self._child_key(version, object_key):
                    raise MediaConflict("The media processor returned an out-of-scope object.")
                head = head_budget.head(object_key)
                if head is None:
                    raise MediaConflict("The media processor returned an unavailable object.")
                if (
                    isinstance(head.content_length, bool)
                    or not isinstance(head.content_length, int)
                    or head.content_length <= 0
                ):
                    raise MediaConflict("The media processor returned an unverified object size.")
                if not head.checksum_sha256 or not _SHA256.fullmatch(head.checksum_sha256):
                    raise MediaConflict(
                        "The media processor returned an unverified object checksum."
                    )
                object_mime = head.content_type.lower().split(";", 1)[0].strip()
                hls_content_types = _RENDITION_CONTENT_TYPES[DeliveryProtocol.HLS]
                if object_key.lower().endswith(".m3u8") and object_mime not in hls_content_types:
                    raise MediaConflict("The media processor returned an unverified playlist.")
                if object_key.lower().endswith(".ts") and object_mime != "video/mp2t":
                    raise MediaConflict("The media processor returned an unverified segment.")
            output_bytes = 0
            for object_key in inventory:
                if object_key == version.object_key:
                    continue
                metadata = head_budget.seen.get(object_key)
                if metadata is None:
                    raise MediaConflict("The media processor returned an unverified object.")
                output_bytes += metadata.content_length
            if result.output_bytes is not None and result.output_bytes != output_bytes:
                raise MediaConflict("The media processor output byte count is unverified.")
            if output_bytes > self.processing_quota.max_output_bytes:
                raise MediaQuotaExceeded("The media output exceeds the processing quota.")
            for rendition in result.renditions:
                if rendition.protocol != DeliveryProtocol.HLS.value:
                    continue
                try:
                    discovered_objects = inspect_hls_playlist_inventory(
                        self.storage,
                        root_key=rendition.object_key,
                        namespace_prefix=version.object_key,
                        max_duration_seconds=self.processing_quota.max_duration_seconds,
                        max_head_operations=self.processing_quota.max_head_operations,
                        head_reader=head_budget.head,
                    )
                except MediaProcessingError as error:
                    raise MediaConflict(
                        "The media processor returned an invalid HLS object graph."
                    ) from error
                if not set(discovered_objects).issubset(inventory):
                    raise MediaConflict(
                        "The media processor returned an incomplete HLS object inventory."
                    )
            if result.hls_manifest is not None and result.hls_manifest.master_object_key not in {
                rendition.object_key
                for rendition in result.renditions
                if rendition.protocol == DeliveryProtocol.HLS.value
            }:
                raise MediaConflict(
                    "The media processor returned a manifest without a delivery rendition."
                )
            for rendition in result.renditions:
                try:
                    protocol = DeliveryProtocol(rendition.protocol)
                except ValueError as error:
                    raise MediaConflict(
                        "The media processor returned an unsupported protocol."
                    ) from error
                content_type = rendition.content_type.lower().split(";", 1)[0].strip()
                if content_type not in _RENDITION_CONTENT_TYPES[protocol]:
                    raise MediaConflict(
                        "The media processor returned an unsupported rendition content type."
                    )
                head = head_budget.head(rendition.object_key)
                if not self._child_key(version, rendition.object_key) or head is None:
                    raise MediaConflict("The media processor returned an unavailable rendition.")
                if head.content_type.lower().split(";", 1)[0].strip() != content_type:
                    raise MediaConflict(
                        "The media processor returned an unverified rendition content type."
                    )
                existing_rendition = database.scalar(
                    select(MediaRendition).where(
                        MediaRendition.tenant_id == version.tenant_id,
                        MediaRendition.version_id == version.id,
                        MediaRendition.object_key == rendition.object_key,
                    )
                )
                if existing_rendition is None:
                    database.add(
                        MediaRendition(
                            id=rendition.id,
                            tenant_id=version.tenant_id,
                            asset_id=version.asset_id,
                            version_id=version.id,
                            protocol=protocol.value,
                            content_type=content_type,
                            object_key=rendition.object_key,
                            width=rendition.width,
                            height=rendition.height,
                            bitrate_kbps=rendition.bitrate_kbps,
                        )
                    )
                elif (
                    existing_rendition.protocol != protocol.value
                    or existing_rendition.content_type != content_type
                ):
                    raise MediaConflict("The media processor reused a rendition identity.")
            caption_bytes = 0
            for caption in result.captions:
                caption_bytes += self._persist_processor_caption(
                    database,
                    version,
                    caption,
                    head_reader=head_budget.head,
                )
            if caption_bytes > self.processing_quota.max_caption_bytes:
                raise MediaQuotaExceeded("The media caption bytes exceed the processing quota.")
            if result.output_bytes is not None and result.output_bytes < caption_bytes:
                raise MediaConflict("The media processor output omits caption bytes.")
            version.avatar_variants = [
                {
                    "size_px": variant.size_px,
                    "content_type": variant.content_type,
                    "object_key": variant.object_key,
                }
                for variant in result.avatar_variants
                if self._child_key(version, variant.object_key)
                and head_budget.head(variant.object_key) is not None
            ]
            if len(version.avatar_variants) != len(result.avatar_variants):
                raise MediaConflict("The media processor returned an unavailable avatar variant.")
            if MediaPurpose(version.purpose) is MediaPurpose.VIDEO:
                # A processor that does not independently measure duration
                # cannot transition a video to READY.  In particular, do not
                # fall back to the duration supplied during upload completion.
                version.duration_seconds = _require_measured_duration(
                    result.duration_seconds,
                    maximum=self.processing_quota.max_duration_seconds,
                )
            elif result.duration_seconds is not None:
                version.duration_seconds = _require_measured_duration(
                    result.duration_seconds,
                    maximum=self.processing_quota.max_duration_seconds,
                )
            if result.width is not None:
                version.width = result.width
                version.height = result.height
            materialized = getattr(self.lifecycle_hooks, "objects_materialized", None)
            if callable(materialized):
                materialized(
                    self._object_reference(version),
                    tuple(key for key in inventory if key != version.object_key),
                )
        except (MediaStorageUnavailable, MediaQuotaExceeded):
            self._cleanup_processor_outputs(result, version=version)
            raise
        except MediaConflict as error:
            self._cleanup_processor_outputs(result, version=version)
            version.state = MediaLifecycle.FAILED.value
            version.processing_error = "MEDIA_PROCESSING_OUTPUT_INVALID"
            version.updated_at = self._now()
            database.flush()
            raise MediaConflict("The media processor returned invalid output.") from error
        except Exception as error:
            self._cleanup_processor_outputs(result, version=version)
            version.state = MediaLifecycle.FAILED.value
            version.processing_error = "MEDIA_PROCESSING_FAILED"
            version.updated_at = self._now()
            database.flush()
            raise MediaConflict("The media processor did not complete this version.") from error
        version.state = MediaLifecycle.READY.value
        version.processing_error = None
        version.updated_at = self._now()
        intent = database.scalar(
            select(MediaUploadIntent)
            .where(MediaUploadIntent.version_id == version.id)
            .with_for_update()
        )
        if intent is not None:
            intent.state = MediaLifecycle.READY.value
        current = (
            database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == asset.current_version_id,
                    MediaVersion.tenant_id == asset.tenant_id,
                    MediaVersion.asset_id == asset.id,
                )
            )
            if asset.current_version_id
            else None
        )
        if current is None or current.version_number <= version.version_number:
            asset.current_version_id = version.id
            asset.state = MediaLifecycle.READY.value
        asset.updated_at = version.updated_at
        database.flush()
        if version.supersedes_version_id is not None:
            superseded = database.scalar(
                select(MediaVersion).where(
                    MediaVersion.tenant_id == version.tenant_id,
                    MediaVersion.asset_id == version.asset_id,
                    MediaVersion.id == version.supersedes_version_id,
                )
            )
            if superseded is not None:
                for reference in self._version_object_references(database, superseded):
                    self.lifecycle_hooks.version_superseded(
                        reference,
                        superseded_at=version.updated_at,
                        policy=self.retention_policy,
                    )
        return self._asset_response(database, actor, asset)

    def get_media(
        self, database: Session, actor: ActorContext, asset_id: UUID
    ) -> MediaAssetResponse:
        asset = self._asset(database, actor, asset_id)
        self._require_read(actor, asset)
        return self._asset_response(database, actor, asset)

    def get_profile_avatar(self, database: Session, actor: ActorContext) -> ProfileAvatarResponse:
        """Return only the authenticated person's tenant-scoped avatar.

        The current ready version remains the presentation source while a
        replacement is uploading/processing/failed.  This deliberately keeps
        the old version usable and exposes no provider object key or provider
        identifier.  A delivery URL is minted only for a server-confirmed
        ready variant.
        """

        tenant_id = self._tenant(actor)
        asset = database.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.tenant_id == tenant_id,
                MediaAsset.owner_person_id == actor.person_id,
                MediaAsset.purpose == MediaPurpose.AVATAR.value,
                MediaAsset.state != MediaLifecycle.RETIRED.value,
            )
            .order_by(MediaAsset.updated_at.desc())
        )
        if asset is None:
            return ProfileAvatarResponse()

        current = (
            database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == asset.current_version_id,
                    MediaVersion.tenant_id == tenant_id,
                    MediaVersion.asset_id == asset.id,
                    MediaVersion.purpose == MediaPurpose.AVATAR.value,
                )
            )
            if asset.current_version_id
            else None
        )
        avatar = self._profile_avatar_version(database, actor, current)

        pending_versions = database.scalars(
            select(MediaVersion)
            .where(
                MediaVersion.tenant_id == tenant_id,
                MediaVersion.asset_id == asset.id,
                MediaVersion.purpose == MediaPurpose.AVATAR.value,
                MediaVersion.state.in_(
                    (
                        MediaLifecycle.UPLOADING.value,
                        MediaLifecycle.PROCESSING.value,
                        MediaLifecycle.FAILED.value,
                    )
                ),
            )
            .order_by(MediaVersion.version_number.desc())
        ).all()
        pending = next(
            (
                self._profile_avatar_version(database, actor, version)
                for version in pending_versions
                if current is None or version.id != current.id
            ),
            None,
        )
        return ProfileAvatarResponse(avatar=avatar, pending=pending)

    def _profile_avatar_version(
        self,
        database: Session,
        actor: ActorContext,
        version: MediaVersion | None,
    ) -> ProfileAvatarVersionResponse | None:
        if version is None:
            return None

        delivery_url: str | None = None
        size_px: int | None = None
        if version.state == MediaLifecycle.READY.value:
            variants = version.avatar_variants or []
            valid_variants = [
                item
                for item in variants
                if isinstance(item, dict)
                and self._avatar_variant_size(item) > 0
                and isinstance(item.get("content_type"), str)
                and isinstance(item.get("object_key"), str)
            ]
            if not valid_variants:
                raise MediaConflict("The ready avatar has no verified delivery variant.")
            selected = max(valid_variants, key=self._avatar_variant_size)
            object_key = str(selected["object_key"])
            content_type = str(selected["content_type"]).lower().split(";", 1)[0].strip()
            if not self._child_key(version, object_key):
                raise MediaConflict("The ready avatar variant is outside its private namespace.")
            if self.storage.head(object_key) is None:
                raise MediaStorageUnavailable("The ready avatar variant is unavailable.")
            if self.delivery_port is not None:
                delivery_url = self._signed_delivery_url(
                    actor=actor,
                    asset=self._asset(database, actor, version.asset_id),
                    version=version,
                    object_key=object_key,
                    expires_at=self._now() + timedelta(minutes=5),
                    kind="read",
                    supports_range=False,
                )
            size_px = self._avatar_variant_size(selected)
        else:
            content_type = version.content_type

        return ProfileAvatarVersionResponse(
            asset_id=version.asset_id,
            version_id=version.id,
            version_number=version.version_number,
            state=MediaLifecycle(version.state),
            delivery_url=delivery_url,
            content_type=content_type,
            size_px=size_px,
            avatar_crop=version.avatar_crop,
            supersedes_version_id=version.supersedes_version_id,
            updated_at=version.updated_at,
        )

    @staticmethod
    def _avatar_variant_size(item: object) -> int:
        if not isinstance(item, dict):
            return 0
        size_px = item.get("size_px")
        if not isinstance(size_px, int) or isinstance(size_px, bool) or size_px <= 0:
            return 0
        return size_px

    @staticmethod
    def _avatar_variant_response(item: dict[str, object]) -> AvatarVariantResponse:
        size_px = item.get("size_px")
        content_type = item.get("content_type")
        if (
            not isinstance(size_px, int)
            or isinstance(size_px, bool)
            or not isinstance(content_type, str)
        ):
            raise MediaConflict("The stored avatar variant metadata is invalid.")
        return AvatarVariantResponse(size_px=size_px, content_type=content_type)

    def _asset_response(
        self, database: Session, actor: ActorContext, asset: MediaAsset
    ) -> MediaAssetResponse:
        version = (
            database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == asset.current_version_id,
                    MediaVersion.tenant_id == asset.tenant_id,
                    MediaVersion.asset_id == asset.id,
                )
            )
            if asset.current_version_id
            else None
        )
        return MediaAssetResponse(
            id=asset.id,
            tenant_id=asset.tenant_id,
            owner_person_id=asset.owner_person_id,
            purpose=MediaPurpose(asset.purpose),
            state=MediaLifecycle(asset.state),
            current_version_id=asset.current_version_id,
            current_version=self._version_response(database, version) if version else None,
            version_count=database.scalar(
                select(func.count(MediaVersion.id)).where(MediaVersion.asset_id == asset.id)
            )
            or 0,
            created_at=asset.created_at,
            updated_at=asset.updated_at,
        )

    def _version_response(
        self,
        database: Session,
        version: MediaVersion | None,
        *,
        include_sources: bool = False,
        expires_at: datetime | None = None,
    ) -> MediaVersionResponse | None:
        if version is None:
            return None
        renditions = database.scalars(
            select(MediaRendition).where(
                MediaRendition.tenant_id == version.tenant_id,
                MediaRendition.version_id == version.id,
            )
        ).all()
        captions = database.scalars(
            select(MediaCaptionTrack).where(
                MediaCaptionTrack.tenant_id == version.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
        ).all()
        return MediaVersionResponse(
            id=version.id,
            asset_id=version.asset_id,
            version_number=version.version_number,
            purpose=MediaPurpose(version.purpose),
            state=MediaLifecycle(version.state),
            content_type=version.content_type,
            declared_bytes=version.declared_bytes,
            actual_bytes=version.actual_bytes,
            checksum_sha256=version.checksum_sha256,
            duration_seconds=version.duration_seconds,
            width=version.width,
            height=version.height,
            avatar_crop=version.avatar_crop,
            avatar_variants=[
                self._avatar_variant_response(item) for item in (version.avatar_variants or [])
            ],
            renditions=[
                RenditionResponse(
                    id=row.id,
                    protocol=DeliveryProtocol(row.protocol),
                    content_type=row.content_type,
                    width=row.width,
                    height=row.height,
                    bitrate_kbps=row.bitrate_kbps,
                )
                for row in renditions
            ],
            captions=[
                self._caption_response(
                    row, include_source_url=include_sources, expires_at=expires_at
                )
                for row in captions
            ],
            supersedes_version_id=version.supersedes_version_id,
            processing_error=version.processing_error,
            created_at=version.created_at,
            updated_at=version.updated_at,
        )

    def _caption_response(
        self,
        caption: MediaCaptionTrack,
        *,
        include_source_url: bool,
        expires_at: datetime | None,
        actor: ActorContext | None = None,
        asset: MediaAsset | None = None,
        version: MediaVersion | None = None,
        session_id: UUID | str | None = None,
    ) -> CaptionResponse:
        source_url = None
        if (
            include_source_url
            and self.delivery_port is not None
            and actor is not None
            and asset is not None
            and version is not None
        ):
            source_url = self._signed_delivery_url(
                actor=actor,
                asset=asset,
                version=version,
                object_key=caption.object_key,
                expires_at=expires_at or (self._now() + timedelta(minutes=5)),
                kind="read",
                supports_range=False,
                session_id=session_id,
            )
        return CaptionResponse(
            id=caption.id,
            media_version_id=caption.version_id,
            language=caption.language,
            kind=CaptionKind(caption.kind),
            state=CaptionState(caption.state),
            content_type=caption.content_type,
            is_default=caption.is_default,
            source_url=source_url,
            supersedes_caption_id=caption.supersedes_caption_id,
            created_at=caption.created_at,
        )

    def _playback_response(
        self,
        database: Session,
        actor: ActorContext,
        asset: MediaAsset,
        version: MediaVersion,
        request: PlaybackRequest,
        grant: MediaPlaybackGrant,
        token: str,
    ) -> PlaybackResponse:
        resume = database.scalar(
            select(MediaResumeState)
            .where(
                MediaResumeState.tenant_id == asset.tenant_id,
                MediaResumeState.actor_person_id == actor.person_id,
                MediaResumeState.asset_id == asset.id,
                MediaResumeState.version_id == version.id,
            )
            .with_for_update()
        )
        if resume is None:
            resume = MediaResumeState(
                tenant_id=asset.tenant_id,
                actor_person_id=actor.person_id,
                asset_id=asset.id,
                version_id=version.id,
            )
            database.add(resume)
            database.flush()
        expires_at = _as_utc(grant.expires_at)
        delivery = self._delivery(
            database,
            actor,
            asset,
            grant,
            version,
            preferred=request.preferred_protocol,
            expires_at=expires_at,
        )
        captions = [
            self._caption_response(
                row,
                include_source_url=True,
                expires_at=expires_at,
                actor=actor,
                asset=asset,
                version=version,
                session_id=grant.session_id,
            )
            for row in database.scalars(
                select(MediaCaptionTrack).where(
                    MediaCaptionTrack.tenant_id == asset.tenant_id,
                    MediaCaptionTrack.version_id == version.id,
                    MediaCaptionTrack.state == CaptionState.READY.value,
                )
            ).all()
        ]
        return PlaybackResponse(
            session_id=grant.session_id,
            media_id=asset.id,
            media_version_id=version.id,
            access_token=token,
            expires_at=expires_at,
            delivery=delivery,
            captions=captions,
            resume=self._resume_response(resume),
        )

    def create_playback(
        self,
        database: Session,
        actor: ActorContext,
        asset_id: UUID,
        request: PlaybackRequest,
        *,
        idempotency_key: str,
    ) -> PlaybackResponse:
        if not idempotency_key or len(idempotency_key) > 128:
            raise MediaBadRequest("A bounded Idempotency-Key is required for playback commands.")
        # Do this before creating or replaying a durable grant.  A runtime
        # without a reviewed application delivery handler must stay entirely
        # unavailable; it must not leave an orphaned grant behind and hope a
        # later route composition can make it usable.
        if self.delivery_port is None:
            raise MediaConflict("Media delivery is not composed for this runtime.")
        asset = self._asset(database, actor, asset_id)
        self._require_playback(database, actor, asset)
        if asset.state == MediaLifecycle.RETIRED.value:
            raise MediaForbidden("Retired media cannot be played.")
        version = (
            database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == asset.current_version_id,
                    MediaVersion.tenant_id == asset.tenant_id,
                    MediaVersion.asset_id == asset.id,
                    MediaVersion.state == MediaLifecycle.READY.value,
                )
            )
            if asset.current_version_id
            else None
        )
        if version is None:
            raise MediaConflict("The media is not ready for playback.")
        if MediaPurpose(version.purpose) is MediaPurpose.VIDEO:
            _require_measured_duration(
                version.duration_seconds,
                maximum=self.processing_quota.max_duration_seconds,
            )
        fingerprint = self._fingerprint(
            {"asset_id": str(asset.id), "request": request.model_dump(mode="json")}
        )
        existing = database.scalar(
            select(MediaPlaybackGrant)
            .where(
                MediaPlaybackGrant.tenant_id == asset.tenant_id,
                MediaPlaybackGrant.actor_person_id == actor.person_id,
                MediaPlaybackGrant.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise MediaConflict("The playback idempotency key was reused with different data.")
            if existing.revoked_at is not None or self._now() >= _as_utc(existing.expires_at):
                raise MediaConflict("The idempotent playback grant is no longer valid.")
            existing_version = self._version(database, actor, existing.version_id)
            if existing.asset_id != asset.id or existing_version.asset_id != asset.id:
                raise MediaConflict("The playback grant is outside the requested media scope.")
            token = self.signer.sign(
                {
                    "tenant_id": str(existing.tenant_id),
                    "actor_id": str(existing.actor_person_id),
                    "media_id": str(existing.asset_id),
                    "version_id": str(existing.version_id),
                    "session_id": str(existing.session_id),
                },
                now=_as_utc(existing.expires_at) - self.playback_ttl,
                lifetime=self.playback_ttl,
                token_type="playback",  # noqa: S106 - bounded token kind, not a secret
                nonce=existing.token_nonce,
            )
            if not hmac.compare_digest(existing.token_digest, self.signer.digest(token)):
                raise MediaConflict("The stored playback grant is invalid.")
            return self._playback_response(
                database, actor, asset, existing_version, request, existing, token
            )
        now = self._now()
        expires_at = now + self.playback_ttl
        session_id = uuid4()
        token_nonce = uuid4().hex
        token = self.signer.sign(
            {
                "tenant_id": str(asset.tenant_id),
                "actor_id": str(actor.person_id),
                "media_id": str(asset.id),
                "version_id": str(version.id),
                "session_id": str(session_id),
            },
            now=now,
            lifetime=self.playback_ttl,
            token_type="playback",  # noqa: S106 - bounded token kind, not a secret
            nonce=token_nonce,
        )
        grant = MediaPlaybackGrant(
            id=uuid4(),
            tenant_id=asset.tenant_id,
            actor_person_id=actor.person_id,
            session_id=session_id,
            asset_id=asset.id,
            version_id=version.id,
            token_digest=self.signer.digest(token),
            token_nonce=token_nonce,
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        database.add(grant)
        database.flush()
        return self._playback_response(database, actor, asset, version, request, grant, token)

    def _delivery(
        self,
        database: Session,
        actor: ActorContext,
        asset: MediaAsset,
        grant: MediaPlaybackGrant,
        version: MediaVersion,
        *,
        preferred: DeliveryProtocol | None,
        expires_at: datetime,
    ) -> MediaDeliveryResponse:
        rows = database.scalars(
            select(MediaRendition).where(MediaRendition.version_id == version.id)
        ).all()
        hls = next((row for row in rows if row.protocol == DeliveryProtocol.HLS.value), None)
        progressive = next(
            (row for row in rows if row.protocol == DeliveryProtocol.PROGRESSIVE.value), None
        )
        selected = (
            hls
            if preferred is DeliveryProtocol.HLS and hls
            else progressive
            if preferred is not DeliveryProtocol.HLS and progressive
            else hls or progressive
        )
        if selected is None:
            raise MediaConflict("The media has no approved playback rendition.")
        url = self._signed_delivery_url(
            actor=actor,
            asset=asset,
            version=version,
            object_key=selected.object_key,
            expires_at=expires_at,
            kind="playback",
            supports_range=selected.protocol == DeliveryProtocol.PROGRESSIVE.value,
            session_id=grant.session_id,
        )
        progressive_url = (
            self._signed_delivery_url(
                actor=actor,
                asset=asset,
                version=version,
                object_key=progressive.object_key,
                expires_at=expires_at,
                kind="playback",
                supports_range=True,
                session_id=grant.session_id,
            )
            if progressive and progressive.id != selected.id
            else None
        )
        return MediaDeliveryResponse(
            protocol=DeliveryProtocol(selected.protocol),
            manifest_url=url if selected.protocol == DeliveryProtocol.HLS.value else None,
            progressive_url=url
            if selected.protocol == DeliveryProtocol.PROGRESSIVE.value
            else progressive_url,
        )

    def heartbeat(
        self,
        database: Session,
        actor: ActorContext,
        asset_id: UUID,
        request: MediaHeartbeatRequest,
        bearer_token: str,
    ) -> HeartbeatResponse:
        claims = self.signer.verify(  # noqa: S106 - bounded token kind, not a secret
            bearer_token,
            now=self._now(),
            token_type="playback",  # noqa: S106 - bounded token kind, not a secret
        )
        expected = {
            "tenant_id": str(self._tenant(actor)),
            "actor_id": str(actor.person_id),
            "media_id": str(asset_id),
            "session_id": str(request.session_id),
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            raise MediaForbidden("The media authorization token is not bound to this request.")
        grant = database.scalar(
            select(MediaPlaybackGrant)
            .where(
                MediaPlaybackGrant.tenant_id == self._tenant(actor),
                MediaPlaybackGrant.actor_person_id == actor.person_id,
                MediaPlaybackGrant.asset_id == asset_id,
                MediaPlaybackGrant.session_id == request.session_id,
            )
            .with_for_update()
        )
        if (
            grant is None
            or grant.revoked_at is not None
            or not hmac.compare_digest(grant.token_digest, self.signer.digest(bearer_token))
        ):
            raise MediaForbidden("The media authorization token is invalid.")
        asset = self._asset(database, actor, asset_id, lock=True)
        self._require_read(actor, asset)
        version = self._version(database, actor, grant.version_id)
        if (
            str(version.id) != claims.get("version_id")
            or version.state != MediaLifecycle.READY.value
        ):
            raise MediaForbidden("The media authorization token is no longer valid.")
        duration_seconds = _require_measured_duration(
            version.duration_seconds,
            maximum=self.processing_quota.max_duration_seconds,
        )
        if request.position_seconds > duration_seconds:
            raise MediaBadRequest("The playback position is outside the media duration.")
        if request.visibility not in {"visible", "hidden", "background"}:
            raise MediaBadRequest("The playback visibility value is not supported.")
        resume = database.scalar(
            select(MediaResumeState)
            .where(
                MediaResumeState.tenant_id == asset.tenant_id,
                MediaResumeState.actor_person_id == actor.person_id,
                MediaResumeState.asset_id == asset.id,
                MediaResumeState.version_id == version.id,
            )
            .with_for_update()
        )
        if resume is None:
            resume = MediaResumeState(
                tenant_id=asset.tenant_id,
                actor_person_id=actor.person_id,
                asset_id=asset.id,
                version_id=version.id,
            )
            database.add(resume)
        if (
            request.client_event_id in (resume.client_event_ids or [])
            or request.sequence <= resume.last_sequence
        ):
            return HeartbeatResponse(
                **self._resume_response(resume).model_dump(),
                accepted=False,
                ignored_reason="duplicate",
            )
        previous = resume.position_seconds
        seek = request.played_from_seconds > previous + 2
        ignored = (
            "not_visible"
            if request.visibility != "visible"
            else "buffering"
            if request.is_buffering
            else "seek_gap"
            if seek
            else None
        )
        resume.position_seconds = min(request.position_seconds, duration_seconds)
        resume.last_sequence = request.sequence
        resume.client_event_ids = [
            *(resume.client_event_ids or [])[-1023:],
            request.client_event_id,
        ]
        resume.updated_at = self._now()
        database.flush()
        return HeartbeatResponse(
            **self._resume_response(resume).model_dump(),
            accepted=ignored is None,
            ignored_reason=ignored,
        )

    @staticmethod
    def _resume_response(resume: MediaResumeState) -> ResumeResponse:
        return ResumeResponse(
            position_seconds=resume.position_seconds, updated_at=resume.updated_at
        )

    def add_caption(
        self,
        database: Session,
        actor: ActorContext,
        asset_id: UUID,
        request: CaptionCreateRequest,
        *,
        idempotency_key: str,
    ) -> CaptionResponse:
        if not idempotency_key or len(idempotency_key) > 128:
            raise MediaBadRequest("A bounded Idempotency-Key is required for caption commands.")
        asset = self._asset(database, actor, asset_id, lock=True)
        self._require_write(actor, purpose=MediaPurpose.VIDEO, asset=asset)
        version = self._version(database, actor, asset.current_version_id or UUID(int=0), lock=True)
        if version.purpose != MediaPurpose.VIDEO.value:
            raise MediaBadRequest("Captions and transcripts can only be attached to video media.")
        if (
            version.state != MediaLifecycle.READY.value
            or asset.state == MediaLifecycle.RETIRED.value
        ):
            raise MediaConflict("Only ready, active video can receive captions.")
        existing = database.scalar(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == asset.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.idempotency_key == idempotency_key,
            )
            .with_for_update()
        )
        fingerprint = self._fingerprint(request.model_dump(mode="json"))
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise MediaConflict("The caption idempotency key was reused with different data.")
            return self._caption_response(
                existing,
                include_source_url=True,
                expires_at=self._now() + timedelta(minutes=5),
                actor=actor,
                asset=asset,
                version=version,
            )
        allowed = (
            {"application/json", "text/plain", "text/vtt"}
            if request.kind is CaptionKind.TRANSCRIPT
            else {"text/vtt", "text/plain"}
        )
        if request.content_type not in allowed:
            raise MediaBadRequest("The caption content type is not allowed for this track kind.")
        content_bytes = request.content.encode("utf-8")
        if len(content_bytes) > self.processing_quota.max_caption_bytes:
            raise MediaQuotaExceeded("The caption content exceeds the configured byte limit.")
        prior = database.scalars(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == asset.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.language == request.language,
                MediaCaptionTrack.kind == request.kind.value,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
            .order_by(MediaCaptionTrack.created_at.desc(), MediaCaptionTrack.id.desc())
            .with_for_update()
        ).all()
        ready_tracks = database.scalars(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == asset.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
            .with_for_update()
        ).all()
        if not prior and len(ready_tracks) >= self.processing_quota.max_caption_tracks:
            raise MediaQuotaExceeded("The media caption count exceeds the processing quota.")
        existing_caption_bytes = 0
        prior_ids = {row.id for row in prior}
        for row in ready_tracks:
            try:
                row_head = self.storage.head(row.object_key)
            except Exception as error:
                raise MediaStorageUnavailable(
                    "The private media storage adapter could not inspect an existing caption."
                ) from error
            if row_head is None or row_head.content_length <= 0:
                raise MediaStorageUnavailable("An existing media caption is unavailable.")
            if row.id not in prior_ids:
                existing_caption_bytes += row_head.content_length
        if existing_caption_bytes + len(content_bytes) > self.processing_quota.max_caption_bytes:
            raise MediaQuotaExceeded("The media caption bytes exceed the processing quota.")
        caption_id = uuid4()
        object_key = (
            f"{version.object_key}/captions/{request.language}/{request.kind.value}/{caption_id}"
        )
        try:
            self.storage.put(
                object_key=object_key, body=content_bytes, content_type=request.content_type
            )
            head = self.storage.head(object_key)
            expected_checksum = hashlib.sha256(content_bytes).hexdigest()
            if (
                head is None
                or head.content_length != len(content_bytes)
                or head.checksum_sha256.lower() != expected_checksum
                or head.content_type.lower().split(";", 1)[0].strip() != request.content_type
            ):
                raise MediaConflict("The stored media caption failed integrity verification.")
            scan = self.scanner.scan(
                storage=self.storage,
                object_key=object_key,
                declared_content_type=request.content_type,
                content_length=len(content_bytes),
                checksum_sha256=expected_checksum,
            )
            if not scan.clean:
                if scan.reason_code == "SCANNER_NOT_CONFIGURED":
                    raise MediaScannerUnavailable("The media safety scanner is not configured.")
                raise MediaConflict("The media caption failed the safety scan.")
            if (
                not scan.verified_checksum_sha256
                or scan.verified_checksum_sha256.lower() != expected_checksum
            ):
                raise MediaConflict("The media caption safety scan did not verify its checksum.")
        except (MediaConflict, MediaScannerUnavailable) as error:
            self._delete_object_best_effort(object_key, reference=self._object_reference(version))
            raise error
        except Exception as error:
            self._delete_object_best_effort(object_key, reference=self._object_reference(version))
            raise MediaStorageUnavailable(
                "The media caption could not be stored or scanned safely."
            ) from error
        for row in prior:
            row.state = CaptionState.SUPERSEDED.value
        try:
            database.add(
                MediaCaptionTrack(
                    id=caption_id,
                    tenant_id=asset.tenant_id,
                    version_id=version.id,
                    language=request.language,
                    kind=request.kind.value,
                    state=CaptionState.READY.value,
                    content_type=request.content_type,
                    object_key=object_key,
                    is_default=request.is_default,
                    supersedes_caption_id=prior[0].id if prior else None,
                    idempotency_key=idempotency_key,
                    request_fingerprint=fingerprint,
                )
            )
            if request.is_default:
                database.query(MediaCaptionTrack).filter(
                    MediaCaptionTrack.tenant_id == asset.tenant_id,
                    MediaCaptionTrack.version_id == version.id,
                    MediaCaptionTrack.kind == request.kind.value,
                    MediaCaptionTrack.id != caption_id,
                    MediaCaptionTrack.is_default.is_(True),
                ).update({"is_default": False}, synchronize_session=False)
            database.flush()
        except IntegrityError as error:
            self._delete_object_best_effort(object_key, reference=self._object_reference(version))
            raise MediaConflict(
                "The caption track changed concurrently; retry the idempotent command."
            ) from error
        except Exception:
            self._delete_object_best_effort(object_key, reference=self._object_reference(version))
            raise
        caption = database.scalar(
            select(MediaCaptionTrack).where(
                MediaCaptionTrack.tenant_id == asset.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.id == caption_id,
            )
        )
        if caption is None:  # pragma: no cover - the flush above guarantees this row
            raise MediaConflict("The caption track could not be persisted.")
        return self._caption_response(
            caption,
            include_source_url=True,
            expires_at=self._now() + timedelta(minutes=5),
            actor=actor,
            asset=asset,
            version=version,
        )

    def list_captions(
        self, database: Session, actor: ActorContext, asset_id: UUID
    ) -> list[CaptionResponse]:
        asset = self._asset(database, actor, asset_id)
        self._require_read(actor, asset)
        version = self._version(database, actor, asset.current_version_id or UUID(int=0))
        rows = database.scalars(
            select(MediaCaptionTrack)
            .where(
                MediaCaptionTrack.tenant_id == asset.tenant_id,
                MediaCaptionTrack.version_id == version.id,
                MediaCaptionTrack.state == CaptionState.READY.value,
            )
            .order_by(MediaCaptionTrack.language, MediaCaptionTrack.kind)
        ).all()
        return [
            self._caption_response(
                row,
                include_source_url=True,
                expires_at=self._now() + timedelta(minutes=5),
                actor=actor,
                asset=asset,
                version=version,
            )
            for row in rows
        ]

    def retire(self, database: Session, actor: ActorContext, asset_id: UUID) -> RetireResponse:
        asset = self._asset(database, actor, asset_id, lock=True)
        self._require_write(actor, purpose=MediaPurpose(asset.purpose), asset=asset)
        if asset.state == MediaLifecycle.RETIRED.value:
            return RetireResponse(
                media_id=asset.id,
                state=MediaLifecycle.RETIRED,
                retired_at=asset.updated_at,
            )
        now = self._now()
        asset.state = MediaLifecycle.RETIRED.value
        asset.updated_at = now
        database.query(MediaPlaybackGrant).filter(
            MediaPlaybackGrant.tenant_id == asset.tenant_id,
            MediaPlaybackGrant.asset_id == asset.id,
            MediaPlaybackGrant.revoked_at.is_(None),
        ).update({"revoked_at": now}, synchronize_session=False)
        database.flush()
        for version in database.scalars(
            select(MediaVersion).where(
                MediaVersion.tenant_id == asset.tenant_id,
                MediaVersion.asset_id == asset.id,
            )
        ).all():
            for reference in self._version_object_references(database, version):
                self.lifecycle_hooks.asset_retired(
                    reference,
                    retired_at=now,
                    policy=self.retention_policy,
                )
        return RetireResponse(media_id=asset.id, state=MediaLifecycle.RETIRED, retired_at=now)

    def verify_webhook_signature(
        self,
        raw_body: bytes,
        signature: str,
        *,
        timestamp: int | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Verify a callback signature, including freshness at the HTTP seam.

        Existing trusted worker callers may continue using the legacy raw-body
        form while they migrate.  The canonical HTTP route supplies a
        timestamp, which binds the signature to the body and rejects replayed
        callbacks outside the five-minute tolerance window.
        """

        value = signature.strip().removeprefix("sha256=")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            return False
        signed_body = raw_body
        if timestamp is not None:
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
                return False
            current = _as_utc(now or self._now())
            if abs(current.timestamp() - timestamp) > _WEBHOOK_TIMESTAMP_TOLERANCE.total_seconds():
                return False
            signed_body = f"{timestamp}.".encode("ascii") + raw_body
        expected = hmac.new(self.webhook_secret, signed_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, value)

    def handle_webhook(
        self,
        database: Session,
        provider: str,
        raw_body: bytes,
        signature: str,
        *,
        timestamp: int | None = None,
        now: datetime | None = None,
    ) -> tuple[MediaVersionResponse, bool]:
        if not self._provider_activation_verified():
            raise MediaConfigurationError("The media provider webhook is not activated.")
        if provider != "video" or not self.verify_webhook_signature(
            raw_body, signature, timestamp=timestamp, now=now
        ):
            raise MediaForbidden("The media provider webhook signature is invalid.")
        try:
            request = VideoWebhookRequest.model_validate_json(raw_body)
        except ValueError as error:
            raise MediaBadRequest("The media provider webhook payload is invalid.") from error
        if request.state.value == MediaLifecycle.READY.value:
            # The callback route is intentionally unmounted: this slice has
            # no inbox-first raw-envelope persistence, quick ACK, and async
            # worker.  Keep the direct service seam fail-closed too; a
            # provider-declared duration is never an internal measurement.
            raise MediaConflict(
                "Provider READY is unavailable without an independent internal duration "
                "measurement."
            )
        version = database.scalar(
            select(MediaVersion)
            .where(MediaVersion.id == request.media_version_id)
            .with_for_update()
        )
        if version is None:
            raise MediaNotFound("The media version was not found.")
        if not version.provider_asset_id or version.provider_asset_id != request.provider_asset_id:
            raise MediaConflict("The webhook provider asset is not bound to this media version.")
        digest = hashlib.sha256(raw_body).hexdigest()
        inbox = database.scalar(
            select(MediaWebhookInbox)
            .where(
                MediaWebhookInbox.provider_name == provider,
                MediaWebhookInbox.provider_event_id == request.provider_event_id,
            )
            .with_for_update()
        )
        if inbox is not None:
            if (
                inbox.event_digest != digest
                or inbox.tenant_id != version.tenant_id
                or inbox.version_id != version.id
            ):
                raise MediaConflict("The provider event was reused for a different media scope.")
            if inbox.processed_at is not None:
                response = self._version_response(database, version)
                if response is None:  # pragma: no cover - version was loaded above
                    raise MediaNotFound("The media version was not found.")
                return response, True
            if inbox.claimed_at is not None and self._now() < inbox.claimed_at + timedelta(
                minutes=5
            ):
                raise MediaConflict("The provider webhook is already being processed.")
            inbox.claimed_at = self._now()
        else:
            inbox = MediaWebhookInbox(
                provider_name=provider,
                provider_event_id=request.provider_event_id,
                tenant_id=version.tenant_id,
                version_id=version.id,
                event_digest=digest,
                claimed_at=self._now(),
            )
            database.add(inbox)
        if version.state != MediaLifecycle.PROCESSING.value:
            raise MediaConflict("The provider webhook is only valid while media is processing.")
        if request.state not in {MediaLifecycle.READY, MediaLifecycle.FAILED}:
            raise MediaBadRequest("The provider webhook state is not terminal.")
        expected_event_type = (
            "video.ready" if request.state is MediaLifecycle.READY else "video.failed"
        )
        if request.event_type.strip().lower() != expected_event_type:
            raise MediaBadRequest("The provider webhook event type does not match its state.")
        if request.state is MediaLifecycle.READY:
            head_budget = _BoundedMediaHeadReader(
                self.storage, self.processing_quota.max_head_operations
            )
            if not request.renditions:
                raise MediaConflict("A ready provider webhook must include a playback rendition.")
            if len(request.renditions) > self.processing_quota.max_renditions:
                raise MediaQuotaExceeded(
                    "The provider rendition count exceeds the processing quota."
                )
            measured_duration = _require_measured_duration(
                request.duration_seconds
                if request.duration_seconds is not None
                else version.duration_seconds,
                maximum=self.processing_quota.max_duration_seconds,
            )
            source_head = head_budget.head(version.object_key)
            if source_head is None:
                raise MediaConflict("The provider source object is unavailable.")
            if (
                isinstance(source_head.content_length, bool)
                or not isinstance(source_head.content_length, int)
                or source_head.content_length <= 0
            ):
                raise MediaConflict("The provider source size is unverified.")
            self.processing_quota.check_source(source_head.content_length)
            if source_head.content_type.lower().split(";", 1)[0].strip() != version.content_type:
                raise MediaConflict("The provider source MIME is unverified.")
            if (
                version.actual_bytes is not None
                and source_head.content_length != version.actual_bytes
            ):
                raise MediaConflict("The provider source changed after upload completion.")
            if version.checksum_sha256 is not None and (
                not source_head.checksum_sha256
                or not _SHA256.fullmatch(source_head.checksum_sha256)
                or source_head.checksum_sha256.lower() != version.checksum_sha256.lower()
            ):
                raise MediaConflict("The provider source checksum is unverified.")
            rendition_ids: set[UUID] = set()
            rendition_keys: set[str] = set()
            materialized_keys: set[str] = set(request.object_keys)
            hls_content_types = _RENDITION_CONTENT_TYPES[DeliveryProtocol.HLS]
            for object_key in materialized_keys:
                if len(materialized_keys) > self.processing_quota.max_output_files:
                    raise MediaQuotaExceeded(
                        "The provider output file count exceeds the processing quota."
                    )
                if not self._child_key(version, object_key):
                    raise MediaBadRequest(
                        "The provider object inventory is outside the private media namespace."
                    )
                object_head = head_budget.head(object_key)
                if object_head is None:
                    raise MediaConflict("The provider object inventory is not available.")
                if (
                    isinstance(object_head.content_length, bool)
                    or not isinstance(object_head.content_length, int)
                    or object_head.content_length <= 0
                ):
                    raise MediaConflict("The provider object inventory size is unverified.")
                if not object_head.checksum_sha256 or not _SHA256.fullmatch(
                    object_head.checksum_sha256
                ):
                    raise MediaConflict("The provider object inventory checksum is unverified.")
                object_mime = object_head.content_type.lower().split(";", 1)[0].strip()
                if object_key.lower().endswith(".m3u8") and object_mime not in hls_content_types:
                    raise MediaConflict(
                        "The provider object inventory contains an unverified playlist."
                    )
                if object_key.lower().endswith(".ts") and object_mime != "video/mp2t":
                    raise MediaConflict(
                        "The provider object inventory contains an unverified segment."
                    )
            for rendition in request.renditions:
                if rendition.id in rendition_ids or rendition.object_key in rendition_keys:
                    raise MediaBadRequest("The provider webhook contains duplicate renditions.")
                rendition_ids.add(rendition.id)
                rendition_keys.add(rendition.object_key)
                if not self._child_key(version, rendition.object_key):
                    raise MediaBadRequest(
                        "The provider rendition is outside the private media namespace."
                    )
                allowed_content_types = _RENDITION_CONTENT_TYPES[rendition.protocol]
                if rendition.content_type not in allowed_content_types:
                    raise MediaBadRequest("The provider rendition content type is not supported.")
                head = head_budget.head(rendition.object_key)
                if head is None:
                    raise MediaConflict("The provider rendition is not available.")
                if not head.checksum_sha256 or not _SHA256.fullmatch(head.checksum_sha256):
                    raise MediaConflict("The provider rendition checksum is unverified.")
                if head.content_type.lower().split(";", 1)[0].strip() != rendition.content_type:
                    raise MediaConflict("The provider rendition content type is not verified.")
                if rendition.protocol is DeliveryProtocol.HLS:
                    try:
                        discovered_objects = inspect_hls_playlist_inventory(
                            self.storage,
                            root_key=rendition.object_key,
                            namespace_prefix=version.object_key,
                            max_duration_seconds=self.processing_quota.max_duration_seconds,
                            max_head_operations=max(
                                1,
                                self.processing_quota.max_head_operations
                                // max(1, len(request.renditions)),
                            ),
                            head_reader=head_budget.head,
                        )
                    except MediaProcessingError as error:
                        raise MediaConflict(
                            "The provider HLS object graph could not be verified."
                        ) from error
                    materialized_keys.update(discovered_objects)
                    if len(materialized_keys) > self.processing_quota.max_output_files:
                        raise MediaQuotaExceeded(
                            "The provider output file count exceeds the processing quota."
                        )
                materialized_keys.add(rendition.object_key)
                database.add(
                    MediaRendition(
                        id=rendition.id,
                        tenant_id=version.tenant_id,
                        asset_id=version.asset_id,
                        version_id=version.id,
                        protocol=rendition.protocol.value,
                        content_type=rendition.content_type,
                        object_key=rendition.object_key,
                        width=rendition.width,
                        height=rendition.height,
                        bitrate_kbps=rendition.bitrate_kbps,
                    )
                )
            output_bytes = 0
            for object_key in materialized_keys:
                metadata = head_budget.seen.get(object_key)
                if metadata is None:
                    raise MediaConflict("The provider output inventory is unverified.")
                output_bytes += metadata.content_length
            if output_bytes > self.processing_quota.max_output_bytes:
                raise MediaQuotaExceeded("The provider output exceeds the processing quota.")
            materialized = getattr(self.lifecycle_hooks, "objects_materialized", None)
            if callable(materialized):
                materialized(self._object_reference(version), tuple(sorted(materialized_keys)))
            version.duration_seconds = measured_duration
            version.state = MediaLifecycle.READY.value
            version.processing_error = None
            intent = database.scalar(
                select(MediaUploadIntent)
                .where(MediaUploadIntent.version_id == version.id)
                .with_for_update()
            )
            if intent is not None:
                intent.state = MediaLifecycle.READY.value
            asset = database.scalar(
                select(MediaAsset)
                .where(MediaAsset.id == version.asset_id, MediaAsset.tenant_id == version.tenant_id)
                .with_for_update()
            )
            if asset is None:
                raise MediaNotFound("The media asset was not found.")
            current = (
                database.scalar(
                    select(MediaVersion).where(
                        MediaVersion.id == asset.current_version_id,
                        MediaVersion.tenant_id == asset.tenant_id,
                        MediaVersion.asset_id == asset.id,
                    )
                )
                if asset.current_version_id
                else None
            )
            if current is None or current.version_number <= version.version_number:
                asset.current_version_id = version.id
                asset.state = MediaLifecycle.READY.value
            version.updated_at = self._now()
            asset.updated_at = version.updated_at
            if version.supersedes_version_id is not None:
                superseded = database.scalar(
                    select(MediaVersion).where(
                        MediaVersion.tenant_id == version.tenant_id,
                        MediaVersion.asset_id == version.asset_id,
                        MediaVersion.id == version.supersedes_version_id,
                    )
                )
                if superseded is not None:
                    for reference in self._version_object_references(database, superseded):
                        self.lifecycle_hooks.version_superseded(
                            reference,
                            superseded_at=version.updated_at,
                            policy=self.retention_policy,
                        )
        else:
            version.state = MediaLifecycle.FAILED.value
            version.processing_error = self._safe_failure_code(
                request.failure_code, fallback="MEDIA_PROVIDER_PROCESSING_FAILED"
            )
            intent = database.scalar(
                select(MediaUploadIntent)
                .where(MediaUploadIntent.version_id == version.id)
                .with_for_update()
            )
            if intent is not None:
                intent.state = MediaLifecycle.FAILED.value
            asset = database.scalar(
                select(MediaAsset)
                .where(
                    MediaAsset.id == version.asset_id,
                    MediaAsset.tenant_id == version.tenant_id,
                )
                .with_for_update()
            )
            if asset is not None and asset.current_version_id is None:
                asset.state = MediaLifecycle.FAILED.value
            # A failed provider attempt has no returned inventory. Discover
            # and remove only children of this version prefix; failures remain
            # retryable through the lifecycle/retention worker if listing or
            # deletion is unavailable.
            self._cleanup_processor_outputs(None, version=version)
        inbox.claimed_at = None
        inbox.processed_at = self._now()
        inbox.result_version_id = version.id
        database.flush()
        # This response intentionally uses only provider-neutral public fields.
        response = self._version_response(database, version)
        if response is None:  # pragma: no cover - version was loaded above
            raise MediaNotFound("The media version was not found.")
        return response, False


__all__ = ["MediaPlaybackAuthorizer", "MediaService"]
