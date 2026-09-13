"""Audited promotion of one READY Coach video into the global Free Course.

The source upload and processing remain the ordinary Studio lifecycle.  This
small operator composes a second tenant-owned media identity only after the
source version is READY, copies objects through the configured private-storage
port with checksum verification, and calls the existing binding ledger for the
published global activity.  It never mutates the source asset or learning
progress and never treats a filesystem path as an authoritative media row.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction, SessionTransactionOrigin

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.catalog.models import (
    Activity,
    ActivityKind,
    CatalogScope,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.identity.models import Person
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import (
    ActivityMediaBindingRequest,
    ActivityMediaBindingResponse,
)
from ac_platform.media.errors import MediaForbidden
from ac_platform.media.models import (
    MediaAsset,
    MediaCaptionTrack,
    MediaLifecycle,
    MediaPurpose,
    MediaRendition,
    MediaVersion,
)
from ac_platform.media.service import MediaService
from ac_platform.media.storage import PrivateObjectStorage, StoredObjectMetadata
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

_IDENTITY_NAMESPACE = UUID("5bb8b3f3-cfb4-42d6-92ff-2c1d4b3fbf9b")
_ZERO_UUID = UUID(int=0)
_PROMOTION_ACTION = "media.free_course_promoted.v1"
_MEDIA_STATUS = "ready_public_tenant_media_bound"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REFERENCE = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")


class FreeCourseMediaPromotionError(RuntimeError):
    """The one approved source-to-public media promotion cannot proceed."""


class FreeCourseMediaPromotionConflict(FreeCourseMediaPromotionError):
    """The promotion identity or binding history has another meaning."""


@dataclass(frozen=True, slots=True)
class FreeCourseMediaPromotionResult:
    status: str
    command_id: UUID
    publication_command_id: UUID
    activity_id: UUID
    source_asset_id: UUID
    source_version_id: UUID
    asset_id: UUID
    version_id: UUID
    binding_id: UUID
    media_status: str


@dataclass(slots=True)
class FreeCourseMediaBindingAuthorization:
    """One internal lease for the existing binding service.

    The lease is minted only by ``FreeCourseMediaPromotionApplication`` after
    fresh operations authority, target membership, global catalog identity and
    source READY checks.  It is never accepted from HTTP input.
    """

    database: Session = field(repr=False)
    transaction: SessionTransaction = field(repr=False)
    savepoint: SessionTransaction = field(repr=False)
    actor: ActorContext = field(repr=False)
    service: MediaService = field(repr=False)
    request_json: str = field(repr=False)
    tenant_id: UUID = field(repr=False)
    activity_id: UUID = field(repr=False)
    asset_id: UUID = field(repr=False)
    version_id: UUID = field(repr=False)
    seal: object = field(repr=False)
    active: bool = field(default=True, repr=False)

    def require(
        self,
        database: Session,
        actor: ActorContext,
        *,
        service: MediaService,
        request: ActivityMediaBindingRequest,
    ) -> None:
        if (
            type(self) is not FreeCourseMediaBindingAuthorization
            or self.seal is not _SEAL
            or not self.active
            or database is not self.database
            or database.get_transaction() is not self.transaction
            or database.get_nested_transaction() is not self.savepoint
            or not self.transaction.is_active
            or not self.savepoint.is_active
            or actor != self.actor
            or service is not self.service
            or request.model_dump_json() != self.request_json
            or actor.tenant_id != self.tenant_id
            or request.activity_id != self.activity_id
            or request.asset_id != self.asset_id
            or request.version_id != self.version_id
        ):
            raise MediaForbidden("The exact active Free Course media authorization is required.")


_SEAL = object()


def _require_transaction(database: AsyncSession) -> None:
    transaction = database.get_transaction()
    sync_transaction = None if transaction is None else transaction.sync_transaction
    if sync_transaction is None or sync_transaction.origin is not SessionTransactionOrigin.BEGIN:
        raise FreeCourseMediaPromotionError("media promotion requires a caller-owned transaction")


def _stable_id(kind: str, tenant_id: UUID, source_id: UUID, activity_id: UUID) -> UUID:
    return uuid5(_IDENTITY_NAMESPACE, f"{kind}:{tenant_id}:{source_id}:{activity_id}")


def _source_prefix(tenant_id: UUID, asset_id: UUID, version_id: UUID) -> str:
    return f"tenants/{tenant_id}/media/video/{asset_id}/{version_id}/"


def _target_key(source_key: str, source_prefix: str, target_prefix: str) -> str:
    if not source_key.startswith(source_prefix):
        raise FreeCourseMediaPromotionError("the source object is outside its media identity")
    suffix = source_key[len(source_prefix) :]
    if not suffix or any(part in {"", ".", ".."} for part in suffix.split("/")):
        raise FreeCourseMediaPromotionError("the source object suffix is invalid")
    return target_prefix + suffix


def _metadata(storage: PrivateObjectStorage, key: str) -> StoredObjectMetadata:
    try:
        head = storage.head(key)
    except Exception as error:
        raise FreeCourseMediaPromotionError("private media metadata is unavailable") from error
    if head is None or not _SHA256.fullmatch(head.checksum_sha256):
        raise FreeCourseMediaPromotionError("private media bytes have no verified checksum")
    return head


class FreeCourseMediaPromotionApplication:
    """Promote one processed source video and bind it to one global activity."""

    def __init__(
        self,
        database: AsyncSession,
        *,
        service: MediaService,
        operations_tenant_id: UUID,
        public_tenant_id: UUID,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if operations_tenant_id == public_tenant_id:
            raise FreeCourseMediaPromotionError("operations and public tenants must differ")
        self.database = database
        self.service = service
        self.operations_tenant_id = operations_tenant_id
        self.public_tenant_id = public_tenant_id
        self.clock = clock or (lambda: datetime.now(UTC))

    async def apply(
        self,
        *,
        actor: ActorContext,
        publication_command_id: UUID,
        command_id: UUID,
        activity_id: UUID,
        source_asset_id: UUID,
        source_version_id: UUID,
        media_owner_person_id: UUID,
        approval_reference: str,
        supersedes_binding_id: UUID | None = None,
    ) -> FreeCourseMediaPromotionResult:
        _require_transaction(self.database)
        if actor.tenant_id != self.operations_tenant_id:
            raise FreeCourseMediaPromotionError("the operator must select the operations tenant")
        for value, label in (
            (publication_command_id, "publication command ID"),
            (command_id, "media command ID"),
            (activity_id, "activity ID"),
            (source_asset_id, "source asset ID"),
            (source_version_id, "source version ID"),
            (media_owner_person_id, "media owner ID"),
        ):
            if type(value) is not UUID or value.int == 0:
                raise FreeCourseMediaPromotionError(f"a non-zero {label} is required")
        if (
            not isinstance(approval_reference, str)
            or _SAFE_REFERENCE.fullmatch(approval_reference.strip()) is None
            or approval_reference != approval_reference.strip()
        ):
            raise FreeCourseMediaPromotionError("approval_reference is invalid")
        if supersedes_binding_id is not None and (
            type(supersedes_binding_id) is not UUID or supersedes_binding_id.int == 0
        ):
            raise FreeCourseMediaPromotionError("supersedes_binding_id must be a non-zero UUID")

        try:
            capabilities = await platform_projection(
                self.database,
                actor,
                operations_tenant_id=self.operations_tenant_id,
            )
        except CapabilityDenied as error:
            raise FreeCourseMediaPromotionError(str(error)) from error
        if not capabilities >= {"platform_catalog_write", "platform_catalog_publish"}:
            raise FreeCourseMediaPromotionError("platform catalog authority is required")

        existing = await self.database.get(AuditEvent, command_id)
        if existing is not None:
            return self._replay(
                existing,
                command_id=command_id,
                publication_command_id=publication_command_id,
                activity_id=activity_id,
                source_asset_id=source_asset_id,
                source_version_id=source_version_id,
                media_owner_person_id=media_owner_person_id,
                approval_reference=approval_reference,
                supersedes_binding_id=supersedes_binding_id,
                actor_person_id=actor.person_id,
            )

        publication = await self.database.get(AuditEvent, publication_command_id)
        if publication is None or publication.tenant_id != self.operations_tenant_id:
            raise FreeCourseMediaPromotionError("the canonical Free Course publication is required")
        if (
            publication.action != "catalog.free_course_published.v1"
            or publication.actor_person_id != actor.person_id
            or not isinstance(publication.payload, dict)
            or publication.payload.get("public_tenant_id") != str(self.public_tenant_id)
        ):
            raise FreeCourseMediaPromotionError(
                "the publication receipt does not match this tenant"
            )
        try:
            target_program_id = UUID(str(publication.payload["program_id"]))
            target_version_id = UUID(str(publication.payload["program_version_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise FreeCourseMediaPromotionError("the publication receipt is malformed") from error

        owner = await self.database.scalar(
            select(Membership)
            .join(Person, Person.id == Membership.person_id)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .where(
                Membership.tenant_id == self.public_tenant_id,
                Membership.person_id == media_owner_person_id,
                Membership.status == MembershipStatus.ACTIVE.value,
                Membership.ended_at.is_(None),
                Person.status == "active",
                Tenant.status == TenantStatus.ACTIVE.value,
            )
            .with_for_update(read=True)
        )
        if owner is None:
            raise FreeCourseMediaPromotionError("the media owner has no active public membership")
        if media_owner_person_id != actor.person_id:
            raise FreeCourseMediaPromotionError(
                "the media owner must be the authenticated operator"
            )

        activity = await self.database.scalar(
            select(Activity)
            .where(
                Activity.id == activity_id,
                Activity.program_id == target_program_id,
                Activity.program_version_id == target_version_id,
                Activity.scope == CatalogScope.GLOBAL.value,
                Activity.tenant_id.is_(None),
                Activity.owner_key == _ZERO_UUID,
                Activity.kind == ActivityKind.VIDEO.value,
            )
            .with_for_update()
        )
        version = await self.database.scalar(
            select(ProgramVersion).where(
                ProgramVersion.id == target_version_id,
                ProgramVersion.program_id == target_program_id,
                ProgramVersion.scope == CatalogScope.GLOBAL.value,
                ProgramVersion.tenant_id.is_(None),
                ProgramVersion.owner_key == _ZERO_UUID,
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
            )
        )
        if activity is None or version is None:
            raise FreeCourseMediaPromotionError("the target global video activity is unavailable")

        source_asset = await self.database.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.id == source_asset_id,
                MediaAsset.tenant_id == self.operations_tenant_id,
                MediaAsset.owner_person_id == actor.person_id,
                MediaAsset.purpose == MediaPurpose.VIDEO.value,
                MediaAsset.state == MediaLifecycle.READY.value,
            )
            .with_for_update()
        )
        source_version = await self.database.scalar(
            select(MediaVersion)
            .where(
                MediaVersion.id == source_version_id,
                MediaVersion.tenant_id == self.operations_tenant_id,
                MediaVersion.asset_id == source_asset_id,
                MediaVersion.purpose == MediaPurpose.VIDEO.value,
                MediaVersion.state == MediaLifecycle.READY.value,
            )
            .with_for_update()
        )
        if (
            source_asset is None
            or source_version is None
            or source_asset.current_version_id != source_version.id
            or source_version.actual_bytes is None
            or source_version.actual_bytes <= 0
            or source_version.checksum_sha256 is None
            or not _SHA256.fullmatch(source_version.checksum_sha256)
            or source_version.duration_seconds is None
            or not math.isfinite(source_version.duration_seconds)
            or source_version.duration_seconds <= 0
        ):
            raise FreeCourseMediaPromotionError("the source video is not a verified READY version")
        source_checksum = source_version.checksum_sha256
        assert source_checksum is not None

        renditions = tuple(
            (
                await self.database.scalars(
                    select(MediaRendition)
                    .where(
                        MediaRendition.tenant_id == self.operations_tenant_id,
                        MediaRendition.asset_id == source_asset.id,
                        MediaRendition.version_id == source_version.id,
                    )
                    .order_by(MediaRendition.id)
                )
            ).all()
        )
        if not renditions:
            raise FreeCourseMediaPromotionError("the READY source has no processed renditions")
        captions = await self.database.scalar(
            select(MediaCaptionTrack.id).where(
                MediaCaptionTrack.tenant_id == self.operations_tenant_id,
                MediaCaptionTrack.version_id == source_version.id,
            )
        )
        if captions is not None:
            raise FreeCourseMediaPromotionError(
                "caption promotion requires a separately reviewed target contract"
            )

        target_asset_id = _stable_id("asset", self.public_tenant_id, source_asset.id, activity.id)
        target_media_version_id = _stable_id(
            "version", self.public_tenant_id, source_version.id, activity.id
        )
        occupied = await self.database.scalar(
            select(MediaAsset).where(
                MediaAsset.tenant_id == self.public_tenant_id,
                MediaAsset.id == target_asset_id,
            )
        )
        occupied_version = await self.database.scalar(
            select(MediaVersion).where(
                MediaVersion.tenant_id == self.public_tenant_id,
                MediaVersion.id == target_media_version_id,
            )
        )
        if occupied is not None or occupied_version is not None:
            raise FreeCourseMediaPromotionConflict("the media promotion identity is occupied")

        target_prefix = _source_prefix(
            self.public_tenant_id, target_asset_id, target_media_version_id
        )
        source_prefix = _source_prefix(
            self.operations_tenant_id, source_asset.id, source_version.id
        )
        objects: list[tuple[str, str, str]] = [
            (
                source_version.object_key,
                _target_key(source_version.object_key, source_prefix, target_prefix),
                source_version.content_type,
            )
        ]
        objects.extend(
            (
                row.object_key,
                _target_key(row.object_key, source_prefix, target_prefix),
                row.content_type,
            )
            for row in renditions
        )
        copied: list[str] = []

        def materialize(database: Session) -> ActivityMediaBindingResponse:
            source_metadata = _metadata(self.service.storage, source_version.object_key)
            if (
                source_metadata.content_length != source_version.actual_bytes
                or source_metadata.checksum_sha256.lower() != source_checksum.lower()
            ):
                raise FreeCourseMediaPromotionError("the READY source bytes changed")
            copied_metadata: dict[str, StoredObjectMetadata] = {}
            for source_key, target_key, content_type in objects:
                source = _metadata(self.service.storage, source_key)
                result = self.service.storage.copy(
                    source_key=source_key,
                    destination_key=target_key,
                    content_type=content_type,
                )
                if (
                    result.content_length != source.content_length
                    or result.checksum_sha256.lower() != source.checksum_sha256.lower()
                    or result.content_type.lower().split(";", 1)[0]
                    != content_type.lower().split(";", 1)[0]
                ):
                    raise FreeCourseMediaPromotionError(
                        "the private media copy failed checksum verification"
                    )
                copied.append(target_key)
                copied_metadata[target_key] = result

            now = self.clock()
            target_asset = MediaAsset(
                id=target_asset_id,
                tenant_id=self.public_tenant_id,
                owner_person_id=media_owner_person_id,
                purpose=MediaPurpose.VIDEO.value,
                state=MediaLifecycle.PROCESSING.value,
                created_at=now,
                updated_at=now,
            )
            database.add(target_asset)
            database.flush()
            target_source_key = objects[0][1]
            target_source = copied_metadata[target_source_key]
            target_version = MediaVersion(
                id=target_media_version_id,
                tenant_id=self.public_tenant_id,
                asset_id=target_asset_id,
                version_number=1,
                purpose=MediaPurpose.VIDEO.value,
                state=MediaLifecycle.READY.value,
                content_type=source_version.content_type,
                declared_bytes=source_version.declared_bytes,
                actual_bytes=target_source.content_length,
                checksum_sha256=target_source.checksum_sha256,
                object_key=target_source_key,
                storage_version_id=target_source.storage_version_id,
                duration_seconds=source_version.duration_seconds,
                width=source_version.width,
                height=source_version.height,
                completion_policy=source_version.completion_policy,
                created_at=now,
                updated_at=now,
            )
            database.add(target_version)
            database.flush()
            for index, source_row in enumerate(renditions):
                target_key = objects[index + 1][1]
                copied_row = copied_metadata[target_key]
                database.add(
                    MediaRendition(
                        id=uuid5(target_media_version_id, f"rendition:{source_row.id}"),
                        tenant_id=self.public_tenant_id,
                        asset_id=target_asset_id,
                        version_id=target_media_version_id,
                        protocol=source_row.protocol,
                        content_type=source_row.content_type,
                        object_key=target_key,
                        width=source_row.width,
                        height=source_row.height,
                        bitrate_kbps=source_row.bitrate_kbps,
                    )
                )
                if (
                    copied_row.checksum_sha256.lower()
                    != _metadata(self.service.storage, target_key).checksum_sha256.lower()
                ):
                    raise FreeCourseMediaPromotionError("the copied rendition checksum changed")
            target_asset.current_version_id = target_media_version_id
            target_asset.state = MediaLifecycle.READY.value
            target_asset.updated_at = now
            database.flush()

            target_actor = ActorContext(
                person_id=media_owner_person_id,
                session_id=actor.session_id,
                tenant_id=self.public_tenant_id,
                permissions=frozenset(),
            )
            request = ActivityMediaBindingRequest(
                activity_id=activity.id,
                module_id=activity.module_id,
                program_version_id=version.id,
                program_id=version.program_id,
                program_scope=CatalogScope.GLOBAL.value,
                program_owner_key=_ZERO_UUID,
                asset_id=target_asset_id,
                version_id=target_media_version_id,
                approval_reference=approval_reference,
                supersedes_binding_id=supersedes_binding_id,
            )
            transaction = database.get_transaction()
            savepoint = database.get_nested_transaction()
            if transaction is None or savepoint is None:
                raise FreeCourseMediaPromotionError("the binding transaction is unavailable")
            authorization = FreeCourseMediaBindingAuthorization(
                database=database,
                transaction=transaction,
                savepoint=savepoint,
                actor=target_actor,
                service=self.service,
                request_json=request.model_dump_json(),
                tenant_id=self.public_tenant_id,
                activity_id=activity.id,
                asset_id=target_asset_id,
                version_id=target_media_version_id,
                seal=_SEAL,
            )
            try:
                binding = self.service.bind_activity_media(
                    database,
                    target_actor,
                    request,
                    idempotency_key=f"free-course-media:{command_id}",
                    free_course_authorization=authorization,
                )
            finally:
                authorization.active = False
            return binding

        try:
            async with self.database.begin_nested():
                binding = await self.database.run_sync(materialize)
        except Exception:
            for key in reversed(copied):
                with suppress(Exception):
                    self.service.storage.delete(key)
            raise

        payload = {
            "publication_command_id": str(publication_command_id),
            "activity_id": str(activity.id),
            "source_asset_id": str(source_asset.id),
            "source_version_id": str(source_version.id),
            "asset_id": str(target_asset_id),
            "version_id": str(target_media_version_id),
            "binding_id": str(binding.id),
            "public_tenant_id": str(self.public_tenant_id),
            "media_owner_person_id": str(media_owner_person_id),
            "approval_reference": approval_reference,
            "supersedes_binding_id": (
                str(supersedes_binding_id) if supersedes_binding_id is not None else None
            ),
            "media_status": _MEDIA_STATUS,
        }
        try:
            await AuditRepository(self.database).append(
                event_id=command_id,
                tenant_id=self.operations_tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action=_PROMOTION_ACTION,
                resource_type="global_program_activity",
                resource_id=activity.id,
                payload=payload,
                reason=approval_reference,
                now=self.clock(),
            )
        except Exception:
            for key in reversed(copied):
                with suppress(Exception):
                    self.service.storage.delete(key)
            raise
        return FreeCourseMediaPromotionResult(
            status="published",
            command_id=command_id,
            publication_command_id=publication_command_id,
            activity_id=activity.id,
            source_asset_id=source_asset.id,
            source_version_id=source_version.id,
            asset_id=target_asset_id,
            version_id=target_media_version_id,
            binding_id=binding.id,
            media_status=_MEDIA_STATUS,
        )

    def _replay(
        self,
        event: AuditEvent,
        *,
        command_id: UUID,
        publication_command_id: UUID,
        activity_id: UUID,
        source_asset_id: UUID,
        source_version_id: UUID,
        media_owner_person_id: UUID,
        approval_reference: str,
        supersedes_binding_id: UUID | None,
        actor_person_id: UUID,
    ) -> FreeCourseMediaPromotionResult:
        if (
            event.tenant_id != self.operations_tenant_id
            or event.action != _PROMOTION_ACTION
            or event.resource_type != "global_program_activity"
            or event.actor_person_id != actor_person_id
            or not isinstance(event.payload, dict)
        ):
            raise FreeCourseMediaPromotionConflict("the media command ID has another meaning")
        payload = event.payload
        expected = {
            "publication_command_id": str(publication_command_id),
            "activity_id": str(activity_id),
            "source_asset_id": str(source_asset_id),
            "source_version_id": str(source_version_id),
            "public_tenant_id": str(self.public_tenant_id),
            "media_owner_person_id": str(media_owner_person_id),
            "approval_reference": approval_reference,
            "supersedes_binding_id": (
                str(supersedes_binding_id) if supersedes_binding_id is not None else None
            ),
            "media_status": _MEDIA_STATUS,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise FreeCourseMediaPromotionConflict("the media command ID has another intent")
        try:
            asset_id = UUID(str(payload["asset_id"]))
            version_id = UUID(str(payload["version_id"]))
            binding_id = UUID(str(payload["binding_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise FreeCourseMediaPromotionConflict("the media receipt is malformed") from error
        return FreeCourseMediaPromotionResult(
            status="replayed",
            command_id=command_id,
            publication_command_id=publication_command_id,
            activity_id=activity_id,
            source_asset_id=source_asset_id,
            source_version_id=source_version_id,
            asset_id=asset_id,
            version_id=version_id,
            binding_id=binding_id,
            media_status=_MEDIA_STATUS,
        )


__all__ = [
    "FreeCourseMediaBindingAuthorization",
    "FreeCourseMediaPromotionApplication",
    "FreeCourseMediaPromotionConflict",
    "FreeCourseMediaPromotionError",
    "FreeCourseMediaPromotionResult",
]
