"""Expire one private recording through AC's existing durable erasure job.

The source-owned permission deadline is authoritative. Expiry needs no current
user session or provider approval and never extends retention on a failed job.

Automatic expiry is OFF in the hosted service (owner, 20 Nov 2026: "No data should be
deleted. Not the call logs, not the recordings, nothing"; and for Authority Closers
Public Learners: "keep the public learners data too, nothing deleted"). The service
composes the scheduler with ``expire=AUTOMATIC_EXPIRY``; a recording goes only when a
person deletes it or an erasure request asks for it (application.py's delete path).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import DELETE_JOB, utc
from ac_platform.conversation_intelligence.canary import recording_is_marked_canary
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository

# The hosted service never erases a recording because its deadline passed (see above).
AUTOMATIC_EXPIRY = False


class ConversationRetentionScheduler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        expire: bool = True,
    ) -> None:
        self.sessions, self.clock, self.expire = sessions, clock, expire

    async def step(self) -> bool:
        if not self.expire:
            return False
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
                    ~recording_is_marked_canary(),
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
