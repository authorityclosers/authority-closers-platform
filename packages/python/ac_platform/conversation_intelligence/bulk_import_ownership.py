"""Exact batch/item authority with the real uploader; no member impersonation."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.activation_contract import InternalTesterApproval
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.bulk_imports import ImportReference, RecordingImports
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.kernel.authz import ActorContext


class ImportSessions(AcquisitionSessions):
    """Normal ledger/limits under an exact server-resolved batch decision."""

    def __init__(
        self, ownership: GuestOwnership, uploader: ActorContext, reference: ImportReference
    ) -> None:
        original = ownership.sessions
        if original.trial_enabled:
            raise ConversationDenied(
                "Recording imports require the normal organisation minute pool."
            )
        super().__init__(
            original.database,
            tenant_id=original.tenant_id,
            policy_revision=original.policy_revision,
            lifetime=original.lifetime,
            clock=original.clock,
            tester_policy=original.tester_policy,
            operations_tenant_id=original.operations_tenant_id,
            trial_policy=original.trial_policy,
            trial_enabled=original.trial_enabled,
        )
        self.imports = RecordingImports(ownership)
        self.uploader, self.reference = uploader, reference

    async def _owner(
        self,
        token: str | None,
        actor: ActorContext | None,
        now: datetime,
        *,
        shared_identity_locks: bool = False,
    ) -> tuple[UUID | None, UUID | None]:
        if token is not None or actor != self.uploader:
            raise ConversationDenied("Use this batch's current uploader session.")
        _, item = await self.imports.authorize(
            self.uploader, self.reference, shared_identity_locks=shared_identity_locks
        )
        if item.reused:
            raise ConversationDenied(
                "An already imported recording keeps its original owner and analysis."
            )
        return None, item.person_id

    async def _account_tester(self, actor: ActorContext | None) -> InternalTesterApproval | None:
        # Never apply an administrator's personal tester exemption to a rep.
        _, person_id = await self._owner(None, actor, utc(self.clock()), shared_identity_locks=True)
        if self.tester_policy is None or person_id is None:
            return None
        return await self.tester_policy.for_learner_account(
            self.database, tenant_id=self.tenant_id, person_id=person_id
        )

    async def reserve(
        self, source: MeasuredSource, *, token: str | None = None, actor: ActorContext | None = None
    ) -> UUID:
        if actor != self.uploader or token is not None:
            raise ConversationDenied("Use this batch's current uploader session.")
        _, item = await self.imports.authorize(self.uploader, self.reference)
        if (
            source.submission_id != item.submission_id
            or source.source_sha256 != item.source_sha256
            or item.reused
        ):
            raise ConversationDenied("The measured source differs from the exact import item.")
        now = await self._admit(mutation=True)
        await self.imports.fair_admission(item.submission_id, self.uploader)
        usage_id = await super().reserve(source, actor=actor)
        if item.usage_id is None:
            item.usage_id, item.linked_at = usage_id, now
            await self.database.flush()
        elif item.usage_id != usage_id:
            raise ConversationDenied("This import item already owns another source receipt.")
        return usage_id

    async def reserve_report_retry(
        self,
        submission_id: UUID,
        *,
        key: str,
        token: str | None = None,
        actor: ActorContext | None = None,
        allow_organisation_start: bool = False,
    ) -> UUID:
        # An import grant covers only the uploader's own exact call: the organisation
        # start path ("Get full report") is accepted here but never forwarded.
        del allow_organisation_start
        _, item = await self.imports.authorize(self.uploader, self.reference)
        if (
            actor != self.uploader
            or token is not None
            or item.submission_id != submission_id
            or item.reused
        ):
            raise ConversationDenied("Use this exact imported call's safe retry.")
        await self._admit(mutation=True)
        await self.imports.fair_admission(submission_id, self.uploader)
        return await super().reserve_report_retry(submission_id, key=key, actor=actor)


class ImportOwnership(GuestOwnership):
    def __init__(
        self, ownership: GuestOwnership, uploader: ActorContext, reference: ImportReference
    ) -> None:
        super().__init__(ImportSessions(ownership, uploader, reference))
        self.imports = RecordingImports(ownership)
        self.uploader, self.reference = uploader, reference

    async def _owned_usage(
        self,
        submission_id: UUID,
        *,
        token: str | None,
        actor: ActorContext | None,
        mutation: bool,
        shared_identity_locks: bool = False,
        allow_organisation_read: bool = False,
        allow_organisation_start: bool = False,
    ) -> tuple[ConversationAcquisitionUsage, datetime, bool]:
        # An import grant covers only the uploader's own exact call: the
        # organisation read/start paths are accepted here but never forwarded.
        del allow_organisation_read, allow_organisation_start
        _, item = await self.imports.authorize(
            self.uploader, self.reference, shared_identity_locks=shared_identity_locks
        )
        if (
            actor != self.uploader
            or token is not None
            or item.submission_id != submission_id
            or item.reused
        ):
            raise ConversationNotFound("This call is outside the exact recording import grant.")
        usage, now, claimed = await super()._owned_usage(
            submission_id,
            token=None,
            actor=actor,
            mutation=mutation,
            shared_identity_locks=shared_identity_locks,
        )
        if (
            usage.id != item.usage_id
            or usage.source_sha256 != item.source_sha256
            or usage.person_id != item.person_id
        ):
            raise ConversationDenied("The import's source ownership receipt is unavailable.")
        return usage, now, claimed

    async def existing_source(
        self, submission_id: UUID, *, source_sha256: str, source_bytes: int, policy_sha256: str
    ) -> dict[str, Any] | None:
        batch, item = await self.imports.authorize(self.uploader, self.reference)
        if (
            item.submission_id != submission_id
            or item.source_sha256 != source_sha256
            or item.source_bytes != source_bytes
            or batch.policy_sha256 != policy_sha256
        ):
            raise ConversationDenied("The upload differs from the confirmed batch item or policy.")
        now = await self.sessions._admit(mutation=True)
        usage = await self.database.scalar(
            select(ConversationAcquisitionUsage)
            .where(
                ConversationAcquisitionUsage.tenant_id == self.tenant_id,
                ConversationAcquisitionUsage.source_sha256 == item.source_sha256,
                ConversationAcquisitionUsage.person_id.is_not(None),
            )
            .order_by(ConversationAcquisitionUsage.created_at, ConversationAcquisitionUsage.id)
            .limit(1)
        )
        if usage is None:
            await self.imports.fair_admission(submission_id, self.uploader)
            return None
        if item.usage_id is None:
            item.usage_id, item.reused, item.linked_at = usage.id, True, now
            await self.database.flush()
        elif item.usage_id != usage.id:
            raise ConversationDenied("This import item already owns a different source receipt.")
        return {
            "submission_id": str(usage.submission_id),
            "source_sha256": usage.source_sha256,
            "state": "already_imported",
            "import_batch_id": str(batch.id),
            "import_item_index": item.item_index,
        }

    async def request_deletion(
        self,
        submission_id: UUID,
        *,
        key: str,
        token: str | None = None,
        actor: ActorContext | None = None,
    ) -> dict[str, Any]:
        raise ConversationDenied("A recording import does not grant deletion authority.")
