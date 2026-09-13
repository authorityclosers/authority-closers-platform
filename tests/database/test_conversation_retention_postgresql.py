"""Automatic deadline erasure on disposable PostgreSQL and synthetic audio."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import DELETE_JOB
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.identity.models import Session
from ac_platform.outbox.models import Job
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_retention_deadline_enqueues_once_and_erases_without_live_session(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as db, db.begin():
                recording = await db.get(ConversationRecording, setup.prepared.recording_id)
                permission = await db.get(ConversationPermission, recording.permission_id)
                deadline = permission.retention_until
                session = await db.get(Session, setup.actor.session_id)
                session.revoked_at = setup.prepared.state.now
            before = ConversationRetentionScheduler(
                setup.sessions, clock=lambda: deadline - timedelta(seconds=1)
            )
            after = ConversationRetentionScheduler(
                setup.sessions, clock=lambda: deadline + timedelta(seconds=1)
            )
            assert await before.step() is False
            assert await after.step() is True
            assert await after.step() is False
            async with setup.sessions() as db:
                recording = await db.get(ConversationRecording, setup.prepared.recording_id)
                assert recording.state == "deleting" and recording.generation == 2
                assert (
                    await db.scalar(
                        select(func.count()).select_from(Job).where(Job.kind == DELETE_JOB)
                    )
                    == 1
                )
                event = await db.scalar(
                    select(AuditEvent).where(AuditEvent.action == "conversation.retention_expired")
                )
                assert (
                    event.actor_type == "system"
                    and event.actor_person_id is None
                    and event.session_id is None
                )
            assert await setup.prepared.worker.run_once() is True
            async with setup.sessions() as db:
                recording = await db.get(ConversationRecording, setup.prepared.recording_id)
                assert recording.state == "deleted"
                rows = list((await db.scalars(select(ConversationCheckpoint))).all())
                assert rows and all(
                    row.payload is None and row.manifest is None and row.erased_at for row in rows
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.action == "conversation.retention_expired")
                    )
                    == 1
                )
            assert setup.broker.routes == []
        finally:
            await setup.engine.dispose()

    run(exercise())
