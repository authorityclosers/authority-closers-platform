"""Original transport evidence survives failed cleanup in a fictional local lab."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.checkpoints import (
    SourceBinding,
    build_checkpoint,
    content_hash,
)
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import MinuteAccount, Reservation
from ac_platform.conversation_intelligence.inference import INFERENCE_JOB, ConversationInference
from ac_platform.conversation_intelligence.inference_broker import InferenceBrokerError
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.conversation_intelligence.provider_failure_observation import (
    ProviderFailureObservation,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.outbox.models import Job
from ac_platform.outbox.policy import ReconciliationRequiredError
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_inference_postgresql import _provider_quote
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local

ACTION = "conversation.provider_failure_observed"
RETRY_ACTION = "conversation.provider_retry_assessed"
RECOVERY_ACTION = "conversation.provider_job_recovery_required"


async def seed_measured_fixture(sessions: Any, prepared: Any) -> None:
    """Seed the known one-second WAV's checkpoint lineage, without native execution.

    Native decoding is covered by the local-worker suite. These cases exercise
    provider failure, independent evidence transactions and cleanup only.
    """

    async with sessions() as db, db.begin():
        recording = await db.get(ConversationRecording, prepared.recording_id)
        assert recording is not None
        binding = SourceBinding(
            str(recording.tenant_id), str(recording.id), recording.source_sha256, "1"
        )
        c0_payload = {
            "source_sha256": recording.source_sha256,
            "source_bytes": recording.source_bytes,
            "content_type": recording.content_type,
            "permission_reference": str(recording.permission_id),
        }
        c0 = build_checkpoint(binding, "C0", "recording-v1", {}, (), content_hash(c0_payload))
        c1_payload = {"source_sha256": recording.source_sha256, "media_duration_ms": 1000}
        c1 = build_checkpoint(
            binding,
            "C1",
            AUDIOATLAS_RECIPE,
            {"decode_rate": 48000, "window_profile": "audioatlas-40ms-10ms"},
            (c0,),
            content_hash(c1_payload),
        )
        for checkpoint, payload in ((c0, c0_payload), (c1, c1_payload)):
            db.add(
                ConversationCheckpoint(
                    id=uuid4(),
                    tenant_id=recording.tenant_id,
                    person_id=recording.person_id,
                    recording_id=recording.id,
                    cache_key=checkpoint.cache_key,
                    manifest_sha256=checkpoint.manifest_sha256,
                    payload_sha256=checkpoint.payload_sha256,
                    stage=checkpoint.stage,
                    feature_blob_id=None,
                    manifest=checkpoint.as_dict(),
                    payload=payload,
                    created_at=datetime.now(UTC),
                )
            )


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class RefusalBroker:
    def __init__(
        self,
        *,
        incomplete: bool = False,
        mismatch: bool = False,
        nonempty: bool = False,
        status: int = 503,
        retry_after: int = 12,
        missing_evidence: bool = False,
    ) -> None:
        self.incomplete, self.mismatch = incomplete, mismatch
        self.nonempty, self.status, self.retry_after = nonempty, status, retry_after
        self.missing_evidence = missing_evidence
        self.calls = 0
        self.reservation: Reservation | None = None
        self.error: InferenceBrokerError | None = None

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        self.calls += 1
        self.reservation = reservation
        assert reservation.attempt_id is not None
        self.error = InferenceBrokerError(
            f"provider_http_{self.status}",
            failure_observation=ProviderFailureObservation(
                reservation_id=reservation.reservation_id,
                attempt_id=reservation.attempt_id,
                quote_fingerprint=reservation.quote.fingerprint,
                provider=reservation.quote.provider_id,
                model=reservation.quote.provider_model,
                operation=reservation.quote.operation,
                input_sha256=("b" * 64 if self.mismatch else hashlib.sha256(payload).hexdigest()),
                http_status=self.status,
                response_body_complete=not self.incomplete,
                response_body_observed_bytes=1 if self.nonempty else 0,
                response_body_sha256=(
                    None
                    if self.incomplete
                    else hashlib.sha256(b"x" if self.nonempty else b"").hexdigest()
                ),
                provider_request_id_sha256=hashlib.sha256(b"fictional-request").hexdigest(),
                retry_after_seconds=self.retry_after,
                diagnostic_category=None,
            ),
        )
        if self.missing_evidence:
            self.error = InferenceBrokerError(f"provider_http_{self.status}")
        raise self.error


@pytest.mark.parametrize(
    "mode",
    [
        "complete",
        "incomplete",
        "mismatch",
        "cleanup_crash",
        "assessment_crash",
        "nonempty",
        "non_retryable",
        "claim_limit",
        "authorization_window",
        "missing_evidence",
    ],
)
def test_original_observation_is_durable_but_never_a_success_or_no_charge_receipt(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await seed_measured_fixture(sessions, prepared)
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as db, db.begin():
                service = ConversationInference(ConversationApplication(db))
                await service.accept(
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    QuoteAcceptance(
                        quote_fingerprint=quote.fingerprint,
                        privacy_revision=quote.privacy_revision,
                        accepted=True,
                    ),
                )
                view = await service.request_transcription(
                    prepared.state.actor, prepared.recording_id, quote_id, key=f"refusal-{mode}"
                )
                if mode == "claim_limit":
                    queued = await db.scalar(
                        select(Job).where(Job.payload["run_id"].as_string() == view["id"])
                    )
                    assert queued is not None
                    queued.max_attempts = 1
            broker = RefusalBroker(
                incomplete=mode == "incomplete",
                mismatch=mode == "mismatch",
                nonempty=mode == "nonempty",
                status=401 if mode == "non_retryable" else 503,
                retry_after=3600 if mode == "authorization_window" else 12,
                missing_evidence=mode == "missing_evidence",
            )
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            if mode in {"cleanup_crash", "missing_evidence"}:

                async def crash_cleanup(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("fictional cleanup crash")

                monkeypatch.setattr(worker, "_fail", crash_cleanup)
            if mode == "assessment_crash":

                async def crash_assessment(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("fictional assessment crash")

                monkeypatch.setattr(worker, "_record_provider_retry_assessment", crash_assessment)
            assert await worker.run_once()
            assert broker.calls == 1
            async with sessions() as db:
                job = await db.scalar(
                    select(Job).where(Job.payload["run_id"].as_string() == view["id"])
                )
                assert job is not None
                job_id = job.id
                lease_token = job.lease_token
                generation = job.recovery_generation
                assert job.attempt_count == 1
                assert job.status == (
                    "leased" if mode in {"cleanup_crash", "missing_evidence"} else "dead_letter"
                )
                run_row = await db.get(ConversationRun, job.payload["run_id"])
                assert run_row is not None
                assert (run_row.completed_at is None) == (job.status == "leased")
                assert job.dispatch_started_at is not None
                assert job.provider_idempotency_key is not None
                assert job.provider_receipt is job.provider_receipt_digest is None
                assert job.receipt_recorded_at is None
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == ACTION, AuditEvent.resource_id == str(job.id)
                        )
                    )
                )
                assert len(events) == (0 if mode in {"mismatch", "missing_evidence"} else 1)
                if events:
                    event = events[0]
                    original_payload = event.payload
                    assert event.actor_type == "system" and event.actor_person_id is None
                    assert broker.error is not None and broker.error.failure_observation is not None
                    assert (
                        event.payload["failure_observation"]
                        == broker.error.failure_observation.as_dict()
                    )
                    assert event.payload["attempt_count"] == 1
                    assert (
                        event.payload["dispatch_started_at"] == job.dispatch_started_at.isoformat()
                    )
                    assert "fictional-request" not in str(event.payload)
                    assert (await AuditRepository(db).verify(prepared.state.tenant_id)).valid
                assessments = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == RETRY_ACTION,
                            AuditEvent.resource_id == str(job.id),
                        )
                    )
                )
                assert len(assessments) == (
                    0 if mode in {"mismatch", "assessment_crash", "missing_evidence"} else 1
                )
                if assessments:
                    assessed = assessments[0].payload
                    original_assessment = assessed
                    assert assessed["failure_event_id"] == str(event.id)
                    assert assessed["failure_event_hash"] == event.event_hash
                    assert assessed["claim_count"] == 1
                    assert assessed["claim_limit"] == (1 if mode == "claim_limit" else 3)
                    expected = {
                        "incomplete": "reconciliation_required",
                        "nonempty": "reconciliation_required",
                        "non_retryable": "non_retryable",
                        "claim_limit": "claim_limit_exhausted",
                        "authorization_window": "authorization_window_exhausted",
                    }.get(mode, "transport_retry_eligible")
                    assert assessed["assessment"]["state"] == expected
                    assert assessed["assessment"]["dispatch_authorized"] is False
                    assert assessed["assessment"]["provider_charge_state"] == "unresolved"
                    assert assessed["assessment"]["not_before"] == (
                        (event.occurred_at + timedelta(seconds=12)).isoformat()
                        if expected == "transport_retry_eligible"
                        else None
                    )
                account = await db.get(
                    ConversationMinuteAccount, (prepared.state.tenant_id, prepared.state.person_id)
                )
                assert account is not None
                reservation = next(
                    r
                    for r in MinuteAccount.from_dict(account.snapshot).reservations
                    if r.reservation_id == view["id"]
                )
                assert reservation.state == (
                    "in_flight" if mode in {"cleanup_crash", "missing_evidence"} else "uncertain"
                )
            if mode == "cleanup_crash":
                from ac_platform.conversation_intelligence.worker import Work

                assert (
                    lease_token is not None
                    and broker.reservation is not None
                    and broker.error is not None
                )
                work = Work(job_id, lease_token, generation, INFERENCE_JOB)
                # Assessment replay reads committed original evidence, and never
                # slides Retry-After when the caller clock advances.
                worker.clock = lambda: datetime.now(UTC) + timedelta(minutes=1)
                await worker._record_provider_retry_assessment(work, reservation=broker.reservation)
                with pytest.raises(ValueError, match="provider job was fenced"):
                    await worker._record_provider_retry_assessment(
                        replace(work, lease_token=uuid4()), reservation=broker.reservation
                    )
                with pytest.raises(ReconciliationRequiredError, match="stale database"):
                    await worker._record_provider_retry_assessment(
                        replace(work, recovery_generation=generation + 1),
                        reservation=broker.reservation,
                    )
                with pytest.raises(ValueError, match="binding mismatch"):
                    await worker._record_provider_retry_assessment(
                        work,
                        reservation=replace(
                            broker.reservation,
                            quote=replace(broker.reservation.quote, provider_model="other-model"),
                            permission=replace(
                                broker.reservation.permission,
                                quote_fingerprint=replace(
                                    broker.reservation.quote, provider_model="other-model"
                                ).fingerprint,
                            ),
                        ),
                    )
                # Repeated evidence is idempotent; conflicting evidence cannot replace history.
                await worker._record_provider_failure_observation(
                    work, error=broker.error, reservation=broker.reservation
                )
                with pytest.raises(ValueError, match="provider job was fenced"):
                    await worker._record_provider_failure_observation(
                        replace(work, lease_token=uuid4()),
                        error=broker.error,
                        reservation=broker.reservation,
                    )
                with pytest.raises(ReconciliationRequiredError, match="stale database"):
                    await worker._record_provider_failure_observation(
                        replace(work, recovery_generation=generation + 1),
                        error=broker.error,
                        reservation=broker.reservation,
                    )
                different = InferenceBrokerError(
                    "provider_http_503",
                    failure_observation=replace(
                        broker.error.failure_observation, retry_after_seconds=13
                    ),
                )
                with pytest.raises(ValueError, match="conflicts with history"):
                    await worker._record_provider_failure_observation(
                        work, error=different, reservation=broker.reservation
                    )
                async with sessions() as db:
                    events = list(
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == ACTION, AuditEvent.resource_id == str(job_id)
                            )
                        )
                    )
                    assert len(events) == 1 and events[0].payload == original_payload
                    assessments = list(
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == RETRY_ACTION,
                                AuditEvent.resource_id == str(job_id),
                            )
                        )
                    )
                    assert len(assessments) == 1 and assessments[0].payload == original_assessment
                    assert (await AuditRepository(db).verify(prepared.state.tenant_id)).valid
            elif mode == "missing_evidence":
                from ac_platform.conversation_intelligence.worker import Work

                assert lease_token is not None and broker.reservation is not None
                async with sessions() as db, db.begin():
                    job = await db.get(Job, job_id)
                    assert job is not None
                    job.last_error = "conversation_provider_http_503"
                with pytest.raises(ValueError, match="Original provider failure evidence"):
                    await worker._record_provider_retry_assessment(
                        Work(job_id, lease_token, generation, INFERENCE_JOB),
                        reservation=broker.reservation,
                    )
            else:
                actor = replace(prepared.state.actor, permissions=frozenset({"job_retry"}))
                async with sessions() as db, db.begin():
                    with pytest.raises(ReconciliationRequiredError, match="typed reconciliation"):
                        await JobRepository(db).retry(
                            job_id,
                            actor=actor,
                            reason="Fictional retry must remain guarded",
                            audit=AuditRepository(db),
                        )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    "mode",
    [
        "dispatched",
        "provisional",
        "exhausted",
        "backoff",
        "live",
        "erased",
        "cancelled",
        "generation",
        "validated",
        "locked",
        "audit_crash",
    ],
)
def test_terminal_job_recovery_preserves_effects_and_settlement(
    postgres_harness: Any, tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await seed_measured_fixture(sessions, prepared)
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as db, db.begin():
                service = ConversationInference(ConversationApplication(db))
                await service.accept(
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    QuoteAcceptance(
                        quote_fingerprint=quote.fingerprint,
                        privacy_revision=quote.privacy_revision,
                        accepted=True,
                    ),
                )
                await service.request_transcription(
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key=f"terminal-recovery-{mode}",
                )
            broker = RefusalBroker()
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            work = await worker.claim()
            assert work is not None
            if mode in {"dispatched", "provisional"}:
                with pytest.raises(InferenceBrokerError):
                    await worker._dispatch(work)
            async with sessions() as db, db.begin():
                job = await db.get(Job, work.job_id)
                task = await db.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.job_id == work.job_id
                    )
                )
                assert job is not None and task is not None
                run_row = await db.get(ConversationRun, task.run_id)
                assert run_row is not None
                if mode != "live":
                    job.leased_until = datetime.now(UTC) - timedelta(seconds=1)
                    job.max_attempts = job.attempt_count
                if mode == "erased":
                    task.erased_at = datetime.now(UTC)
                    task.intent = None
                if mode == "cancelled":
                    task.state = run_row.state = "cancelled"
                if mode == "generation":
                    job.recovery_generation += 1
                if mode == "validated":
                    job.provider_receipt = {"validation_state": "validated"}
                    job.provider_receipt_digest = content_hash(job.provider_receipt)
                    job.receipt_recorded_at = datetime.now(UTC)
                if mode == "provisional":
                    job.provider_receipt = {"validation_state": "provider_returned"}
                    job.provider_receipt_digest = content_hash(job.provider_receipt)
                    job.receipt_recorded_at = datetime.now(UTC)
                if mode == "backoff":
                    job.status = "retry_wait"
                    job.lease_token = job.leased_until = None
                    job.available_at = datetime.now(UTC) + timedelta(minutes=5)
                if mode in {"generation", "validated"}:
                    job.status = "dead_letter"
                    job.lease_token = job.leased_until = None
                    job.dead_lettered_at = datetime.now(UTC)
                    job.last_error = "fictional dead letter"
                before_states = (task.state, run_row.state)
                before_completed_at = run_row.completed_at
                before_effect = (
                    job.dispatch_started_at,
                    job.provider_idempotency_key,
                    job.provider_receipt,
                    job.attempt_count,
                )
                minutes = await db.get(ConversationMinuteAccount, (task.tenant_id, task.person_id))
                assert minutes is not None
                before_minutes = minutes.snapshot
                run_id = task.run_id
            if mode == "locked":
                async with sessions() as locker, locker.begin():
                    locked = await locker.scalar(
                        select(ConversationInferenceTask)
                        .where(ConversationInferenceTask.run_id == run_id)
                        .with_for_update()
                    )
                    assert locked is not None
                    assert await worker.claim() is None
                    assert locked.state == before_states[0]
            if mode == "audit_crash":
                original_append = AuditRepository.append

                async def crash_append(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("fictional recovery audit crash")

                monkeypatch.setattr(AuditRepository, "append", crash_append)
                with pytest.raises(RuntimeError, match="fictional recovery audit crash"):
                    await worker.claim()
                monkeypatch.setattr(AuditRepository, "append", original_append)
                async with sessions() as db:
                    rolled_back = await db.get(Job, work.job_id)
                    task = await db.get(ConversationInferenceTask, run_id)
                    run_row = await db.get(ConversationRun, run_id)
                    assert rolled_back is not None and rolled_back.status == "leased"
                    assert task is not None and task.state == before_states[0]
                    assert run_row is not None and run_row.completed_at == before_completed_at
            assert await worker.claim() is None
            async with sessions() as db:
                job = await db.get(Job, work.job_id)
                task = await db.get(ConversationInferenceTask, run_id)
                run_row = await db.get(ConversationRun, run_id)
                assert job is not None and task is not None and run_row is not None
                recovered = mode in {
                    "dispatched",
                    "provisional",
                    "exhausted",
                    "locked",
                    "audit_crash",
                }
                assert (task.state, run_row.state) == (
                    ("uncertain" if mode in {"dispatched", "provisional"} else "failed", "failed")
                    if recovered
                    else before_states
                )
                assert (
                    job.dispatch_started_at,
                    job.provider_idempotency_key,
                    job.provider_receipt,
                    job.attempt_count,
                ) == before_effect
                if mode == "backoff":
                    assert job.status == "retry_wait" and job.available_at > datetime.now(UTC)
                minutes = await db.get(ConversationMinuteAccount, (task.tenant_id, task.person_id))
                assert minutes is not None and minutes.snapshot == before_minutes
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == RECOVERY_ACTION,
                            AuditEvent.resource_id == str(work.job_id),
                        )
                    )
                )
                assert len(events) == int(recovered)
                assert run_row.completed_at == (
                    events[0].occurred_at if recovered else before_completed_at
                )
                assert (await AuditRepository(db).verify_chain(task.tenant_id)).valid
            if recovered:
                with pytest.raises(ConversationConflict, match="fenced"):
                    await worker._dispatch(work)
            assert await worker.claim() is None
            async with sessions() as db:
                assert (await db.get(ConversationRun, run_id)).completed_at == run_row.completed_at
                assert len(
                    list(
                        await db.scalars(
                            select(AuditEvent).where(
                                AuditEvent.action == RECOVERY_ACTION,
                                AuditEvent.resource_id == str(work.job_id),
                            )
                        )
                    )
                ) == int(recovered)
            assert broker.calls == int(mode in {"dispatched", "provisional"})
        finally:
            await engine.dispose()

    run(exercise())
