"""Sandbox-only preserved authored records; no provider, real identity or minute write."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
    utc,
)
from ac_platform.conversation_intelligence.bulk_imports import RecordingImports
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.synthetic_import_contracts import (
    PRIVATE_KINDS,
    SyntheticCallBundle,
    SyntheticRecordBatch,
)
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
    ConversationSyntheticRecord,
)
from ac_platform.kernel.authz import ActorContext

SANDBOX_NAMESPACE = UUID("3a70c7aa-8be1-4f16-8119-335f5203a9e4")


class SyntheticImports:
    def __init__(self, ownership: GuestOwnership) -> None:
        self.ownership = ownership
        self.database = ownership.database
        self.imports = RecordingImports(ownership)

    async def admit(self, actor: ActorContext, *, write: bool = False) -> datetime:
        now = await self.imports.administrator(actor, shared_identity_locks=not write)
        flag = await self.database.scalar(
            select(ConversationSandboxOrganisation)
            .where(ConversationSandboxOrganisation.tenant_id == actor.tenant_id)
            .with_for_update(read=True)
        )
        if flag is None:
            raise ConversationDenied(
                "Synthetic imports require an explicitly flagged sandbox organisation."
            )
        if write:
            await take_admission_lock(self.database, self.ownership.tenant_id)
        return now

    async def _save(
        self,
        actor: ActorContext,
        *,
        kind: str,
        key: str,
        revision: int,
        business_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
        now: datetime,
    ) -> bool:
        identity = (self.ownership.tenant_id, kind, key, revision)
        digest = content_hash(payload)
        existing = await self.database.get(ConversationSyntheticRecord, identity)
        if existing is not None:
            if (
                existing.payload_sha256 != digest
                or existing.business_id != business_id
                or utc(existing.occurred_at) != utc(occurred_at)
            ):
                raise ConversationConflict(
                    "This synthetic revision already has different authored content. "
                    "Supersede it explicitly."
                )
            return False
        if utc(occurred_at) > now:
            raise ConversationConflict(
                "Import only synthetic history available as of the current date."
            )
        self.database.add(
            ConversationSyntheticRecord(
                tenant_id=self.ownership.tenant_id,
                kind=kind,
                synthetic_key=key,
                revision=revision,
                business_id=business_id,
                imported_by_person_id=actor.person_id,
                payload_sha256=digest,
                payload=payload,
                occurred_at=utc(occurred_at),
                imported_at=now,
            )
        )
        await self.database.flush()
        return True

    async def call(
        self, actor: ActorContext, bundle: SyntheticCallBundle, *, key: str
    ) -> dict[str, Any]:
        now = await self.admit(actor, write=True)
        call_id = str(bundle.metadata["call_id"])
        payload = bundle.model_dump(by_alias=True)
        created = await self._save(
            actor,
            kind="call",
            key=call_id,
            revision=1,
            business_id=str(bundle.metadata["business_id"]),
            occurred_at=bundle.occurred_at,
            payload=payload,
            now=now,
        )
        await self._receipt(actor, key, {"call_id": call_id, "sha256": content_hash(payload)}, now)
        return {
            "synthetic": True,
            "call_id": call_id,
            "state": "done",
            "created": created,
            "processing": "authored_report",
            "minute_state": None,
        }

    async def records(
        self, actor: ActorContext, batch: SyntheticRecordBatch, *, key: str
    ) -> dict[str, Any]:
        now = await self.admit(actor, write=True)
        created = 0
        for record in batch.records:
            created += await self._save(
                actor,
                kind=record.kind,
                key=record.key,
                revision=record.revision,
                business_id=record.business_id,
                occurred_at=record.occurred_at,
                payload=record.payload,
                now=now,
            )
        intent = {"records_sha256": content_hash(batch.model_dump(mode="json", by_alias=True))}
        await self._receipt(actor, key, intent, now)
        return {
            "synthetic": True,
            "state": "done",
            "created": created,
            "skipped": len(batch.records) - created,
        }

    async def _receipt(
        self, actor: ActorContext, key: str, intent: dict[str, Any], now: datetime
    ) -> None:
        app = self.imports.application
        action = "sandbox_imported"
        # A replay and a different-key repeat both retain the original records;
        # the receipt contains only a digest, never authored call content.
        if await app._replay(actor, key, action, intent) is None:
            await app._receipt(
                actor,
                key,
                action,
                intent,
                uuid5(SANDBOX_NAMESPACE, f"{actor.tenant_id}:{content_hash(intent)}"),
                now,
                resource_type="conversation_synthetic_import",
            )

    async def progress(self, actor: ActorContext) -> dict[str, Any]:
        await self.admit(actor)
        rows = (
            await self.database.execute(
                select(
                    ConversationSyntheticRecord.kind,
                    func.count(),
                    func.min(ConversationSyntheticRecord.occurred_at),
                    func.max(ConversationSyntheticRecord.occurred_at),
                )
                .where(ConversationSyntheticRecord.tenant_id == self.ownership.tenant_id)
                .group_by(ConversationSyntheticRecord.kind)
            )
        ).all()
        return {
            "synthetic": True,
            "sandbox": True,
            "tenant_id": str(self.ownership.tenant_id),
            "records": [
                {
                    "kind": kind,
                    "count": count,
                    "first_at": first.isoformat(),
                    "last_at": last.isoformat(),
                }
                for kind, count, first, last in rows
            ],
        }

    async def read_call(
        self, actor: ActorContext, call_id: str, *, coaching: bool = False
    ) -> dict[str, Any]:
        await self.admit(actor)
        row = await self.database.get(
            ConversationSyntheticRecord, (self.ownership.tenant_id, "call", call_id, 1)
        )
        if row is None or (coaching and row.imported_by_person_id != actor.person_id):
            raise ConversationNotFound("This synthetic call is unavailable.")
        if coaching:
            return {"synthetic": True, "private": True, "coaching": row.payload["coaching"]}
        return {
            "synthetic": True,
            "call_id": call_id,
            "state": "done",
            "processing": "authored_report",
            "minute_state": None,
            "metadata": row.payload["metadata"],
            "transcript": row.payload["transcript"],
            "report": row.payload["report"],
            "payload_sha256": row.payload_sha256,
        }

    async def list_records(
        self, actor: ActorContext, *, kind: str, after: str | None = None, limit: int = 100
    ) -> dict[str, Any]:
        await self.admit(actor)
        query = select(ConversationSyntheticRecord).where(
            ConversationSyntheticRecord.tenant_id == self.ownership.tenant_id,
            ConversationSyntheticRecord.kind == kind,
        )
        if kind in PRIVATE_KINDS:
            query = query.where(
                ConversationSyntheticRecord.imported_by_person_id == actor.person_id
            )
        if after:
            query = query.where(ConversationSyntheticRecord.synthetic_key > after)
        # List current authored revisions; full calls use the bounded read port.
        newer = aliased(ConversationSyntheticRecord)
        query = query.where(
            ~select(newer.revision)
            .where(
                newer.tenant_id == ConversationSyntheticRecord.tenant_id,
                newer.kind == ConversationSyntheticRecord.kind,
                newer.synthetic_key == ConversationSyntheticRecord.synthetic_key,
                newer.revision > ConversationSyntheticRecord.revision,
            )
            .exists()
        )
        rows = list(
            (
                await self.database.scalars(
                    query.order_by(ConversationSyntheticRecord.synthetic_key).limit(limit + 1)
                )
            ).all()
        )
        return {
            "synthetic": True,
            "records": [
                {
                    "kind": row.kind,
                    "key": row.synthetic_key,
                    "business_id": row.business_id,
                    "occurred_at": row.occurred_at.isoformat(),
                    "payload_sha256": row.payload_sha256,
                    **(
                        {"metadata": row.payload["metadata"]}
                        if kind == "call"
                        else {"payload": row.payload}
                    ),
                }
                for row in rows[:limit]
            ],
            "next_cursor": rows[limit - 1].synthetic_key if len(rows) > limit else None,
        }
