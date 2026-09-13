"""Explicit disposable-sandbox avatar composition over canonical media commands."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

if TYPE_CHECKING:
    from ac_platform.media.studio_upload import StudioUploadAuthorization

from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import (
    MediaAssetResponse,
    UploadIntentRequest,
    UploadIntentResponse,
)
from ac_platform.media.contracts import EphemeralMediaUrl
from ac_platform.media.delivery import (
    MediaDeliveryAuthorizer,
    MediaDeliveryResult,
    MediaTokenType,
    PrivateMediaDeliveryHandler,
)
from ac_platform.media.errors import (
    MediaBadRequest,
    MediaConfigurationError,
    MediaForbidden,
    MediaStorageUnavailable,
)
from ac_platform.media.local_avatar_processing import LocalAvatarProcessor, LocalAvatarScanner
from ac_platform.media.local_avatar_storage import (
    LOCAL_AVATAR_ORIGIN,
    MAX_AVATAR_BYTES,
    UPLOAD_PREFIX,
    FilesystemAvatarStorage,
    LocalAvatarStorage,
)
from ac_platform.media.models import (
    MediaAsset,
    MediaLifecycle,
    MediaPurpose,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.policy import MediaCorsPolicy, SignedMediaDeliveryPort
from ac_platform.media.runtime import MediaRuntime, _derive
from ac_platform.media.service import MediaService
from ac_platform.media.signing import MediaSigner
from ac_platform.tenancy.models import Membership, Tenant


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class LocalAvatarMediaService(MediaService):
    @staticmethod
    def _secure_media_url(value: str, *, description: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme == "http" and (
            f"{parsed.scheme}://{parsed.netloc}" != LOCAL_AVATAR_ORIGIN
            or not parsed.path.startswith((UPLOAD_PREFIX, "/v1/media/read/"))
        ):
            raise MediaStorageUnavailable("The local profile URL is outside its exact origin.")
        try:
            return EphemeralMediaUrl(value, allow_loopback_http=True).value
        except (TypeError, ValueError) as error:
            raise MediaStorageUnavailable(
                f"The local profile {description} URL is invalid."
            ) from error

    def create_upload_intent(
        self,
        database: Session,
        actor: ActorContext,
        request: UploadIntentRequest,
        *,
        idempotency_key: str,
        studio_authorization: StudioUploadAuthorization | None = None,
    ) -> UploadIntentResponse:
        if request.purpose is not MediaPurpose.AVATAR:
            raise MediaForbidden("This local upload adapter accepts only profile photos.")
        if request.crop is not None and request.crop.rotation_degrees != 0:
            raise MediaBadRequest("This local photo editor does not support crop rotation.")
        return super().create_upload_intent(
            database,
            actor,
            request,
            idempotency_key=idempotency_key,
            studio_authorization=studio_authorization,
        )


@dataclass(frozen=True)
class LocalAvatarRuntime:
    storage: LocalAvatarStorage
    service: LocalAvatarMediaService

    @staticmethod
    def require_identity(database: Session, actor: ActorContext) -> None:
        session = database.scalar(
            select(IdentitySession.id)
            .join(Person, Person.id == IdentitySession.person_id)
            .join(
                Membership,
                (Membership.person_id == Person.id) & (Membership.tenant_id == actor.tenant_id),
            )
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                IdentitySession.id == actor.session_id,
                IdentitySession.person_id == actor.person_id,
                IdentitySession.selected_tenant_id == actor.tenant_id,
                IdentitySession.revoked_at.is_(None),
                IdentitySession.expires_at > datetime.now(UTC),
                Person.status == "active",
                Membership.status == "active",
                Membership.ended_at.is_(None),
                Tenant.status == "active",
            )
        )
        if session is None:
            raise MediaForbidden("The local profile session is unavailable.")

    def accept_upload(
        self,
        database: Session,
        actor: ActorContext,
        *,
        key: str,
        token: str,
        body: bytes,
        content_type: str,
        declared_length: str,
        checksum: str,
    ) -> UUID:
        self.require_identity(database, actor)
        if (
            not self.storage.owns(key)
            or not key.endswith("/original")
            or not 0 < len(body) <= MAX_AVATAR_BYTES
        ):
            raise MediaBadRequest("The local profile upload target or bytes are invalid.")
        now = datetime.now(UTC)
        claims = self.storage.signer.verify(
            token, now=now, token_type=self.storage.token_type
        )  # noqa: S106 - bounded token kind, not a secret
        digest = hashlib.sha256(body).hexdigest()
        if (
            claims.get("key") != key
            or claims.get("bytes") != len(body)
            or claims.get("mime") != content_type
            or claims.get("checksum") != digest
            or declared_length != str(len(body))
            or checksum != digest
        ):
            raise MediaForbidden("The local profile upload differs from its signed intent.")
        intent = database.scalar(
            select(MediaUploadIntent)
            .where(
                MediaUploadIntent.object_key == key,
                MediaUploadIntent.tenant_id == actor.tenant_id,
                MediaUploadIntent.actor_person_id == actor.person_id,
            )
            .with_for_update()
        )
        if intent is None:
            raise MediaForbidden("The local profile upload is unavailable.")
        asset = database.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.id == intent.asset_id,
                MediaAsset.tenant_id == actor.tenant_id,
                MediaAsset.owner_person_id == actor.person_id,
                MediaAsset.purpose == "avatar",
                MediaAsset.state != "retired",
            )
            .with_for_update()
        )
        version = database.scalar(
            select(MediaVersion)
            .where(
                MediaVersion.id == intent.version_id,
                MediaVersion.tenant_id == actor.tenant_id,
                MediaVersion.asset_id == intent.asset_id,
                MediaVersion.purpose == "avatar",
                MediaVersion.object_key == key,
            )
            .with_for_update()
        )
        if (
            asset is None
            or version is None
            or intent.state != "uploading"
            or version.state != "uploading"
            or utc(intent.expires_at) <= now
            or intent.declared_bytes != len(body)
            or intent.content_type != content_type
            or intent.checksum_sha256 != digest
            or intent.max_bytes < len(body)
        ):
            raise MediaForbidden("The local profile upload intent is no longer available.")
        self.storage.put(object_key=key, body=body, content_type=content_type)
        return intent.version_id

    def finish(self, database: Session, actor: ActorContext, upload_id: UUID) -> MediaAssetResponse:
        self.require_identity(database, actor)
        intent = database.scalar(
            select(MediaUploadIntent).where(
                MediaUploadIntent.id == upload_id,
                MediaUploadIntent.tenant_id == actor.tenant_id,
                MediaUploadIntent.actor_person_id == actor.person_id,
            )
        )
        if intent is None:
            raise MediaForbidden("The local profile upload is unavailable.")
        version = database.scalar(
            select(MediaVersion).where(
                MediaVersion.id == intent.version_id,
                MediaVersion.tenant_id == actor.tenant_id,
                MediaVersion.purpose == "avatar",
            )
        )
        if version is None:
            raise MediaForbidden("The local profile version is unavailable.")
        if version.state == MediaLifecycle.PROCESSING.value:
            return self.service.process_version(database, actor, version.id)
        return self.service.get_media(database, actor, intent.asset_id)

    def authorize_read(
        self, database: Session, actor: ActorContext, claims: Mapping[str, object]
    ) -> bool:
        try:
            self.require_identity(database, actor)
            if any(
                claims.get(key) != str(value)
                for key, value in (
                    ("tenant_id", actor.tenant_id),
                    ("person_id", actor.person_id),
                    ("session_id", actor.session_id),
                )
            ):
                return False
            asset_id, version_id = (
                UUID(str(claims.get("asset_id"))),
                UUID(str(claims.get("version_id"))),
            )
            asset = database.scalar(
                select(MediaAsset).where(
                    MediaAsset.id == asset_id,
                    MediaAsset.tenant_id == actor.tenant_id,
                    MediaAsset.owner_person_id == actor.person_id,
                    MediaAsset.purpose == "avatar",
                    MediaAsset.current_version_id == version_id,
                    MediaAsset.state != "retired",
                )
            )
            version = database.scalar(
                select(MediaVersion).where(
                    MediaVersion.id == version_id,
                    MediaVersion.asset_id == asset_id,
                    MediaVersion.tenant_id == actor.tenant_id,
                    MediaVersion.purpose == "avatar",
                    MediaVersion.state == "ready",
                )
            )
            if asset is None or version is None:
                return False
            key = claims.get("key")
            return (
                isinstance(key, str)
                and self.storage.owns(key)
                and key.startswith(version.object_key + "/avatar/")
                and any(
                    item.get("object_key") == key and item.get("content_type") == "image/webp"
                    for item in version.avatar_variants
                )
            )
        except (MediaForbidden, ValueError, TypeError):
            return False


class _AvatarDeliveryHandler(PrivateMediaDeliveryHandler):
    """Use avatar storage only for avatar keys; preserve the prior media graph."""

    def __init__(
        self,
        *,
        previous: PrivateMediaDeliveryHandler,
        storage: LocalAvatarStorage,
        signer: MediaSigner,
        delivery_port: SignedMediaDeliveryPort,
        cors_policy: MediaCorsPolicy,
        authorizer: Callable[[Mapping[str, object], MediaTokenType], bool]
        | MediaDeliveryAuthorizer,
        max_object_bytes: int,
    ) -> None:
        super().__init__(
            storage=storage,
            signer=signer,
            delivery_port=delivery_port,
            cors_policy=cors_policy,
            authorizer=authorizer,
            max_object_bytes=max_object_bytes,
        )
        self._previous = previous
        self._avatar_storage = storage

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
        if self._avatar_storage.owns(object_key):
            return super().serve(
                token=token,
                token_type=token_type,
                object_key=object_key,
                method=method,
                origin=origin,
                range_header=range_header,
                now=now,
            )
        return self._previous.serve(
            token=token,
            token_type=token_type,
            object_key=object_key,
            method=method,
            origin=origin,
            range_header=range_header,
            now=now,
        )


def compose_local_avatar_runtime(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    from ac_platform.development.seed import require_local_target

    require_local_target(settings, acknowledged=settings.media_local_avatar_enabled)
    if (
        base.environment != "local"
        or str(settings.public_app_url).rstrip("/") != LOCAL_AVATAR_ORIGIN
        or base.media_delivery is None
        or base.media_cors_policy is None
        or base.authenticated_delivery_handler_factory is None
        or not settings.media_local_avatar_storage_root
    ):
        raise MediaConfigurationError(
            "Local profile photos require the managed local film sandbox."
        )
    storage = LocalAvatarStorage(
        root=Path(settings.media_local_avatar_storage_root),
        signer=MediaSigner(
            _derive(settings.session_token_pepper.get_secret_value(), b"local-avatar-upload-v1")
        ),
        fallback=base.service.storage,
    )
    service = LocalAvatarMediaService(
        storage=storage,
        signer=base.service.signer,
        webhook_secret=base.service.webhook_secret,
        scanner=LocalAvatarScanner(),
        processor=LocalAvatarProcessor(),
        delivery_port=base.media_delivery,
        delivery_activity_resolver=base.service.delivery_activity_resolver,
        max_upload_bytes=MAX_AVATAR_BYTES,
        quota_bytes_per_actor=25 * 1024 * 1024,
        quota_uploads_per_actor=10,
        media_config=base.media_config,
    )
    local = LocalAvatarRuntime(storage, service)
    prior_factory = base.authenticated_delivery_handler_factory

    def factory(database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        prior = prior_factory(database, actor)

        def authorize(claims: Mapping[str, object], kind: MediaTokenType) -> bool:
            if kind == "read":
                return local.authorize_read(database, actor, claims)
            checker = prior.authorizer
            return checker(claims, kind) if callable(checker) else checker.authorize(claims, kind)

        return _AvatarDeliveryHandler(
            previous=prior,
            storage=storage,
            signer=prior.signer,
            delivery_port=prior.delivery_port,
            cors_policy=prior.cors_policy,
            authorizer=authorize,
            max_object_bytes=prior.max_object_bytes,
        )

    return replace(
        base,
        local_avatar_runtime=local,
        authenticated_delivery_handler_factory=factory,
    )


def compose_filesystem_avatar_runtime(settings: Settings, base: MediaRuntime) -> MediaRuntime:
    """Compose deployment profile avatars beside, never inside, Studio video."""

    from ac_platform.media.clamav_scanner import ClamAVContentScanner, ClamAVScannerConfig

    if (
        settings.environment not in {"staging", "production"}
        or not settings.media_filesystem_enabled
        or not settings.media_filesystem_avatar_root
        or base.environment != settings.environment
        or base.media_delivery is None
        or base.media_cors_policy is None
        or base.authenticated_delivery_handler_factory is None
    ):
        raise MediaConfigurationError(
            "Deployment profile photos require the reviewed filesystem media composition."
        )
    scanner_config = ClamAVScannerConfig(
        unix_socket=settings.media_scanner_unix_socket,
        host=settings.media_scanner_host,
        port=settings.media_scanner_port,
        max_content_bytes=MAX_AVATAR_BYTES,
        total_timeout_seconds=min(settings.media_scanner_total_timeout_seconds, 120.0),
    )
    storage = FilesystemAvatarStorage(
        root=Path(settings.media_filesystem_avatar_root),
        signer=MediaSigner(
            _derive(
                settings.session_token_pepper.get_secret_value(),
                b"filesystem-avatar-upload-v1",
            )
        ),
        fallback=base.service.storage,
        origin=str(settings.public_app_url).rstrip("/"),
    )
    service = LocalAvatarMediaService(
        storage=storage,
        signer=base.service.signer,
        webhook_secret=base.service.webhook_secret,
        scanner=ClamAVContentScanner(scanner_config),
        processor=LocalAvatarProcessor(),
        delivery_port=base.media_delivery,
        delivery_activity_resolver=base.service.delivery_activity_resolver,
        max_upload_bytes=MAX_AVATAR_BYTES,
        quota_bytes_per_actor=25 * 1024 * 1024,
        quota_uploads_per_actor=10,
        media_config=base.media_config,
    )
    filesystem_avatar = LocalAvatarRuntime(storage, service)
    prior_factory = base.authenticated_delivery_handler_factory

    def factory(database: Session, actor: ActorContext) -> PrivateMediaDeliveryHandler:
        prior = prior_factory(database, actor)

        def authorize(claims: Mapping[str, object], kind: MediaTokenType) -> bool:
            if kind == "read":
                return filesystem_avatar.authorize_read(database, actor, claims)
            checker = prior.authorizer
            return checker(claims, kind) if callable(checker) else checker.authorize(claims, kind)

        return _AvatarDeliveryHandler(
            previous=prior,
            storage=storage,
            signer=prior.signer,
            delivery_port=prior.delivery_port,
            cors_policy=prior.cors_policy,
            authorizer=authorize,
            max_object_bytes=prior.max_object_bytes,
        )

    return replace(
        base,
        filesystem_avatar_runtime=filesystem_avatar,
        authenticated_delivery_handler_factory=factory,
    )
