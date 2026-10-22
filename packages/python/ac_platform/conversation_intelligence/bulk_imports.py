"""Batch decisions are durable; calls still use normal source-bound acquisition."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationError,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.bulk_import_contracts import ImportConfirmation
from ac_platform.conversation_intelligence.bulk_import_models import (
    ConversationRecordingImport,
    ConversationRecordingImportItem,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationCommand
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile import (
    SalesXrayProfileUnavailable,
    get_sales_xray_profile,
)
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership

IMPORT_LIFETIME = timedelta(days=7)
IMPORT_SOURCE_NAMESPACE = UUID("3d11e2cc-3b70-4f8d-ae49-52b5d7cec676")
IMPORT_ACTION = "recording_import_confirmed"
MEMBER_SETUP_REQUIRED = (
    "This member must add their name and phone number in Sales X-Ray before their calls "
    "can be analysed. Their recordings wait in this import for up to 7 days; resume once "
    "they have."
)


def path_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def import_submission_id(tenant_id: UUID, source_sha256: str) -> UUID:
    return uuid5(IMPORT_SOURCE_NAMESPACE, f"{tenant_id}:{source_sha256}")


@dataclass(frozen=True)
class ImportReference:
    batch_id: UUID
    item_index: int


def batch_intent(
    batch: ConversationRecordingImport, items: list[ConversationRecordingImportItem]
) -> dict[str, Any]:
    return {
        "manifest_sha256": batch.manifest_sha256,
        "policy_sha256": batch.policy_sha256,
        "rights_confirmed": True,
        "items": [
            {
                "index": item.item_index,
                "path_sha256": item.path_sha256,
                "folder_sha256": item.folder_sha256,
                "source_sha256": item.source_sha256,
                "source_bytes": item.source_bytes,
                "person_id": None if item.person_id is None else str(item.person_id),
            }
            for item in items
        ],
    }


async def verify_batch_consent(
    database: AsyncSession,
    batch: ConversationRecordingImport,
    items: list[ConversationRecordingImportItem],
) -> None:
    receipt = await database.scalar(
        select(ConversationCommand)
        .where(
            ConversationCommand.tenant_id == batch.tenant_id,
            ConversationCommand.person_id == batch.uploader_person_id,
            ConversationCommand.action == IMPORT_ACTION,
            ConversationCommand.result_id == batch.id,
            ConversationCommand.intent_sha256 == content_hash(batch_intent(batch, items)),
        )
        .limit(1)
    )
    if (
        receipt is None
        or utc(batch.expires_at) - utc(batch.created_at) != IMPORT_LIFETIME
        or utc(receipt.created_at) != utc(batch.created_at)
        or len(items) != batch.total_files
        or sum(item.source_bytes for item in items) != batch.total_bytes
        or [item.item_index for item in items] != list(range(batch.total_files))
    ):
        raise ConversationDenied("The exact batch consent receipt is unavailable.")


class RecordingImports:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership, self.database = ownership, ownership.database
        self.application = ConversationApplication(self.database, clock=ownership.clock)

    async def administrator(
        self, actor: ActorContext | None, *, shared_identity_locks: bool = False
    ) -> datetime:
        if (
            actor is None
            or type(actor) is not ActorContext
            or actor.tenant_id != self.ownership.tenant_id
        ):
            raise ConversationDenied("Select an organisation where you are an owner or admin.")
        now = await self.application.admit(actor, shared_identity_locks=shared_identity_locks)
        if not await self.ownership.organisation_call_reader(actor):
            raise ConversationDenied("Select an organisation where you are an owner or admin.")
        return now

    async def member(self, person_id: UUID | None) -> None:
        if person_id is None:
            raise ConversationConflict("Confirm a current member before importing this recording.")
        person = await self.database.get(Person, person_id, populate_existing=True)
        member = await self.database.get(
            Membership, (self.ownership.tenant_id, person_id), populate_existing=True
        )
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or member.role not in {"owner", "admin", "member"}
        ):
            raise ConversationDenied(
                "The confirmed member is no longer available in this organisation."
            )

    async def member_setup_complete(self, person_id: UUID) -> bool:
        # The worker holds a call whose owner has no complete Sales X-Ray profile
        # (name and phone) and nothing resumes the hold, so the upload's one-hour
        # source budget expires unprocessed (46 imported calls, 18 Oct 2026).
        try:
            profile = await get_sales_xray_profile(self.database, person_id=person_id)
        except SalesXrayProfileUnavailable:
            return False
        return profile.profile_complete

    async def require_member_setup(self, person_id: UUID | None) -> None:
        """Refuse new import work before any minutes, lease or job exist."""
        if person_id is None or not await self.member_setup_complete(person_id):
            raise ConversationConflict(MEMBER_SETUP_REQUIRED)

    async def items(self, batch_id: UUID) -> list[ConversationRecordingImportItem]:
        return list(
            (
                await self.database.scalars(
                    select(ConversationRecordingImportItem)
                    .where(
                        ConversationRecordingImportItem.batch_id == batch_id,
                        ConversationRecordingImportItem.tenant_id == self.ownership.tenant_id,
                    )
                    .order_by(ConversationRecordingImportItem.item_index)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def create(
        self, actor: ActorContext, confirmation: ImportConfirmation, *, policy_sha256: str, key: str
    ) -> dict[str, Any]:
        now = await self.administrator(actor)
        if confirmation.policy_sha256 != policy_sha256:
            raise ConversationConflict("The upload terms changed. Review them and try again.")
        await self.ownership.sessions._admit(mutation=True)
        owners = {
            folder.folder: None if folder.person_id is None else UUID(folder.person_id)
            for folder in confirmation.folders
        }
        batch = ConversationRecordingImport(
            id=uuid4(),
            tenant_id=self.ownership.tenant_id,
            uploader_person_id=actor.person_id,
            uploader_session_id=actor.session_id,
            manifest_sha256=confirmation.manifest_sha256,
            policy_sha256=confirmation.policy_sha256,
            total_files=len(confirmation.manifest.files),
            total_bytes=sum(source.source_bytes for source in confirmation.manifest.files),
            created_at=now,
            expires_at=now + IMPORT_LIFETIME,
        )
        items = [
            ConversationRecordingImportItem(
                batch_id=batch.id,
                item_index=index,
                tenant_id=batch.tenant_id,
                person_id=owners[source.folder],
                source_sha256=source.source_sha256,
                source_bytes=source.source_bytes,
                path_sha256=path_digest(source.relative_path),
                folder_sha256=path_digest(source.folder),
                submission_id=import_submission_id(batch.tenant_id, source.source_sha256),
                reused=False,
            )
            for index, source in enumerate(confirmation.manifest.files)
        ]
        intent = batch_intent(batch, items)
        previous = await self.application._replay(actor, key, IMPORT_ACTION, intent)
        if previous is not None:
            if previous.result_id is None:
                raise ConversationConflict("This batch receipt is unavailable.")
            return await self.progress(actor, previous.result_id)
        for member_id in set(owners.values()) - {None}:
            await self.member(member_id)
        self.database.add(batch)
        await self.database.flush()
        self.database.add_all(items)
        await self.database.flush()
        await self.application._receipt(
            actor,
            key,
            IMPORT_ACTION,
            intent,
            batch.id,
            now,
            resource_type="conversation_recording_import",
        )
        return await self.progress(actor, batch.id)

    async def batch(
        self, actor: ActorContext, batch_id: UUID, *, shared_identity_locks: bool = False
    ) -> ConversationRecordingImport:
        await self.administrator(actor, shared_identity_locks=shared_identity_locks)
        batch = await self.database.scalar(
            select(ConversationRecordingImport)
            .where(
                ConversationRecordingImport.id == batch_id,
                ConversationRecordingImport.tenant_id == self.ownership.tenant_id,
            )
            .execution_options(populate_existing=True)
        )
        if batch is None:
            raise ConversationNotFound("This recording import is unavailable.")
        return batch

    async def authorize(
        self,
        actor: ActorContext,
        reference: ImportReference,
        *,
        shared_identity_locks: bool = False,
    ) -> tuple[ConversationRecordingImport, ConversationRecordingImportItem]:
        batch = await self.batch(
            actor, reference.batch_id, shared_identity_locks=shared_identity_locks
        )
        if batch.uploader_person_id != actor.person_id:
            raise ConversationDenied("Only this batch's current uploader can resume its import.")
        if utc(batch.expires_at) <= utc(self.ownership.clock()):
            raise ConversationConflict("This batch expired. Preview the folder again to continue.")
        item = await self.database.get(
            ConversationRecordingImportItem,
            (batch.id, reference.item_index),
            populate_existing=True,
        )
        if item is None or item.tenant_id != batch.tenant_id:
            raise ConversationNotFound("This import item is unavailable.")
        await self.member(item.person_id)
        await self.consent(batch)
        return batch, item

    async def consent(self, batch: ConversationRecordingImport) -> None:
        await verify_batch_consent(self.database, batch, await self.items(batch.id))

    async def progress(self, actor: ActorContext, batch_id: UUID) -> dict[str, Any]:
        batch = await self.batch(actor, batch_id, shared_identity_locks=True)
        now = utc(self.ownership.clock())
        rows = []
        items = await self.items(batch.id)
        unavailable_members = set()
        setup_pending = set()
        for person_id in {item.person_id for item in items if item.usage_id is None} - {None}:
            try:
                await self.member(person_id)
            except ConversationDenied:
                unavailable_members.add(person_id)
                continue
            if not await self.member_setup_complete(person_id):
                setup_pending.add(person_id)
        for item in items:
            waiting_setup = (
                utc(batch.expires_at) > now
                and item.usage_id is None
                and item.person_id in setup_pending
            )
            result: dict[str, Any] = {
                "item_index": item.item_index,
                "path_sha256": item.path_sha256,
                "folder_sha256": item.folder_sha256,
                "person_id": None if item.person_id is None else str(item.person_id),
                "confirmed_person_id": None if item.person_id is None else str(item.person_id),
                "source_sha256": item.source_sha256,
                "source_bytes": item.source_bytes,
                "submission_id": None,
                "upload_submission_id": str(item.submission_id),
                "state": "expired"
                if utc(batch.expires_at) <= now
                else "needs_member"
                if item.person_id is None or item.person_id in unavailable_members or waiting_setup
                else "awaiting_upload",
                # Old clients skip needs_member; newer ones say who must finish setup.
                "member_setup_required": waiting_setup,
                "run_state": None,
                "current_stage": None,
                "minute_state": None,
                "local_state": None,
                "plan_state": None,
                "terminal_state": None,
                "retry_available": False,
            }
            if item.usage_id is not None:
                usage = await self.database.get(ConversationAcquisitionUsage, item.usage_id)
                if (
                    usage is not None
                    and usage.tenant_id == batch.tenant_id
                    and usage.source_sha256 == item.source_sha256
                ):
                    result["submission_id"] = str(usage.submission_id)
                    result["person_id"] = str(usage.person_id)
                    try:
                        progress = await AcquisitionReports(self.ownership).progress(
                            usage.submission_id,
                            actor=actor,
                            allow_organisation_read=True,
                            shared_identity_locks=True,
                        )
                        result.update(
                            {
                                field: progress.get(field)
                                for field in (
                                    "run_state",
                                    "current_stage",
                                    "minute_state",
                                    "local_state",
                                    "plan_state",
                                    "terminal_state",
                                )
                            }
                        )
                        result["state"] = (
                            "already_imported"
                            if item.reused
                            else progress.get("run_state") or "unavailable"
                        )
                        if result["run_state"] == "failed" and not item.reused:
                            from ac_platform.conversation_intelligence import (
                                bulk_import_ownership,
                            )

                            try:
                                await bulk_import_ownership.ImportOwnership(
                                    self.ownership,
                                    actor,
                                    ImportReference(batch.id, item.item_index),
                                ).require_submission_owner(
                                    usage.submission_id, actor=actor, shared_identity_locks=True
                                )
                                result["retry_available"] = True
                            except ConversationError:
                                pass
                    except ConversationError:
                        result["state"] = "already_imported" if item.reused else "unavailable"
                else:
                    result["state"] = "unavailable"
            rows.append(result)
        states = [row["state"] for row in rows]
        terminal = {"done", "failed", "already_imported", "expired"}
        finished = bool(states) and all(state in terminal for state in states)
        return {
            "batch_id": str(batch.id),
            "tenant_id": str(batch.tenant_id),
            "manifest_sha256": batch.manifest_sha256,
            "policy_sha256": batch.policy_sha256,
            "uploader_person_id": str(batch.uploader_person_id),
            "created_at": utc(batch.created_at).isoformat(),
            "expires_at": utc(batch.expires_at).isoformat(),
            "total_files": batch.total_files,
            "total_bytes": batch.total_bytes,
            "state": "finished"
            if finished
            else "expired"
            if utc(batch.expires_at) <= now
            else "in_progress",
            "terminal_state": "failed"
            if utc(batch.expires_at) <= now
            and not finished
            or finished
            and any(state in {"failed", "expired"} for state in states)
            else "done"
            if finished
            else None,
            "files": rows,
        }

    async def fair_admission(self, submission_id: UUID, uploader: ActorContext) -> None:
        # All callers hold the ordinary tenant mutation lock and have already
        # authorised this exact batch/item. Minute outcomes never own capacity.
        from ac_platform.conversation_intelligence.bulk_import_admission import active_local_item

        active = await self.database.scalar(
            active_local_item(
                tenant_id=self.ownership.tenant_id,
                uploader_id=uploader.person_id,
                submission_id=submission_id,
                now=utc(self.ownership.clock()),
            )
        )
        if active is not None:
            raise ConversationConflict(
                "The previous batch recording is still processing. "
                "Other callers can continue uploading."
            )


async def require_import_execution(
    database: AsyncSession, usage: ConversationAcquisitionUsage, now: datetime
) -> None:
    """Verify batch provenance; the normal lease gate rechecks the human call owner."""
    if usage.submission_id != import_submission_id(usage.tenant_id, usage.source_sha256):
        return
    item = await database.scalar(
        select(ConversationRecordingImportItem).where(
            ConversationRecordingImportItem.usage_id == usage.id,
            ConversationRecordingImportItem.reused.is_(False),
        )
    )
    if item is None:
        return
    batch = await database.get(ConversationRecordingImport, item.batch_id)
    if (
        batch is None
        or batch.tenant_id != usage.tenant_id
        or item.tenant_id != usage.tenant_id
        or item.person_id != usage.person_id
        or item.source_sha256 != usage.source_sha256
        or item.submission_id != usage.submission_id
        or not utc(batch.created_at) <= utc(usage.created_at) < utc(batch.expires_at)
    ):
        raise ConversationDenied("The recording import's source authority is unavailable.")
    items = list(
        (
            await database.scalars(
                select(ConversationRecordingImportItem)
                .where(
                    ConversationRecordingImportItem.batch_id == batch.id,
                    ConversationRecordingImportItem.tenant_id == batch.tenant_id,
                )
                .order_by(ConversationRecordingImportItem.item_index)
            )
        ).all()
    )
    await verify_batch_consent(database, batch, items)
