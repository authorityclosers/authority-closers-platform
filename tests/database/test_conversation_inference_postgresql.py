"""Disposable PostgreSQL proof for the external C2 inference lifecycle.

Only a synthetic local broker is used.  The loopback database and private
storage fixture are disposable; no provider credentials or network calls are
permitted by these tests.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import (
    ExecutionPermission,
    MinuteAccount,
    Quote,
)
from ac_platform.conversation_intelligence.inference import TRANSCRIPT_RECIPE, ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationRecording,
    ConversationReview,
    ConversationRun,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.storage import ObjectKey, ObjectKind
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _provider_quote(
    sessions: async_sessionmaker[AsyncSession],
    state: Any,
    recording_id: UUID,
    scope_id: UUID,
    source_sha256: str,
    *,
    quote_source_sha256: str | None = None,
    provider_id: str = "elevenlabs",
    provider_model: str = "scribe_v2",
    permission_fingerprint: str | None = None,
) -> tuple[UUID, Quote]:
    now = datetime.now(UTC)
    quoted_source_sha256 = quote_source_sha256 or source_sha256
    quote = Quote(
        quote_id=str(uuid4()),
        source=SourceBinding(
            str(state.tenant_id), str(recording_id), quoted_source_sha256, "1"
        ),
        account_id=str(state.person_id),
        budget_scope_id=str(scope_id),
        provider_id=provider_id,
        provider_model=provider_model,
        recipe_revision=TRANSCRIPT_RECIPE,
        operation="transcribe_scribe_v2",
        input_sha256=source_sha256,
        privacy_revision="synthetic-provider-privacy-v1",
        permission_ref=str(state.permission_id),
        provider_terms_ref="synthetic-provider-terms",
        retention_ref="synthetic-provider-retention",
        professional_gate_ref="synthetic-provider-gate",
        pricing_ref="synthetic-zero-price",
        entitlement_seconds=1,
        max_cost_paise=0,
        created_at_epoch=int(now.timestamp()) - 1,
        expires_at_epoch=int(now.timestamp()) + 3600,
    )
    permission = ExecutionPermission(
        "synthetic-provider-execution-approval",
        permission_fingerprint or quote.fingerprint,
        str(state.person_id),
        int(now.timestamp()) + 3600,
    )
    quote_id = UUID(quote.quote_id)
    async with sessions() as database, database.begin():
        database.add(
            ConversationQuote(
                id=quote_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=recording_id,
                budget_scope_id=scope_id,
                quote=quote.as_dict(),
                execution_permission=permission.as_dict(),
            )
        )
    return quote_id, quote


class FakeBroker:
    def __init__(self, data: bytes, *, mode: str = "success") -> None:
        self.data = data
        self.mode = mode
        self.calls = 0
        self.payloads: list[bytes] = []
        self.response_sha256: str | None = None

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        self.calls += 1
        self.payloads.append(payload)
        if self.mode == "failure":
            raise RuntimeError("synthetic broker failure")
        if self.mode == "timeout":
            await asyncio.sleep(1)
        raw_data = (
            {
                "text": "malformed native result",
                "words": [
                    {
                        "text": "malformed",
                        "start": "not-a-time",
                        "end": 0.5,
                        "speaker_id": "speaker_1",
                    }
                ],
            }
            if self.mode == "malformed"
            else {
                "text": "hello buyer",
                "words": [
                    {
                        "text": "hello",
                        "start": 0.0,
                        "end": 0.5,
                        "speaker_id": "speaker_1",
                    },
                    {
                        "text": "buyer",
                        "start": 0.5,
                        "end": 0.9,
                        "speaker_id": "speaker_1",
                    },
                ],
            }
        )
        raw = canonical(raw_data)
        response_sha256 = hashlib.sha256(raw).hexdigest()
        self.response_sha256 = response_sha256
        return ProviderResult(
            provider="elevenlabs",
            model="scribe_v2",
            request_id="synthetic-provider-request-1",
            response_sha256=response_sha256,
            raw_json=raw,
            data=raw_data,
            usage={"total_tokens": 0},
            input_sha256=reservation.quote.input_sha256,
        )


def test_provider_requires_exact_accepted_quote_and_owner_session(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
                with pytest.raises(Exception, match="Approve this exact recording"):
                    await service.request_transcription(
                        prepared.state.actor,
                        prepared.recording_id,
                        quote_id,
                        key="provider-without-acceptance",
                    )
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count()).select_from(ConversationInferenceTask)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count()).select_from(ConversationQuoteAcceptance)
                    )
                    == 0
                )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
            foreign = replace(prepared.state, session_id=uuid4())
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
                with pytest.raises(ConversationDenied):
                    await service.request_transcription(
                        foreign.actor,
                        prepared.recording_id,
                        quote_id,
                        key="provider-wrong-session",
                    )
        finally:
            await engine.dispose()

    run(exercise())


def test_provider_rejects_wrong_source_route_or_permission_before_queue(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        source_sha256 = hashlib.sha256(prepared.data).hexdigest()
        try:
            invalid_quotes = (
                {"quote_source_sha256": "b" * 64},
                {"provider_id": "gemini"},
                {"provider_model": "wrong-scribe-model"},
                {"permission_fingerprint": "c" * 64},
            )
            for index, options in enumerate(invalid_quotes):
                quote_id, _ = await _provider_quote(
                    sessions,
                    prepared.state,
                    prepared.recording_id,
                    prepared.scope_id,
                    source_sha256,
                    **options,
                )
                async with sessions() as database, database.begin():
                    service = ConversationInference(ConversationApplication(database))
                    with pytest.raises(ConversationDenied):
                        await service.request_transcription(
                            prepared.state.actor,
                            prepared.recording_id,
                            quote_id,
                            key=f"provider-invalid-{index}",
                        )
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count()).select_from(ConversationInferenceTask)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count()).select_from(Job).where(
                            Job.kind == "conversation.infer_provider.v1"
                        )
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_duplicate_provider_requests_reuse_one_job_and_reservation(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                first = await service.request_transcription(
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-first-key",
                )
                second = await service.request_transcription(
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-second-key",
                )
            assert first["id"] == second["id"]
            async with sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count()).select_from(ConversationInferenceTask)
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(Job.kind == "conversation.infer_provider.v1")
                    )
                    == 1
                )
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert minutes is not None
                reservations = MinuteAccount.from_dict(minutes.snapshot).reservations
                provider_reservations = [
                    reservation
                    for reservation in reservations
                    if reservation.quote.quote_id == str(quote_id)
                ]
                assert len(provider_reservations) == 1
        finally:
            await engine.dispose()

    run(exercise())


def test_success_commits_native_c2_receipt_before_ack_and_never_redispatches(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-success",
                )
            broker = FakeBroker(prepared.data)
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            assert await worker.run_once()
            assert broker.calls == 1 and broker.payloads == [prepared.data]
            async with sessions() as database:
                run_row = await database.get(ConversationRun, UUID(view["id"]))
                assert run_row is not None and run_row.state == "completed"
                task = await database.get(ConversationInferenceTask, run_row.id)
                assert task is not None and task.state == "completed"
                job = await database.get(Job, run_row.job_id)
                assert job is not None and job.status == "succeeded"
                assert job.provider_receipt is not None
                assert job.provider_receipt["response_sha256"]
                checkpoint = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C2",
                    )
                )
                assert checkpoint is not None and checkpoint.payload is not None
                assert checkpoint.payload["source_sha256"] == prepared.state.source_sha256
                assert checkpoint.payload["duration_ms"] == 1_000
                assert checkpoint.payload["revision"] == job.provider_receipt["response_sha256"]
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert minutes is not None
                assert (
                    MinuteAccount.from_dict(minutes.snapshot).reservations[1].state == "uncertain"
                )
                raw_key = ObjectKey(
                    prepared.state.tenant_id,
                    prepared.recording_id,
                    run_row.id,
                    ObjectKind.PROVIDER_RESPONSE,
                )
                assert broker.response_sha256 is not None
                assert b"hello buyer" in b"".join(
                    prepared.storage.iter_bytes(
                        raw_key,
                        expected_sha256=broker.response_sha256,
                    )
                )
            assert await worker.run_once() is False
            assert broker.calls == 1
        finally:
            await engine.dispose()

    run(exercise())


def test_receipt_commit_survives_ack_crash_and_restart_only_ack(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-ack-crash",
                )
            broker = FakeBroker(prepared.data)
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            work = await worker.claim()
            assert work is not None
            original_complete = JobRepository.complete
            failed_once = False

            async def crash_ack(*args: Any, **kwargs: Any) -> Any:
                nonlocal failed_once
                if not failed_once:
                    failed_once = True
                    raise RuntimeError("synthetic acknowledgement crash")
                return await original_complete(*args, **kwargs)

            monkeypatch.setattr(JobRepository, "complete", crash_ack)
            with pytest.raises(RuntimeError, match="synthetic acknowledgement crash"):
                await worker._dispatch(work)
            monkeypatch.undo()
            assert broker.calls == 1
            job_id: UUID
            async with sessions() as database, database.begin():
                run_row = await database.get(ConversationRun, UUID(view["id"]))
                assert run_row is not None
                job_id = run_row.job_id
                job = await database.get(Job, job_id)
                assert job is not None and job.status == "leased"
                assert job.provider_receipt is not None
                job.leased_until = datetime.now(UTC) - timedelta(minutes=1)
            restarted_broker = FakeBroker(prepared.data)
            restarted = ConversationInferenceWorker(sessions, prepared.storage, restarted_broker)
            assert await restarted.run_once()
            assert restarted_broker.calls == 0
            async with sessions() as database:
                job = await database.get(Job, job_id)
                assert job is not None and job.status == "succeeded"
                assert job.provider_receipt is not None
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("mode", ["failure", "timeout"])
def test_broker_failure_or_timeout_dead_letters_and_holds_budget(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key=f"provider-{mode}",
                )
            if mode == "timeout":
                monkeypatch.setattr(
                    "ac_platform.conversation_intelligence.inference_worker._EFFECT_SECONDS",
                    0.01,
                )
            broker = FakeBroker(prepared.data, mode=mode)
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            assert await worker.run_once()
            async with sessions() as database:
                run_row = await database.get(ConversationRun, UUID(view["id"]))
                assert run_row is not None and run_row.state == "failed"
                task = await database.get(ConversationInferenceTask, run_row.id)
                assert task is not None and task.state == "uncertain"
                job = await database.get(Job, run_row.job_id)
                assert job is not None and job.status == "dead_letter"
                assert job.provider_receipt is None
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (prepared.state.tenant_id, prepared.state.person_id),
                )
                assert minutes is not None
                assert (
                    MinuteAccount.from_dict(minutes.snapshot).reservations[1].state == "uncertain"
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_deletion_before_provider_claim_fences_inference_without_call(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-delete-before-claim",
                )
                await service.application.request_deletion(
                    prepared.state.actor,
                    prepared.recording_id,
                    key="delete-provider-before-claim",
                )
            # The local worker consumes the already queued deletion job; its
            # generation fence also cancels the queued inference task.
            assert await prepared.worker.run_once()
            broker = FakeBroker(prepared.data)
            worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            assert await worker.run_once()
            assert await worker.run_once() is False
            assert broker.calls == 0
            async with sessions() as database:
                recording = await database.get(ConversationRecording, prepared.recording_id)
                assert recording is not None and recording.state == "deleted"
                task = await database.get(ConversationInferenceTask, UUID(view["id"]))
                assert task is not None and task.erased_at is not None and task.state == "cancelled"
        finally:
            await engine.dispose()

    run(exercise())


def test_review_history_allows_one_content_erasure_only(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        review_id = uuid4()
        try:
            async with sessions() as database, database.begin():
                database.add(
                    ConversationReview(
                        id=review_id,
                        run_id=prepared.run_id,
                        tenant_id=prepared.state.tenant_id,
                        person_id=prepared.state.person_id,
                        reviewer_id=prepared.state.person_id,
                        lane="sales",
                        proposal_hash="a" * 64,
                        proposal={"summary": "synthetic draft"},
                        created_at=datetime.now(UTC),
                    )
                )
            for mutation in ("proposal_hash", "lane", "reviewer_id", "proposal"):
                async with sessions() as database:
                    try:
                        async with database.begin():
                            review = await database.get(ConversationReview, review_id)
                            assert review is not None
                            if mutation == "proposal_hash":
                                review.proposal_hash = "b" * 64
                            elif mutation == "lane":
                                review.lane = "signal"
                            elif mutation == "reviewer_id":
                                review.reviewer_id = uuid4()
                            else:
                                review.proposal = {"summary": "rewritten"}
                    except DBAPIError as error:
                        assert "review history" in str(error).lower()
                    else:
                        raise AssertionError(f"review mutation unexpectedly committed: {mutation}")
            async with sessions() as database, database.begin():
                review = await database.get(ConversationReview, review_id)
                assert review is not None
                review.proposal = None
                review.erased_at = datetime.now(UTC)
            async with sessions() as database:
                review = await database.get(ConversationReview, review_id)
                assert (
                    review is not None and review.proposal is None and review.erased_at is not None
                )
            async with sessions() as database:
                try:
                    async with database.begin():
                        review = await database.get(ConversationReview, review_id)
                        assert review is not None
                        review.proposal = {"summary": "rehydrated"}
                except DBAPIError as error:
                    assert "review history" in str(error).lower()
                else:
                    raise AssertionError("review content rehydration unexpectedly committed")
            async with sessions() as database:
                try:
                    async with database.begin():
                        review = await database.get(ConversationReview, review_id)
                        assert review is not None
                        await database.delete(review)
                except DBAPIError as error:
                    assert "review history" in str(error).lower()
                else:
                    raise AssertionError("review deletion unexpectedly committed")
        finally:
            await engine.dispose()

    run(exercise())


def test_successful_provider_recording_erasure_removes_bytes_and_keeps_receipts(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        prepared = await prepare_local(postgres_harness, tmp_path)
        assert await prepared.worker.run_once()
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            quote_id, quote = await _provider_quote(
                sessions,
                prepared.state,
                prepared.recording_id,
                prepared.scope_id,
                hashlib.sha256(prepared.data).hexdigest(),
            )
            async with sessions() as database, database.begin():
                service = ConversationInference(ConversationApplication(database))
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
                    prepared.state.actor,
                    prepared.recording_id,
                    quote_id,
                    key="provider-then-delete",
                )
            broker = FakeBroker(prepared.data)
            inference_worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
            assert await inference_worker.run_once()
            async with sessions() as database:
                audit_before = await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.tenant_id == prepared.state.tenant_id)
                )
            async with sessions() as database, database.begin():
                application = ConversationApplication(database)
                deletion = await application.request_deletion(
                    prepared.state.actor,
                    prepared.recording_id,
                    key="delete-provider-result",
                )
                assert deletion["state"] == "deleting"
            assert await prepared.worker.run_once()
            assert prepared.storage.list_recording(
                prepared.state.tenant_id, prepared.recording_id
            ) == ()
            async with sessions() as database:
                recording = await database.get(ConversationRecording, prepared.recording_id)
                assert recording is not None and recording.state == "deleted"
                task = await database.get(ConversationInferenceTask, UUID(view["id"]))
                assert task is not None and task.intent is None and task.erased_at is not None
                checkpoint = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == prepared.recording_id,
                        ConversationCheckpoint.stage == "C2",
                    )
                )
                assert checkpoint is not None
                assert checkpoint.payload is None and checkpoint.manifest is None
                audit_after = await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.tenant_id == prepared.state.tenant_id)
                )
                assert audit_before is not None and audit_after is not None
                assert audit_after >= audit_before
        finally:
            await engine.dispose()

    run(exercise())
