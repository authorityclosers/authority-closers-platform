"""AC session/tenant-bound recording commands on the existing transaction and outbox."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.async_io import join_thread
from ac_platform.conversation_intelligence.checkpoints import Checkpoint, content_hash
from ac_platform.conversation_intelligence.contracts import RecordingIntent, RunIntent
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    reserve,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationReportDraft,
    ConversationReview,
    ConversationRun,
)
from ac_platform.conversation_intelligence.signals import NATIVE_SOURCE_SHA256, _feature_metadata
from ac_platform.conversation_intelligence.storage import (
    ObjectKey,
    ObjectKind,
    RecordingObjectStorage,
    StorageError,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from ac_platform.tenancy.models import Membership, Tenant

LOCAL_JOB = "conversation.inspect_local.v1"
DELETE_JOB = "conversation.erase_local.v1"
AUDIOATLAS_RECIPE = "audioatlas-48000-v1"
AUDIOATLAS_HOSTED_RECIPE = "audioatlas-16000-v1"
AUDIOATLAS_RECIPES = {AUDIOATLAS_RECIPE: 48000, AUDIOATLAS_HOSTED_RECIPE: 16000}


class ConversationError(ValueError):
    status = 422


class ConversationDenied(ConversationError):
    status = 403


class ConversationNotFound(ConversationError):
    status = 404


class ConversationConflict(ConversationError):
    status = 409


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class ConversationApplication:
    def __init__(
        self,
        database: AsyncSession,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.database = database
        self.clock = clock

    async def admit(self, actor: ActorContext) -> datetime:
        tx = self.database.get_transaction()
        sync_tx = tx.sync_transaction if tx is not None else None
        if sync_tx is None or sync_tx.origin is not SessionTransactionOrigin.BEGIN:
            raise ConversationError("A caller-owned transaction is required.")
        if actor.tenant_id is None:
            raise ConversationDenied("Select your AC workspace.")
        # The same person/session locks as existing AC commands serialize revocation
        # and idempotency. Never trust a previously hydrated actor as current authority.
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == actor.person_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        session = await self.database.scalar(
            select(IdentitySession)
            .where(
                IdentitySession.id == actor.session_id,
                IdentitySession.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == actor.tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.person_id == actor.person_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        now = utc(self.clock())
        if (
            person is None
            or person.status != "active"
            or person.email_verified_at is None
            or session is None
            or session.revoked_at is not None
            or utc(session.expires_at) <= now
            or session.selected_tenant_id != actor.tenant_id
            or tenant is None
            or tenant.status != "active"
            or member is None
            or member.status != "active"
            or member.ended_at is not None
        ):
            raise ConversationDenied("A current AC workspace session is required.")
        return now

    async def _recording(self, actor: ActorContext, recording_id: UUID) -> ConversationRecording:
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id == actor.tenant_id,
                ConversationRecording.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if recording is None:
            raise ConversationNotFound("Recording not found.")
        return recording

    async def _permission(
        self,
        actor: ActorContext,
        permission_id: UUID,
        sha: str,
        now: datetime,
    ) -> ConversationPermission:
        permission = await self.database.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == permission_id,
                ConversationPermission.tenant_id == actor.tenant_id,
                ConversationPermission.person_id == actor.person_id,
                ConversationPermission.source_sha256 == sha,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            permission is None
            or permission.revoked_at is not None
            or permission.provider != "local"
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
            or not permission.permission_reference
            or not permission.retention_reference
        ):
            raise ConversationDenied("Current permission for this exact recording is required.")
        return permission

    @staticmethod
    def _view(recording: ConversationRecording) -> dict[str, Any]:
        return {
            "id": str(recording.id),
            "state": recording.state,
            "source_revision": str(recording.source_revision),
            "source_sha256": recording.source_sha256,
            "source_bytes": recording.source_bytes,
            "content_type": recording.content_type,
            "created_at": utc(recording.created_at).isoformat(),
        }

    async def _replay(
        self,
        actor: ActorContext,
        key: str,
        action: str,
        intent: dict[str, Any],
    ) -> ConversationCommand | None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", key):
            raise ConversationError("A valid Idempotency-Key is required.")
        command = await self.database.scalar(
            select(ConversationCommand).where(
                ConversationCommand.tenant_id == actor.tenant_id,
                ConversationCommand.person_id == actor.person_id,
                ConversationCommand.key == key,
            )
        )
        if command is not None and (
            command.action != action or command.intent_sha256 != content_hash(intent)
        ):
            raise ConversationConflict("The request key belongs to a different command.")
        return command

    async def _receipt(
        self,
        actor: ActorContext,
        key: str,
        action: str,
        intent: dict[str, Any],
        result_id: UUID,
        now: datetime,
        *,
        resource_type: str = "conversation_recording",
    ) -> None:
        digest = content_hash(intent)
        audit = await AuditRepository(self.database).append_for_actor(
            actor,
            action=f"conversation.{action}",
            resource_type=resource_type,
            resource_id=result_id,
            payload={"intent_sha256": digest},
            now=now,
        )
        self.database.add(
            ConversationCommand(
                id=uuid4(),
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                key=key,
                action=action,
                intent_sha256=digest,
                result_id=result_id,
                audit_event_id=audit.id,
                created_at=now,
            )
        )
        await self.database.flush()

    async def register(
        self,
        actor: ActorContext,
        intent: RecordingIntent,
        *,
        key: str,
    ) -> dict[str, Any]:
        now = await self.admit(actor)
        payload = intent.model_dump(mode="json")
        await self._permission(actor, intent.permission_reference, intent.source_sha256, now)
        replay = await self._replay(actor, key, "register", payload)
        if replay is not None and replay.result_id is not None:
            return self._view(await self._recording(actor, replay.result_id))
        recording = ConversationRecording(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            permission_id=intent.permission_reference,
            request_key=key,
            intent_sha256=content_hash(payload),
            source_sha256=intent.source_sha256,
            source_bytes=intent.source_bytes,
            content_type=intent.content_type,
            source_revision=1,
            generation=1,
            state="awaiting_upload",
            created_at=now,
        )
        self.database.add(recording)
        await self.database.flush()
        await self._receipt(actor, key, "register", payload, recording.id, now)
        return self._view(recording)

    async def get(self, actor: ActorContext, recording_id: UUID) -> dict[str, Any]:
        now = await self.admit(actor)
        recording = await self._recording(actor, recording_id)
        if recording.state in {"deleting", "deleted"}:
            raise ConversationNotFound("Recording not found.")
        await self._permission(actor, recording.permission_id, recording.source_sha256, now)
        return self._view(recording)

    async def store_source(
        self,
        actor: ActorContext,
        recording_id: UUID,
        *,
        chunks: Iterable[bytes],
        storage: RecordingObjectStorage,
    ) -> dict[str, Any]:
        """Private intake port; the HTTP upload transport is separately configured."""
        now = await self.admit(actor)
        recording = await self._recording(actor, recording_id)
        await self._permission(actor, recording.permission_id, recording.source_sha256, now)
        if recording.state not in {"awaiting_upload", "ready"}:
            raise ConversationConflict("This recording no longer accepts media.")
        permission_row = await self.database.get(ConversationPermission, recording.permission_id)
        if permission_row is not None and permission_row.permission_reference.startswith(
            "intake-consent-v1:"
        ):
            from ac_platform.conversation_intelligence.intake import require_intake_acceptance

            quoted = await self.database.get(
                ConversationQuote, UUID(permission_row.permission_reference.split(":", 1)[1])
            )
            if quoted is None or quoted.revoked_at is not None:
                raise ConversationDenied("This recording's quote is unavailable.")
            await require_intake_acceptance(self, actor, quoted)
        object_key = ObjectKey(
            recording.tenant_id, recording.id, recording.id, ObjectKind.SOURCE_AUDIO
        )

        def write() -> None:
            try:
                storage.put(
                    object_key,
                    chunks,
                    expected_sha256=recording.source_sha256,
                    expected_bytes=recording.source_bytes,
                )
            except StorageError as error:
                if str(error) != "storage_object_exists":
                    raise
                # A crash after publication but before commit is recoverable only
                # when the preexisting immutable object has the exact source hash/size.
                existing_size = sum(
                    len(block)
                    for block in storage.iter_bytes(
                        object_key,
                        expected_sha256=recording.source_sha256,
                    )
                )
                if existing_size != recording.source_bytes:
                    raise StorageError("storage_digest_mismatch") from None

        await join_thread(write)
        recording.state = "ready"
        key = f"source:{recording.id}"
        payload = {"recording_id": str(recording.id), "source_sha256": recording.source_sha256}
        if await self._replay(actor, key, "source_stored", payload) is None:
            await self._receipt(actor, key, "source_stored", payload, recording.id, now)
        return self._view(recording)

    async def checkpoints(self, actor: ActorContext, recording_id: UUID) -> list[dict[str, Any]]:
        await self.get(actor, recording_id)
        rows = (
            await self.database.scalars(
                select(ConversationCheckpoint)
                .where(
                    ConversationCheckpoint.recording_id == recording_id,
                    ConversationCheckpoint.tenant_id == actor.tenant_id,
                    ConversationCheckpoint.person_id == actor.person_id,
                    ConversationCheckpoint.erased_at.is_(None),
                )
                .order_by(ConversationCheckpoint.created_at, ConversationCheckpoint.id)
                .limit(100)
            )
        ).all()
        return [
            {"id": str(row.id), "manifest": row.manifest, "payload": row.payload} for row in rows
        ]

    async def request_deletion(
        self,
        actor: ActorContext,
        recording_id: UUID,
        *,
        key: str,
    ) -> dict[str, Any]:
        now = await self.admit(actor)
        recording = await self._recording(actor, recording_id)
        intent = {"recording_id": str(recording_id)}
        replay = await self._replay(actor, key, "delete", intent)
        if replay is not None or recording.state in {"deleting", "deleted"}:
            return {"id": str(recording.id), "state": recording.state}
        # Revokes reads and fences any delayed worker BEFORE storage erasure.
        recording.state = "deleting"
        recording.generation += 1
        await JobRepository(self.database).enqueue(
            kind=DELETE_JOB,
            dedupe_key=f"conversation:erase:{recording.id}:{recording.generation}",
            tenant_id=recording.tenant_id,
            payload={"recording_id": str(recording.id), "generation": recording.generation},
            external_side_effect=False,
        )
        await self._receipt(actor, key, "delete", intent, recording.id, now)
        return {"id": str(recording.id), "state": recording.state}

    async def request_run(
        self,
        actor: ActorContext,
        intent: RunIntent,
        *,
        key: str,
    ) -> dict[str, Any]:
        now = await self.admit(actor)
        recording = await self._recording(actor, intent.recording_id)
        await self._permission(actor, recording.permission_id, recording.source_sha256, now)
        if recording.state != "ready" or str(recording.source_revision) != intent.source_revision:
            raise ConversationConflict("The requested recording revision is not ready.")
        payload = intent.model_dump(mode="json")
        replay = await self._replay(actor, key, "run", payload)
        if replay is not None and replay.result_id is not None:
            return await self._run_view(actor, replay.result_id)
        quoted = await self.database.scalar(
            select(ConversationQuote)
            .where(
                ConversationQuote.id == intent.quote_id,
                ConversationQuote.tenant_id == actor.tenant_id,
                ConversationQuote.person_id == actor.person_id,
                ConversationQuote.recording_id == recording.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if quoted is None or quoted.revoked_at is not None:
            raise ConversationDenied("An approved exact recording quote is required.")
        from ac_platform.conversation_intelligence.intake import require_intake_acceptance

        await require_intake_acceptance(self, actor, quoted)
        quote = Quote.from_dict(quoted.quote)
        permission = ExecutionPermission.from_dict(quoted.execution_permission)
        if (
            quote.quote_id != str(quoted.id)
            or quote.source.tenant_id != str(actor.tenant_id)
            or quote.source.recording_id != str(recording.id)
            or quote.source.source_sha256 != recording.source_sha256
            or quote.source.source_revision != intent.source_revision
            or quote.input_sha256 != recording.source_sha256
            or quote.account_id != str(actor.person_id)
            or quote.budget_scope_id != str(quoted.budget_scope_id)
            or quote.recipe_revision != intent.recipe_revision
            or intent.recipe_revision not in AUDIOATLAS_RECIPES
            or quote.provider_id != "local"
            or quote.max_cost_paise != 0
            or quote.operation != "inspect_audioatlas"
            or quote.provider_model != "audioatlas"
        ):
            raise ConversationDenied("This worker accepts only the approved local acoustic recipe.")
        # One global budget lock then one member allowance lock. Different members
        # cannot multiply the shared project spending cap by racing each other.
        budget_row = await self.database.scalar(
            select(ConversationBudgetAccount)
            .where(
                ConversationBudgetAccount.scope_id == quoted.budget_scope_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        minute_row = await self.database.scalar(
            select(ConversationMinuteAccount)
            .where(
                ConversationMinuteAccount.tenant_id == actor.tenant_id,
                ConversationMinuteAccount.person_id == actor.person_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if budget_row is None or minute_row is None:
            raise ConversationDenied("An explicit processing entitlement is required.")
        identifier = uuid4()
        try:
            transition = reserve(
                MinuteAccount.from_dict(minute_row.snapshot),
                BudgetAccount.from_dict(budget_row.snapshot),
                str(identifier),
                quote,
                permission,
                now_epoch=int(now.timestamp()),
            )
        except ValueError:
            raise ConversationConflict("The quote or reserved allowance is unavailable.") from None
        minute_row.snapshot, budget_row.snapshot = (
            transition.minutes.as_dict(),
            transition.budget.as_dict(),
        )
        minute_row.revision += 1
        budget_row.revision += 1
        job = await JobRepository(self.database).enqueue(
            kind=LOCAL_JOB,
            dedupe_key=f"conversation:inspect:{identifier}",
            tenant_id=recording.tenant_id,
            external_side_effect=False,
            payload={
                "run_id": str(identifier),
                "recording_id": str(recording.id),
                "generation": recording.generation,
                "quote_id": str(quoted.id),
            },
        )
        self.database.add(
            ConversationRun(
                id=identifier,
                tenant_id=recording.tenant_id,
                person_id=recording.person_id,
                recording_id=recording.id,
                request_key=key,
                intent_sha256=content_hash(payload),
                recipe_revision=intent.recipe_revision,
                generation=recording.generation,
                state="queued",
                job_id=job.id,
                created_at=now,
            )
        )
        await self.database.flush()
        await self._receipt(actor, key, "run", payload, identifier, now)
        return await self._run_view(actor, identifier)

    async def _run_view(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        run = await self.database.scalar(
            select(ConversationRun).where(
                ConversationRun.id == run_id,
                ConversationRun.tenant_id == actor.tenant_id,
                ConversationRun.person_id == actor.person_id,
            )
        )
        if run is None:
            raise ConversationNotFound("Run not found.")
        job = await self.database.get(Job, run.job_id)
        state = run.state
        if job is not None and job.status == "dead_letter" and state in {"queued", "running"}:
            state = "failed"
        return {
            "id": str(run.id),
            "recording_id": str(run.recording_id),
            "state": state,
            "recipe_revision": run.recipe_revision,
            # Confirmed responses only; an ambiguous dispatch has no receipt.
            "provider_calls": int(job is not None and job.provider_receipt is not None),
        }

    async def get_run(self, actor: ActorContext, run_id: UUID) -> dict[str, Any]:
        await self.admit(actor)
        result = await self._run_view(actor, run_id)
        await self.get(actor, UUID(result["recording_id"]))
        return result

    async def publish_checkpoint(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        recovery_generation: int,
        checkpoint: Checkpoint,
        payload: dict[str, Any],
        feature_blob_id: UUID | None = None,
        storage: RecordingObjectStorage | None = None,
    ) -> UUID:
        """Worker-only port: a hash alone never grants permission to publish content."""
        job = await JobRepository(self.database).lock_internal_lease(
            job_id,
            lease_token,
            kind=LOCAL_JOB,
            recovery_generation=recovery_generation,
        )
        recording_id = UUID(checkpoint.binding.recording_id)
        owner = await self.database.scalar(
            select(ConversationRecording.person_id).where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id == job.tenant_id,
            )
        )
        if owner is None:
            raise ConversationConflict("Checkpoint publication was fenced.")
        # Same identity-first lock order as interactive commands. Holding these
        # locks through commit also fences suspension and membership revocation.
        person = await self.database.scalar(
            select(Person)
            .where(Person.id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tenant = await self.database.scalar(
            select(Tenant)
            .where(Tenant.id == job.tenant_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        member = await self.database.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == job.tenant_id,
                Membership.person_id == owner,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == recording_id,
                ConversationRecording.tenant_id == UUID(checkpoint.binding.tenant_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = utc(self.clock())
        if (
            recording is None
            or job.tenant_id != recording.tenant_id
            or job.payload.get("recording_id") != str(recording.id)
            or job.payload.get("generation") != recording.generation
            or recording.state != "ready"
            or checkpoint.binding.source_sha256 != recording.source_sha256
            or checkpoint.binding.source_revision != str(recording.source_revision)
            or checkpoint.payload_sha256 != content_hash(payload)
            or checkpoint.stage not in {"C0", "C1"}
        ):
            raise ConversationConflict("Checkpoint publication was fenced.")
        permission = await self.database.scalar(
            select(ConversationPermission)
            .where(
                ConversationPermission.id == recording.permission_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            permission is None
            or permission.revoked_at is not None
            or permission.provider != "local"
            or permission.source_sha256 != recording.source_sha256
            or utc(permission.expires_at) <= now
            or utc(permission.retention_until) <= now
            or member is None
            or member.status != "active"
            or member.ended_at is not None
            or person is None
            or person.status != "active"
            or tenant is None
            or tenant.status != "active"
        ):
            raise ConversationDenied("Recording permission is no longer active.")
        run = await self.database.scalar(
            select(ConversationRun)
            .where(
                ConversationRun.job_id == job.id,
                ConversationRun.recording_id == recording.id,
                ConversationRun.tenant_id == recording.tenant_id,
                ConversationRun.generation == recording.generation,
                ConversationRun.state.in_(("queued", "running")),
            )
            .with_for_update()
        )
        if run is None or job.payload.get("run_id") != str(run.id):
            raise ConversationConflict("The run no longer accepts checkpoint publication.")
        if feature_blob_id is not None and checkpoint.stage != "C1":
            raise ConversationConflict("Feature storage does not belong to this run.")
        if (
            payload.get("source_sha256") != recording.source_sha256
            or payload.get("source_bytes") != recording.source_bytes
        ):
            raise ConversationConflict("Checkpoint payload does not match the source.")
        if checkpoint.stage == "C0" and (
            payload.get("content_type") != recording.content_type
            or payload.get("permission_reference") != str(recording.permission_id)
            or checkpoint.revision != "recording-v1"
            or json.loads(checkpoint.config_json) != {}
        ):
            raise ConversationConflict("Source checkpoint metadata does not match admission.")
        for stage, manifest_hash in checkpoint.parents:
            parent = await self.database.scalar(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                    ConversationCheckpoint.stage == stage,
                    ConversationCheckpoint.manifest_sha256 == manifest_hash,
                    ConversationCheckpoint.erased_at.is_(None),
                )
            )
            if parent is None:
                raise ConversationConflict("The checkpoint parent is unavailable.")
        existing = await self.database.scalar(
            select(ConversationCheckpoint).where(
                ConversationCheckpoint.recording_id == recording.id,
                ConversationCheckpoint.cache_key == checkpoint.cache_key,
            )
        )
        if checkpoint.stage == "C1":
            decode_rate = AUDIOATLAS_RECIPES.get(checkpoint.revision)
            if (
                storage is None
                or feature_blob_id is None
                or (existing is None and feature_blob_id != run.id)
                or (existing is not None and feature_blob_id != existing.feature_blob_id)
                or decode_rate is None
                or checkpoint.revision != run.recipe_revision
                or json.loads(checkpoint.config_json)
                != {"decode_rate": decode_rate, "window_profile": "audioatlas-40ms-10ms"}
            ):
                raise ConversationConflict("A verified feature artifact is required.")
            try:
                meta = payload["acoustics"]
                expected = _feature_metadata(
                    decode_rate, payload["source_channels"], meta["sample_count"]
                )
                if (
                    payload["schema"] != "ac.sales-xray.signal-checkpoint/1"
                    or payload["stage"] != "C1"
                    or any(meta.get(k) != v for k, v in expected.items())
                    or meta["source_sha256"] != recording.source_sha256
                    or meta["feature_sha256"] != payload["feature_sha256"]
                    or payload["native_receipt"]["source_sha256"] != NATIVE_SOURCE_SHA256
                    or payload["native_receipt"]["rows"] != meta["rows"]
                    or payload["timebase"]["rate"] != decode_rate
                    or payload["timebase"]["clock"] != "decoded_audio_track"
                    or payload["timebase"]["silence_removed"] is not False
                    or payload["media_duration_ms"]
                    != round(meta["sample_count"] / decode_rate * 1000)
                ):
                    raise ValueError("inconsistent signal metadata")
                feature_key = ObjectKey(
                    recording.tenant_id, recording.id, feature_blob_id, ObjectKind.SIGNAL_FEATURES
                )
                retained_size = await join_thread(
                    lambda: sum(
                        len(block)
                        for block in storage.iter_bytes(
                            feature_key, expected_sha256=payload["feature_sha256"]
                        )
                    )
                )
                if retained_size != meta["header_bytes"] + meta["uncompressed_payload_bytes"]:
                    raise ValueError("inconsistent artifact size")
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ConversationConflict(
                    "Signal source or retained artifact is invalid."
                ) from None
        if existing is not None:
            if (
                existing.manifest_sha256 != checkpoint.manifest_sha256
                or existing.erased_at is not None
            ):
                raise ConversationConflict("Conflicting immutable checkpoint output.")
            return existing.id
        row = ConversationCheckpoint(
            id=uuid4(),
            recording_id=recording.id,
            tenant_id=recording.tenant_id,
            person_id=recording.person_id,
            cache_key=checkpoint.cache_key,
            manifest_sha256=checkpoint.manifest_sha256,
            payload_sha256=checkpoint.payload_sha256,
            stage=checkpoint.stage,
            feature_blob_id=feature_blob_id,
            manifest=checkpoint.as_dict(),
            payload=payload,
            created_at=now,
        )
        self.database.add(row)
        await self.database.flush()
        return row.id

    async def finish_erasure(
        self,
        *,
        job_id: UUID,
        lease_token: UUID,
        recovery_generation: int,
    ) -> None:
        """Call only after the private adapter confirms all recording objects erased."""
        job = await JobRepository(self.database).lock_internal_lease(
            job_id,
            lease_token,
            kind=DELETE_JOB,
            recovery_generation=recovery_generation,
        )
        recording = await self.database.scalar(
            select(ConversationRecording)
            .where(
                ConversationRecording.id == UUID(job.payload["recording_id"]),
                ConversationRecording.tenant_id == job.tenant_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            recording is None
            or recording.generation != job.payload["generation"]
            or recording.state not in {"deleting", "deleted"}
        ):
            raise ConversationConflict("Erasure was fenced.")
        now = utc(self.clock())
        from ac_platform.conversation_intelligence.models import ConversationProcessingPlan

        for plan in (
            await self.database.scalars(
                select(ConversationProcessingPlan).where(
                    ConversationProcessingPlan.recording_id == recording.id,
                    ConversationProcessingPlan.erased_at.is_(None),
                )
            )
        ).all():
            plan.manifest, plan.erased_at, plan.state = None, now, "cancelled"
            plan.progress = {}
        for task in (
            await self.database.scalars(
                select(ConversationInferenceTask).where(
                    ConversationInferenceTask.recording_id == recording.id,
                    ConversationInferenceTask.erased_at.is_(None),
                )
            )
        ).all():
            task.intent, task.erased_at = None, now
            if task.state in {"queued", "running"}:
                task.state = "cancelled"
        for draft in (
            await self.database.scalars(
                select(ConversationReportDraft).where(
                    ConversationReportDraft.recording_id == recording.id,
                    ConversationReportDraft.erased_at.is_(None),
                )
            )
        ).all():
            draft.payload, draft.transcript, draft.evidence_receipt = None, None, None
            draft.erased_at = now
        for row in (
            await self.database.scalars(
                select(ConversationCheckpoint).where(
                    ConversationCheckpoint.recording_id == recording.id,
                )
            )
        ).all():
            row.payload, row.manifest, row.erased_at = None, None, now
        runs = (
            await self.database.scalars(
                select(ConversationRun).where(
                    ConversationRun.recording_id == recording.id,
                )
            )
        ).all()
        for run in runs:
            if run.state in {"queued", "running"}:
                run.state = "cancelled"
            for review in (
                await self.database.scalars(
                    select(ConversationReview).where(
                        ConversationReview.run_id == run.id,
                    )
                )
            ).all():
                review.proposal, review.erased_at = None, now
        recording.state, recording.deleted_at = "deleted", now
        await JobRepository(self.database).complete(job_id, lease_token)
