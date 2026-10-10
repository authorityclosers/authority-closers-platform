"""Released customer work cannot outlive worker ownership or replay a send."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.released_run_recovery import stop_released_run
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_report_minutes_postgresql import setup_case
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def pending_provider(case: Any) -> Any:
    await _reconcile(case.sessions, case.state)
    async with case.sessions() as db, db.begin():
        identifier = uuid4()
        recording = await db.get(ConversationRecording, case.plan.recording_id)
        recording.state = "ready"  # Synthetic retained-source recovery fixture.
        quote = await db.scalar(
            select(ConversationQuote).where(
                ConversationQuote.recording_id == case.plan.recording_id
            )
        )
        job = await JobRepository(db).enqueue(
            kind="conversation.infer_provider.v1",
            dedupe_key=uuid4().hex,
            payload={"run_id": str(identifier)},
            tenant_id=case.actor.tenant_id,
            external_side_effect=True,
        )
        job.status = "leased"
        job.held_at = job.hold_reason = None
        job.lease_token = uuid4()
        job.leased_until = datetime.now(UTC) - timedelta(seconds=1)
        job.attempt_count = 1
        job.dispatch_started_at = datetime.now(UTC) - timedelta(minutes=1)
        job.provider_idempotency_key = "fictional-original-effect"
        # A provisional returned receipt is evidence, not a validated report.
        job.provider_receipt = {"validation_state": "provider_returned", "fixture": True}
        job.provider_receipt_digest = "b" * 64
        job.receipt_recorded_at = job.dispatch_started_at
        row = ConversationRun(
            id=identifier,
            tenant_id=case.actor.tenant_id,
            person_id=case.actor.person_id,
            recording_id=case.plan.recording_id,
            request_key=uuid4().hex,
            intent_sha256="a" * 64,
            job_id=job.id,
            recipe_revision="fictional-recovery",
            generation=1,
            state="running",
            created_at=case.state.now,
        )
        db.add(row)
        await db.flush()
        db.add(
            ConversationInferenceTask(
                run_id=identifier,
                tenant_id=row.tenant_id,
                person_id=row.person_id,
                recording_id=row.recording_id,
                processing_lease_id=case.actor.processing_lease_id,
                job_id=job.id,
                quote_id=quote.id,
                generation=1,
                stage="C2",
                cache_key="a" * 64,
                input_sha256="a" * 64,
                intent_sha256="a" * 64,
                intent={"fixture": True},
                state="running",
                created_at=case.state.now,
            )
        )
        assert await ReportMinutes(db).release_plan(case.plan)
        return row, job


def test_released_provider_recovery_skips_live_ownership_and_preserves_effect(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            original, original_job = await pending_provider(case)
            async with case.sessions() as locked, locked.begin():
                await locked.scalar(select(Job).where(Job.id == original_job.id).with_for_update())
                async with case.sessions() as other, other.begin():
                    assert not await stop_released_run(other, generation=1)
            async with case.sessions() as db, db.begin():
                alarm = await overdue_processing_plans(db)
                assert alarm["released_unfinished_runs"][0]["run_id"] == str(original.id)
                assert await stop_released_run(db, generation=1)
                assert not await stop_released_run(db, generation=1)
            async with case.sessions() as db:
                job = await db.get(Job, original_job.id)
                task = await db.get(ConversationInferenceTask, original.id)
                row = await db.get(ConversationRun, original.id)
                assert job.status == "dead_letter" and row.state == "failed" and row.completed_at
                assert task.state == "uncertain"
                for field in (
                    "provider_idempotency_key",
                    "dispatch_started_at",
                    "provider_receipt",
                    "provider_receipt_digest",
                    "receipt_recorded_at",
                    "attempt_count",
                ):
                    assert getattr(job, field) == getattr(original_job, field)
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "conversation.released_run_stopped"
                        )
                    )
                )
                assert len(events) == 1 and events[0].payload["dispatch_started"] is True
                assert (await overdue_processing_plans(db))["released_unfinished_runs"] == []
        finally:
            await engine.dispose()

    run(exercise())


def test_released_recovery_respects_generation_live_lease_and_audit_rollback(
    postgres_harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            row, job = await pending_provider(case)
            async with case.sessions() as db, db.begin():
                assert not await stop_released_run(db, generation=2)
                stored = await db.get(Job, job.id)
                stored.leased_until = datetime.now(UTC) + timedelta(minutes=1)
            async with case.sessions() as db, db.begin():
                assert not await stop_released_run(db, generation=1)
                stored = await db.get(Job, job.id)
                stored.leased_until = datetime.now(UTC) - timedelta(seconds=1)

            async def fail_audit(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("fictional audit failure")

            with monkeypatch.context() as patch:
                patch.setattr(AuditRepository, "append", fail_audit)
                with pytest.raises(RuntimeError, match="fictional audit"):
                    async with case.sessions() as db, db.begin():
                        await stop_released_run(db, generation=1)
            async with case.sessions() as db, db.begin():
                assert (await db.get(Job, job.id)).status == "leased"
                assert (await db.get(ConversationRun, row.id)).state == "running"
                assert await stop_released_run(db, generation=1)
        finally:
            await engine.dispose()

    run(exercise())
