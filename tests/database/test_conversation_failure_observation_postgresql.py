"""Original transport evidence survives failed cleanup in a fictional local lab."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
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
    ConversationMinuteAccount,
    ConversationRecording,
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
    def __init__(self, *, incomplete: bool = False, mismatch: bool = False) -> None:
        self.incomplete, self.mismatch = incomplete, mismatch
        self.calls = 0
        self.reservation: Reservation | None = None
        self.error: InferenceBrokerError | None = None

    async def execute(self, reservation: Reservation, payload: bytes) -> ProviderResult:
        self.calls += 1
        self.reservation = reservation
        assert reservation.attempt_id is not None
        self.error = InferenceBrokerError(
            "provider_http_503",
            failure_observation=ProviderFailureObservation(
                reservation_id=reservation.reservation_id,
                attempt_id=reservation.attempt_id,
                quote_fingerprint=reservation.quote.fingerprint,
                provider=reservation.quote.provider_id,
                model=reservation.quote.provider_model,
                operation=reservation.quote.operation,
                input_sha256=("b" * 64 if self.mismatch else hashlib.sha256(payload).hexdigest()),
                http_status=503,
                response_body_complete=not self.incomplete,
                response_body_observed_bytes=0,
                response_body_sha256=(None if self.incomplete else hashlib.sha256(b"").hexdigest()),
                provider_request_id_sha256=hashlib.sha256(b"fictional-request").hexdigest(),
                retry_after_seconds=12,
                diagnostic_category=None,
            ),
        )
        raise self.error


@pytest.mark.parametrize("mode", ["complete", "incomplete", "mismatch", "cleanup_crash"])
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
            broker = RefusalBroker(incomplete=mode == "incomplete", mismatch=mode == "mismatch")
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            if mode == "cleanup_crash":

                async def crash_cleanup(*args: Any, **kwargs: Any) -> None:
                    raise RuntimeError("fictional cleanup crash")

                monkeypatch.setattr(worker, "_fail", crash_cleanup)
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
                assert job.status == ("leased" if mode == "cleanup_crash" else "dead_letter")
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
                assert len(events) == (0 if mode == "mismatch" else 1)
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
                    "in_flight" if mode == "cleanup_crash" else "uncertain"
                )
            if mode == "cleanup_crash":
                from ac_platform.conversation_intelligence.worker import Work

                assert (
                    lease_token is not None
                    and broker.reservation is not None
                    and broker.error is not None
                )
                work = Work(job_id, lease_token, generation, INFERENCE_JOB)
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
                    assert (await AuditRepository(db).verify(prepared.state.tenant_id)).valid
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
