"""Fictional C1 crash recovery; no native helper, provider or customer settlement."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    MinuteAccount,
    mark_dispatched,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.submission_progress import project_stage_progress
from ac_platform.outbox.errors import LeaseLostError
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_failure_observation_postgresql import seed_measured_fixture
from tests.database.test_conversation_postgresql import application, run, seed
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _prepare

ACTION = "conversation.local_job_recovery_required"


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize(
    "mode",
    [
        "exhausted",
        "native_started",
        "permanent",
        "backoff",
        "live",
        "completed",
        "cancelled",
        "erased",
        "generation",
        "wrong_run",
        "wrong_kind",
        "wrong_quote",
        "wrong_tenant",
        "source_digest",
        "source_revision",
        "source_owner",
        "payload_generation",
        "retained_checkpoint",
        "locked",
        "audit_crash",
        "two_sweepers",
    ],
)
def test_exhausted_local_job_commits_failed_run(
    postgres_harness: Any, tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            work = await prepared.worker.claim()
            assert work is not None
            async with sessions() as db, db.begin():
                job = await db.get(Job, work.job_id)
                local_run = await db.get(ConversationRun, prepared.run_id)
                recording = await db.get(ConversationRecording, prepared.recording_id)
                assert job is not None and local_run is not None and recording is not None
                if mode == "native_started":
                    recording, local_run, quoted, quote = await prepared.worker._scope(db, job)
                    minutes, budget = await prepared.worker._accounts(db, recording, quoted)
                    transition = mark_dispatched(
                        MinuteAccount.from_dict(minutes.snapshot),
                        BudgetAccount.from_dict(budget.snapshot),
                        str(local_run.id),
                        str(job.id),
                        int(datetime.now(UTC).timestamp()),
                    )
                    prepared.worker._save_accounts(minutes, budget, transition)
                    local_run.state = "running"
                if mode not in {"live", "permanent"}:
                    job.leased_until = datetime.now(UTC) - timedelta(seconds=1)
                job.max_attempts = job.attempt_count
                if mode == "backoff":
                    job.status = "retry_wait"
                    job.lease_token = job.leased_until = None
                    job.available_at = datetime.now(UTC) + timedelta(minutes=5)
                if mode == "permanent":
                    await JobRepository(db).fail(
                        job.id,
                        work.lease_token,
                        "fictional_permanent_local_failure",
                        permanent=True,
                    )
                if mode in {"completed", "cancelled"}:
                    local_run.state = mode
                    local_run.completed_at = datetime.now(UTC) - timedelta(seconds=10)
                if mode == "erased":
                    recording.state = "deleting"
                if mode == "generation":
                    recording.generation += 1
                if mode == "wrong_run":
                    job.payload = {**job.payload, "run_id": str(uuid4())}
                if mode == "wrong_kind":
                    job.kind = "fictional.unrelated.v1"
                if mode == "wrong_quote":
                    job.payload = {**job.payload, "quote_id": str(uuid4())}
                if mode == "payload_generation":
                    job.payload = {**job.payload, "generation": str(local_run.generation)}
                if mode == "wrong_tenant":
                    foreign = await seed(engine)
                    job.tenant_id = foreign.tenant_id
                if mode in {"source_digest", "source_revision", "source_owner"}:
                    quoted = await db.get(ConversationQuote, prepared.quote_id)
                    assert quoted is not None
                    broken = deepcopy(quoted.quote)
                    key, value = {
                        "source_digest": ("source_sha256", "f" * 64),
                        "source_revision": ("source_revision", "99"),
                        "source_owner": ("tenant_id", str(uuid4())),
                    }[mode]
                    broken["source"][key] = value
                    # Keep the admitted immutable quote intact. This separate
                    # unaccepted fixture models a wrong persisted job binding.
                    mismatched_id = uuid4()
                    db.add(
                        ConversationQuote(
                            id=mismatched_id,
                            tenant_id=quoted.tenant_id,
                            person_id=quoted.person_id,
                            recording_id=quoted.recording_id,
                            budget_scope_id=quoted.budget_scope_id,
                            quote=broken,
                            execution_permission=quoted.execution_permission,
                        )
                    )
                    job.payload = {**job.payload, "quote_id": str(mismatched_id)}
                before_run = (local_run.state, local_run.completed_at)
                before_effect = (job.dispatch_started_at, job.provider_receipt, job.attempt_count)
                minute_key = (prepared.state.tenant_id, prepared.state.person_id)
                minutes = await db.get(ConversationMinuteAccount, minute_key)
                budget = await db.get(ConversationBudgetAccount, prepared.scope_id)
                assert minutes is not None and budget is not None
                before_accounts = deepcopy((minutes.snapshot, budget.snapshot))
            if mode == "retained_checkpoint":
                await seed_measured_fixture(sessions, prepared)
            if mode == "locked":
                async with sessions() as locker, locker.begin():
                    locked = await locker.scalar(
                        select(ConversationRun)
                        .where(ConversationRun.id == prepared.run_id)
                        .with_for_update()
                    )
                    assert locked is not None
                    assert await asyncio.wait_for(prepared.worker.claim(), timeout=2) is None
                    assert locked.state == before_run[0]
            if mode == "audit_crash":
                original = AuditRepository.append

                async def crash_append(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("fictional terminal audit crash")

                monkeypatch.setattr(AuditRepository, "append", crash_append)
                with pytest.raises(RuntimeError, match="fictional terminal audit crash"):
                    await prepared.worker.claim()
                monkeypatch.setattr(AuditRepository, "append", original)
                async with sessions() as db:
                    job = await db.get(Job, work.job_id)
                    local_run = await db.get(ConversationRun, prepared.run_id)
                    assert job is not None and job.status == "leased"
                    assert local_run is not None
                    assert (local_run.state, local_run.completed_at) == before_run
            if mode == "two_sweepers":
                assert await asyncio.gather(prepared.worker.claim(), prepared.worker.claim()) == [
                    None,
                    None,
                ]
            else:
                assert await prepared.worker.claim() is None
            async with sessions() as db, db.begin():
                job = await db.get(Job, work.job_id)
                local_run = await db.get(ConversationRun, prepared.run_id)
                assert job is not None and local_run is not None
                recovered = mode in {
                    "exhausted",
                    "native_started",
                    "permanent",
                    "locked",
                    "audit_crash",
                    "two_sweepers",
                }
                assert local_run.state == ("failed" if recovered else before_run[0])
                assert (
                    job.dispatch_started_at,
                    job.provider_receipt,
                    job.attempt_count,
                ) == before_effect
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == ACTION,
                            AuditEvent.resource_id == str(job.id),
                        )
                    )
                )
                assert len(events) == int(recovered)
                assert local_run.completed_at == (
                    events[0].occurred_at if recovered else before_run[1]
                )
                if recovered:
                    assert events[0].payload["source_sha256"] == prepared.state.source_sha256
                    assert events[0].payload["generation"] == local_run.generation
                    assert events[0].payload["run_id"] == str(local_run.id)
                    view = await application(db, prepared.state).get_run(
                        prepared.state.actor, local_run.id
                    )
                    assert view["state"] == "failed"
                    progress = project_stage_progress(
                        plan=None,
                        local_run=local_run,
                        local_job=job,
                        executions=[],
                        checkpoints=[],
                        has_report=False,
                        run_state="failed",
                        report_finished_at=None,
                    )
                    failed = next(
                        row for row in progress["stage_progress"] if row["state"] == "failed"
                    )
                    assert failed["finished_at"] == local_run.completed_at.isoformat()
                minutes = await db.get(ConversationMinuteAccount, minute_key)
                budget = await db.get(ConversationBudgetAccount, prepared.scope_id)
                assert minutes is not None and budget is not None
                assert (minutes.snapshot, budget.snapshot) == before_accounts
                assert (await AuditRepository(db).verify_chain(prepared.state.tenant_id)).valid
                if mode == "backoff":
                    assert job.status == "retry_wait" and job.available_at > datetime.now(UTC)
                if mode == "live":
                    assert job.status == "leased" and job.lease_token == work.lease_token
                after_completed_at = local_run.completed_at
            if recovered:
                async with sessions() as db, db.begin():
                    with pytest.raises(LeaseLostError):
                        await prepared.worker._job(db, work)
            assert await prepared.worker.claim() is None
            async with sessions() as db:
                local_run = await db.get(ConversationRun, prepared.run_id)
                assert local_run is not None and local_run.completed_at == after_completed_at
                assert len(
                    list(
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == ACTION,
                                AuditEvent.resource_id == str(work.job_id),
                            )
                        )
                    )
                ) == int(recovered)
        finally:
            await engine.dispose()

    run(exercise())
