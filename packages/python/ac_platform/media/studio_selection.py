"""Course-scoped Studio video approval using the existing immutable binding ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.studio import StudioAuthorization
from ac_platform.catalog.models import Activity, ProgramVersion
from ac_platform.kernel.authz import ActorContext
from ac_platform.media.api_contracts import ActivityMediaBindingRequest
from ac_platform.media.errors import MediaBadRequest, MediaConflict, MediaForbidden, MediaNotFound
from ac_platform.media.models import (
    ActivityMediaBinding,
    MediaAsset,
    MediaUploadIntent,
    MediaVersion,
)
from ac_platform.media.service import MediaService
from ac_platform.media.studio_contract import (
    StudioVideoSelectionRequest,
    _technical_identity,
    project_studio_video_choice,
    studio_video_label,
)

_SEAL = object()


class StudioBoundVideo(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: UUID
    asset_id: UUID
    version_id: UUID
    label: str
    state: Literal["approved"] = "approved"


class StudioActivityVideoState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    activity_id: UUID
    version_status: str
    binding: StudioBoundVideo | None


class StudioVideoSaved(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    binding_id: UUID
    asset_id: UUID
    version_id: UUID
    state: Literal["approved", "superseded", "revoked"]
    replayed: bool


@dataclass(slots=True)
class StudioBindingAuthorization:
    """One synchronous invocation lease; never returned or accepted over HTTP.

    Minted only after fresh Studio authority and locked media eligibility. The
    caller owns root transaction and savepoint; the original ActorContext stays
    unchanged. Revoked immediately after the one existing binder invocation.
    """

    database: Session = field(repr=False)
    transaction: SessionTransaction = field(repr=False)
    savepoint: SessionTransaction = field(repr=False)
    actor: ActorContext = field(repr=False)
    service: MediaService = field(repr=False)
    request_json: str = field(repr=False)
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
            type(self) is not StudioBindingAuthorization
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
        ):
            raise MediaForbidden("The exact active Studio approval transaction is required.")


def _activity(
    database: Session,
    actor: ActorContext,
    program_id: UUID,
    activity_id: UUID,
) -> tuple[Activity, ProgramVersion]:
    activity = database.scalar(
        select(Activity)
        .where(
            Activity.id == activity_id,
            Activity.program_id == program_id,
            Activity.scope == "tenant",
            Activity.tenant_id == actor.tenant_id,
            Activity.owner_key == actor.tenant_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if activity is None:
        raise MediaNotFound("The video lesson is unavailable in this course.")
    if activity.kind != "VIDEO":
        raise MediaBadRequest("Only video lessons can receive a video selection.")
    version = database.scalar(
        select(ProgramVersion)
        .where(
            ProgramVersion.id == activity.program_version_id,
            ProgramVersion.program_id == program_id,
            ProgramVersion.scope == "tenant",
            ProgramVersion.tenant_id == actor.tenant_id,
            ProgramVersion.owner_key == actor.tenant_id,
        )
        .execution_options(populate_existing=True)
    )
    if version is None:
        raise MediaNotFound("The course version is unavailable.")
    return activity, version


def _bindings(actor: ActorContext, activity: Activity) -> Select[tuple[ActivityMediaBinding]]:
    return select(ActivityMediaBinding).where(
        ActivityMediaBinding.tenant_id == actor.tenant_id,
        ActivityMediaBinding.activity_id == activity.id,
        ActivityMediaBinding.module_id == activity.module_id,
        ActivityMediaBinding.program_version_id == activity.program_version_id,
        ActivityMediaBinding.program_id == activity.program_id,
        ActivityMediaBinding.program_scope == activity.scope,
        ActivityMediaBinding.program_owner_key == activity.owner_key,
    )


class StudioVideoSelection:
    def __init__(self, database: AsyncSession, service: MediaService) -> None:
        self.database, self.service = database, service

    async def current(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        activity_id: UUID,
    ) -> StudioActivityVideoState:
        await StudioAuthorization(self.database).require(
            actor, "catalog_read", program_id=program_id
        )

        def read(database: Session) -> StudioActivityVideoState:
            activity, version = _activity(database, actor, program_id, activity_id)
            binding = database.scalar(
                _bindings(actor, activity).where(ActivityMediaBinding.state == "approved")
            )
            result = None
            if binding is not None:
                media_version = database.scalar(
                    select(MediaVersion).where(
                        MediaVersion.id == binding.version_id,
                        MediaVersion.tenant_id == actor.tenant_id,
                        MediaVersion.asset_id == binding.asset_id,
                    )
                )
                if media_version is None:
                    raise MediaConflict("Video details changed. Refresh this lesson.")
                intent = database.scalar(
                    select(MediaUploadIntent)
                    .where(
                        MediaUploadIntent.tenant_id == actor.tenant_id,
                        MediaUploadIntent.asset_id == binding.asset_id,
                        MediaUploadIntent.version_id == binding.version_id,
                    )
                    .order_by(MediaUploadIntent.created_at.desc(), MediaUploadIntent.id.desc())
                    .limit(1)
                )
                result = StudioBoundVideo(
                    binding_id=binding.id,
                    asset_id=binding.asset_id,
                    version_id=binding.version_id,
                    label=studio_video_label(media_version.version_number, intent),
                )
            return StudioActivityVideoState(
                activity_id=activity.id, version_status=version.status, binding=result
            )

        return await self.database.run_sync(read)

    async def select(
        self,
        actor: ActorContext,
        *,
        program_id: UUID,
        activity_id: UUID,
        body: StudioVideoSelectionRequest,
        idempotency_key: str,
        request_id: str | None = None,
    ) -> StudioVideoSaved:
        if not idempotency_key.strip() or len(idempotency_key) > 128:
            raise MediaBadRequest("A bounded Idempotency-Key is required for video selection.")
        async with self.database.begin_nested():
            await StudioAuthorization(self.database).require(
                actor, "catalog_write", program_id=program_id
            )
            result = await self.database.run_sync(
                lambda database: self._select(
                    database, actor, program_id, activity_id, body, idempotency_key
                )
            )
            if not result.replayed:
                await AuditRepository(self.database).append_for_actor(
                    actor,
                    action="media.activity_binding_approved",
                    resource_type="activity_media_binding",
                    resource_id=result.binding_id,
                    payload={"status": "approved"},
                    request_id=request_id,
                )
            return result

    def _select(
        self,
        database: Session,
        actor: ActorContext,
        program_id: UUID,
        activity_id: UUID,
        body: StudioVideoSelectionRequest,
        key: str,
    ) -> StudioVideoSaved:
        activity, catalog = _activity(database, actor, program_id, activity_id)
        if catalog.status not in {"published", "superseded"}:
            raise MediaConflict("Publish the course content before approving lesson delivery.")
        request = ActivityMediaBindingRequest(
            activity_id=activity.id,
            module_id=activity.module_id,
            program_version_id=catalog.id,
            program_id=program_id,
            program_scope="tenant",
            program_owner_key=actor.tenant_id,
            asset_id=body.asset_id,
            version_id=body.version_id,
            approval_reference=body.approval_reference,
            supersedes_binding_id=body.expected_binding_id,
        )
        # Receipts are scoped to the original actor/key, not today's current binding.
        # Exact retry remains resolvable after another approval supersedes it.
        receipt = database.scalar(
            select(ActivityMediaBinding)
            .where(
                ActivityMediaBinding.tenant_id == actor.tenant_id,
                ActivityMediaBinding.approved_by_person_id == actor.person_id,
                ActivityMediaBinding.idempotency_key == key,
            )
            .execution_options(populate_existing=True)
        )
        if receipt is not None:
            if (
                any(
                    getattr(receipt, name) != getattr(request, name)
                    for name in (
                        "activity_id",
                        "module_id",
                        "program_version_id",
                        "program_id",
                        "program_scope",
                        "program_owner_key",
                        "asset_id",
                        "version_id",
                        "approval_reference",
                        "supersedes_binding_id",
                    )
                )
                or receipt.activity_version != f"activity:{activity.id}"
            ):
                raise MediaConflict(
                    "This video selection key is already used for different details."
                )
            return StudioVideoSaved(
                binding_id=receipt.id,
                asset_id=receipt.asset_id,
                version_id=receipt.version_id,
                state=receipt.state,
                replayed=True,
            )

        tenant_id = actor.tenant_id
        if tenant_id is None or _technical_identity(tenant_id, body.asset_id, body.version_id):
            raise MediaForbidden("Technical demonstration films are not course-library choices.")
        asset = database.scalar(
            select(MediaAsset)
            .where(
                MediaAsset.id == body.asset_id,
                MediaAsset.tenant_id == tenant_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        version = database.scalar(
            select(MediaVersion)
            .where(
                MediaVersion.id == body.version_id,
                MediaVersion.asset_id == body.asset_id,
                MediaVersion.tenant_id == tenant_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if asset is None or version is None:
            raise MediaNotFound("The selected video is unavailable.")
        try:
            project_studio_video_choice(tenant_id, asset, version)
        except ValueError as error:
            raise MediaConflict("The selected video changed. Refresh the library.") from error
        if asset.owner_person_id != actor.person_id:
            donor = database.scalar(
                select(ActivityMediaBinding)
                .join(
                    ProgramVersion,
                    ProgramVersion.id == ActivityMediaBinding.program_version_id,
                )
                .where(
                    ActivityMediaBinding.tenant_id == tenant_id,
                    ActivityMediaBinding.program_id == program_id,
                    ActivityMediaBinding.program_scope == "tenant",
                    ActivityMediaBinding.program_owner_key == tenant_id,
                    ActivityMediaBinding.asset_id == asset.id,
                    ActivityMediaBinding.version_id == version.id,
                    ActivityMediaBinding.state == "approved",
                    ProgramVersion.program_id == program_id,
                    ProgramVersion.tenant_id == tenant_id,
                    ProgramVersion.scope == "tenant",
                    ProgramVersion.owner_key == tenant_id,
                    ProgramVersion.status.in_(("published", "superseded")),
                )
                .order_by(ActivityMediaBinding.id)
                .limit(1)
                .execution_options(populate_existing=True)
                .with_for_update(read=True, of=ActivityMediaBinding)
            )
            if donor is None:
                raise MediaForbidden("The selected video is not available to this course editor.")
        current = database.scalar(
            _bindings(actor, activity)
            .where(ActivityMediaBinding.state == "approved")
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if (current.id if current is not None else None) != body.expected_binding_id:
            raise MediaConflict(
                "The lesson video changed. Review the current selection before saving."
            )
        if current is not None and _technical_identity(
            tenant_id, current.asset_id, current.version_id
        ):
            raise MediaForbidden(
                "Technical demonstration films use their dedicated publication workflow."
            )
        transaction, savepoint = database.get_transaction(), database.get_nested_transaction()
        if transaction is None or savepoint is None:
            raise MediaForbidden("The active Studio approval transaction is required.")
        lease = StudioBindingAuthorization(
            database, transaction, savepoint, actor, self.service, request.model_dump_json(), _SEAL
        )
        try:
            binding = self.service.bind_activity_media(
                database, actor, request, idempotency_key=key, studio_authorization=lease
            )
        finally:
            lease.active = False
        return StudioVideoSaved(
            binding_id=binding.id,
            asset_id=binding.asset_id,
            version_id=binding.version_id,
            state=binding.state,
            replayed=False,
        )
