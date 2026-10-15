"""Fictional canonical loader and capture-lock proof; no failure settlement yet."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.acquisition_usage import acquisition_seconds
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.customer_failure_candidate import (
    locked_recovered_customer_failure,
)
from ac_platform.conversation_intelligence.guest_models import (
    ConversationProcessingLease,
    ConversationProcessingPrincipal,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import INFERENCE_JOB
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.intake import ConversationIntake
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_failure_observation_postgresql import RefusalBroker
from tests.database.test_conversation_guest_ownership_postgresql import (
    _guest,
    _processing_actor,
    _provision,
)
from tests.database.test_conversation_intake_postgresql import make_intent, policy
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, seed_budget
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


async def prepare(engine, scratch, *, expired=False, owner_kind="guest"):
    state = await seed(engine, role="owner" if owner_kind == "organisation" else "learner")
    if expired:
        state = replace(state, now=state.now - timedelta(hours=2))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    await _reconcile(sessions, state)
    scope = await seed_budget(engine)
    await _provision(engine, state)
    credential = None
    if owner_kind == "guest":
        credential, measured, intent, usage_id = await _guest(
            engine, state, duration_seconds=7, marker=uuid4().hex
        )
        actor = await _processing_actor(engine, state, measured.submission_id, credential.token)
    else:
        assert owner_kind in {"personal", "organisation"}
        intent = make_intent(f"fictional-personal-{uuid4().hex}".encode()).model_copy(
            update={"duration_ms": 7000}
        )
        measured = MeasuredSource(uuid4(), intent.source_sha256, 7000, uuid4().hex * 2)
        async with sessions() as db, db.begin():
            intake_sessions = AcquisitionSessions(
                db,
                tenant_id=state.tenant_id,
                policy_revision="fictional-owner",
                clock=lambda: state.now,
            )
            usage_id = await intake_sessions.reserve(measured, actor=state.actor)
            actor = await GuestOwnership(intake_sessions).resolve_processing_actor(
                measured.submission_id, actor=state.actor
            )
    async with sessions() as db, db.begin():
        intake = ConversationIntake(
            ConversationApplication(db, clock=lambda: state.now), policy(scope, state.tenant_id)
        )
        view = await intake.prepare(actor, intent, key="fictional-failed-source")
        recording_id = UUID(view["recording_id"])
        recording = await db.get(ConversationRecording, recording_id)
        recording.state = "ready"
        run_id = uuid4()
        job = await JobRepository(db).enqueue(
            tenant_id=state.tenant_id,
            kind=INFERENCE_JOB,
            dedupe_key=str(run_id),
            payload={"schema": 1, "run_id": str(run_id)},
            external_side_effect=True,
            max_attempts=1,
        )
        job.status = "dead_letter"
        job.attempt_count = 1
        job.dead_lettered_at = state.now
        job.last_error = "Fictional exhausted worker"
        db.add(
            ConversationRun(
                id=run_id,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                recording_id=recording_id,
                request_key=str(run_id),
                intent_sha256="a" * 64,
                recipe_revision="fictional-recovery-v1",
                generation=1,
                state="queued",
                job_id=job.id,
                created_at=state.now,
            )
        )
        await db.flush()
        db.add(
            ConversationInferenceTask(
                run_id=run_id,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                recording_id=recording_id,
                processing_lease_id=actor.processing_lease_id,
                session_id=None,
                job_id=job.id,
                quote_id=UUID(view["id"]),
                generation=1,
                stage="C2",
                cache_key=uuid4().hex * 2,
                input_sha256="b" * 64,
                intent_sha256="c" * 64,
                intent={"fictional": True},
                state="queued",
                created_at=state.now,
            )
        )
    worker = ConversationInferenceWorker(
        sessions, PrivateLocalRecordingStorage(scratch / "objects"), RefusalBroker()
    )
    async with sessions() as db, db.begin():
        await worker._recover_terminal_job(db, job.recovery_generation)
        original = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == actor.tenant_id,
                AuditEvent.action == "conversation.provider_job_recovery_required",
            )
        )
        assert original is not None
        event_id = original.id
    return SimpleNamespace(
        sessions=sessions,
        state=state,
        actor=actor,
        run_id=run_id,
        event_id=event_id,
        recording_id=recording_id,
        job_id=job.id,
        usage_id=usage_id,
        visitor_id=credential.visitor_id if credential else None,
        credential_token=credential.token if credential else None,
    )


def candidate(db, f, **changes):
    return locked_recovered_customer_failure(
        db,
        actor=changes.get("actor", f.actor),
        run_id=changes.get("run_id", f.run_id),
        event_id=changes.get("event_id", f.event_id),
    )


def test_locked_candidate_is_exact_repeatable_and_does_not_release(postgres_harness, tmp_path):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            # Issue the fixture admission on an earlier clock; never alter its
            # immutable expiry. This authorizes no execution after that window.
            f = await prepare(engine, tmp_path, expired=True)
            async with f.sessions() as db:
                lease = await db.get(ConversationProcessingLease, f.actor.processing_lease_id)
                assert lease.expires_at < datetime.now(UTC)
            counts = []
            queries = []

            def capture(*args):
                queries.append(args[2])

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            for _ in range(2):
                queries.clear()
                async with f.sessions() as db, candidate(db, f) as receipt:
                    assert receipt.usage_id == str(f.usage_id)
                    assert receipt.run_id == str(f.run_id)
                    assert receipt.reserved_seconds == 7
                    assert receipt.failure_event_id == str(f.event_id)
                counts.append(len(queries))
            event.remove(engine.sync_engine, "before_cursor_execute", capture)
            assert counts == [13, 13]
            async with f.sessions() as db:
                assert await db.get(ConversationAcquisitionSettlement, f.usage_id) is None
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.actor.tenant_id, visitor_id=f.visitor_id
                    )
                    == 7
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    "fault",
    [
        "tenant",
        "person",
        "lease",
        "event",
        "run",
        "source",
        "generation",
        "worker_generation",
        "running",
        "cancelled",
        "erased",
        "missing_completion",
        "no_work",
        "capture",
        "draft",
        "unknown_event",
        "revoked_lease",
        "completion_changed",
        "revoked_principal",
        "suspended_processing_person",
        "deleted_source",
    ],
)
def test_unrelated_changed_or_settled_facts_cannot_qualify(postgres_harness, tmp_path, fault):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepare(engine, tmp_path)
            changes = {}
            async with f.sessions() as db, db.begin():
                task = await db.get(ConversationInferenceTask, f.run_id)
                row = await db.get(ConversationRun, f.run_id)
                if fault in {"tenant", "person", "lease"}:
                    field = {
                        "tenant": "tenant_id",
                        "person": "person_id",
                        "lease": "processing_lease_id",
                    }[fault]
                    wrong = (await seed(engine)).tenant_id if fault == "tenant" else uuid4()
                    changes["actor"] = replace(f.actor, **{field: wrong})
                elif fault in {"event", "run"}:
                    changes[fault + "_id"] = uuid4()
                elif fault == "source":
                    recording = await db.get(ConversationRecording, f.recording_id)
                    recording.source_sha256 = "e" * 64
                elif fault == "generation":
                    row.generation += 1
                elif fault == "worker_generation":
                    job = await db.get(Job, f.job_id)
                    job.recovery_generation += 1
                elif fault in {"running", "cancelled"}:
                    row.state = task.state = fault
                elif fault == "erased":
                    task.erased_at = f.state.now
                    task.intent = None
                elif fault == "missing_completion":
                    row.completed_at = None
                elif fault == "completion_changed":
                    row.completed_at += timedelta(seconds=1)
                elif fault == "revoked_lease":
                    lease = await db.get(ConversationProcessingLease, f.actor.processing_lease_id)
                    lease.revoked_at = f.state.now
                elif fault == "revoked_principal":
                    principal = await db.scalar(
                        select(ConversationProcessingPrincipal).where(
                            ConversationProcessingPrincipal.person_id == f.actor.person_id
                        )
                    )
                    principal.revoked_at = f.state.now
                elif fault == "suspended_processing_person":
                    person = await db.get(Person, f.actor.person_id)
                    person.status = "suspended"
                elif fault == "deleted_source":
                    recording = await db.get(ConversationRecording, f.recording_id)
                    recording.state = "deleted"
                    recording.deleted_at = f.state.now
                elif fault in {"no_work", "capture"}:
                    await AcquisitionSessions(
                        db, tenant_id=f.actor.tenant_id, policy_revision="fictional-terminal-v1"
                    ).settle(
                        f.usage_id,
                        charged_seconds=0 if fault == "no_work" else 7,
                        receipt_sha256="d" * 64,
                        no_work=fault == "no_work",
                    )
                elif fault == "draft":
                    db.add(
                        ConversationReportDraft(
                            id=uuid4(),
                            tenant_id=f.actor.tenant_id,
                            person_id=f.actor.person_id,
                            recording_id=f.recording_id,
                            run_id=f.run_id,
                            source_revision=1,
                            source_sha256=(
                                await db.get(ConversationAcquisitionUsage, f.usage_id)
                            ).source_sha256,
                            report_sha256="a" * 64,
                            transcript_sha256="b" * 64,
                            profile_sha256="c" * 64,
                            evidence_receipt_sha256="d" * 64,
                            payload=None,
                            transcript=None,
                            evidence_receipt=None,
                            created_at=f.state.now,
                        )
                    )
                elif fault == "unknown_event":
                    original = await AuditRepository(db).append(
                        tenant_id=f.actor.tenant_id,
                        actor_type="system",
                        actor_person_id=None,
                        action="conversation.unrelated",
                        resource_type="job",
                        resource_id=f.job_id,
                        payload={},
                        now=f.state.now,
                    )
                    changes["event_id"] = original.id
            async with f.sessions() as db:
                with pytest.raises(ConversationConflict):
                    async with candidate(db, f, **changes):
                        pytest.fail("changed canonical facts qualified")
            if fault == "running":
                # The module shares one disposable queue. End this deliberately
                # live fixture so the next recovery selects its own new job.
                async with f.sessions() as db, db.begin():
                    task = await db.get(ConversationInferenceTask, f.run_id)
                    row = await db.get(ConversationRun, f.run_id)
                    task.state = row.state = "cancelled"
        finally:
            await engine.dispose()

    run(exercise())


def test_job_contention_fails_closed_without_lock_inversion(postgres_harness, tmp_path):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepare(engine, tmp_path)
            async with f.sessions() as locker, locker.begin():
                await locker.scalar(select(Job).where(Job.id == f.job_id).with_for_update())

                async def contender():
                    async with f.sessions() as db, candidate(db, f):
                        pytest.fail("contended job qualified")

                with pytest.raises(ConversationConflict):
                    await asyncio.wait_for(contender(), 2)
            async with f.sessions() as db, candidate(db, f):
                pass
        finally:
            await engine.dispose()

    run(exercise())


def test_capture_serializes_and_is_rechecked_after_candidate(postgres_harness, tmp_path):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepare(engine, tmp_path)
            entered = asyncio.Event()

            async def capture():
                async with f.sessions() as db, db.begin():
                    entered.set()
                    await AcquisitionSessions(
                        db, tenant_id=f.actor.tenant_id, policy_revision="fictional-terminal-v1"
                    ).settle(f.usage_id, charged_seconds=7, receipt_sha256="d" * 64)

            async with f.sessions() as db, candidate(db, f):
                pending = asyncio.create_task(capture())
                await entered.wait()
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(pending), 0.1)
            await asyncio.wait_for(pending, 2)
            async with f.sessions() as db:
                with pytest.raises(ConversationConflict):
                    async with candidate(db, f):
                        pytest.fail("captured usage qualified")
        finally:
            await engine.dispose()

    run(exercise())


def test_preexisting_transaction_is_rejected_and_caller_abort_rolls_back(
    postgres_harness, tmp_path
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepare(engine, tmp_path)
            async with f.sessions() as db, db.begin():
                with pytest.raises(ConversationConflict):
                    async with candidate(db, f):
                        pytest.fail("existing transaction qualified")
            async with f.sessions() as db:
                with pytest.raises(RuntimeError, match="fictional audit abort"):
                    async with candidate(db, f):
                        await db.execute(
                            update(ConversationRun)
                            .where(ConversationRun.id == f.run_id)
                            .values(state="cancelled")
                        )
                        raise RuntimeError("fictional audit abort")
            async with f.sessions() as db, candidate(db, f):
                pass
        finally:
            await engine.dispose()

    run(exercise())
