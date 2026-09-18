"""Expire one private recording through AC's existing durable erasure job.

The source-owned permission deadline is authoritative. Expiry needs no current
user session or provider approval and never extends retention on a failed job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import DELETE_JOB, utc
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository


class ConversationRetentionScheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.sessions, self.clock = sessions, clock

    async def step(self) -> bool:
        now = utc(self.clock())
        async with self.sessions() as db, db.begin():
            await RecoveryStateRepository(db).require_ready(lock=True, shared_lock=True)
            recording = await db.scalar(
                select(ConversationRecording)
                .join(
                    ConversationPermission,
                    (ConversationPermission.id == ConversationRecording.permission_id)
                    & (ConversationPermission.tenant_id == ConversationRecording.tenant_id)
                    & (ConversationPermission.person_id == ConversationRecording.person_id),
                )
                .where(
                    ConversationRecording.state.not_in(("deleting", "deleted")),
                    ConversationPermission.retention_until <= now,
                )
                .order_by(ConversationPermission.retention_until, ConversationRecording.id)
                .limit(1)
                .with_for_update(of=ConversationRecording, skip_locked=True)
            )
            if recording is None:
                return False
            permission = await db.get(
                ConversationPermission, recording.permission_id, with_for_update=True
            )
            if permission is None or utc(permission.retention_until) > now:
                return False
            recording.state = "deleting"
            recording.generation += 1
            await JobRepository(db).enqueue(
                kind=DELETE_JOB,
                dedupe_key=f"conversation:erase:{recording.id}:{recording.generation}",
                tenant_id=recording.tenant_id,
                payload={"recording_id": str(recording.id), "generation": recording.generation},
                external_side_effect=False,
            )
            await AuditRepository(db).append(
                tenant_id=recording.tenant_id,
                actor_person_id=None,
                actor_type="system",
                action="conversation.retention_expired",
                resource_type="conversation_recording",
                resource_id=recording.id,
                payload={
                    "permission_id": str(permission.id),
                    "generation": recording.generation,
                    "retention_until": utc(permission.retention_until).isoformat(),
                },
                reason="The approved private recording retention deadline expired.",
                now=now,
            )
            return True
