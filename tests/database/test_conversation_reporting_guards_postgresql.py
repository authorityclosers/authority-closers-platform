"""Guard cases for synthetic C4/C5 provider jobs on disposable PostgreSQL."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationQuote,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import (
    ReportingBroker,
    completed_checkpoint,
    enqueue,
    text_quote,
)
from tests.database.test_conversation_worker_postgresql import (
    _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def _queued_c4(
    postgres_harness: Any, tmp_path: Path
) -> tuple[Any, Any, Any, ReportingBroker, ConversationInferenceWorker, UUID]:
    """Create a ready recording with one completed C4 fact chunk."""

    await asyncio.to_thread(tmp_path.mkdir, parents=True, exist_ok=True)
    prepared = await prepare_local(postgres_harness, tmp_path)
    assert await prepared.worker.run_once()
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    broker = ReportingBroker(prepared.data)
    worker = ConversationInferenceWorker(sessions, prepared.storage, broker)

    from tests.database.test_conversation_inference_postgresql import _provider_quote

    quote_id, quote = await _provider_quote(
        sessions,
        prepared.state,
        prepared.recording_id,
        prepared.scope_id,
        hashlib.sha256(prepared.data).hexdigest(),
    )
    asr = await enqueue(sessions, prepared, quote_id, quote, None, "guards-asr")
    assert await worker.run_once()
    c2 = await completed_checkpoint(sessions, asr)
    facts = StageRequest(stage="C4", transcript_checkpoint_id=c2)
    quote_id, quote = await text_quote(sessions, prepared, facts)
    fact_view = await enqueue(sessions, prepared, quote_id, quote, facts, "guards-facts")
    assert await worker.run_once()
    c4 = await completed_checkpoint(sessions, fact_view)
    return prepared, engine, sessions, broker, worker, c4


async def _queued_c5(
    postgres_harness: Any, tmp_path: Path, broker: ReportingBroker | None = None
) -> tuple[Any, Any, Any, ReportingBroker, ConversationInferenceWorker, dict[str, Any]]:
    """Create a queued C5 job with a completed source transcript and facts."""

    prepared, engine, sessions, default_broker, worker, c4 = await _queued_c4(
        postgres_harness, tmp_path
    )
    if broker is not None:
        broker.routes[:] = default_broker.routes
        broker.calls = default_broker.calls
        broker.payloads[:] = default_broker.payloads
        worker = ConversationInferenceWorker(sessions, prepared.storage, broker)
    coaching = StageRequest(
        stage="C5",
        transcript_checkpoint_id=(await _transcript_checkpoint(sessions, prepared.recording_id)),
        fact_checkpoint_ids=(c4,),
        max_completion_tokens=1_800,
    )
    quote_id, quote = await text_quote(sessions, prepared, coaching)
    view = await enqueue(sessions, prepared, quote_id, quote, coaching, "guards-coaching")
    return prepared, engine, sessions, (broker or default_broker), worker, view


async def _transcript_checkpoint(sessions: Any, recording_id: UUID) -> UUID:
    async with sessions() as db:
        row = await db.scalar(
            select(ConversationCheckpoint)
            .where(
                ConversationCheckpoint.recording_id == recording_id,
                ConversationCheckpoint.stage == "C2",
            )
            .order_by(ConversationCheckpoint.created_at)
        )
        assert row is not None
        return row.id


def test_c5_rejects_missing_incomplete_and_foreign_fact_checkpoints(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        first, engine, sessions, broker, _, c4_first = await _queued_c4(
            postgres_harness, tmp_path / "first"
        )
        foreign, foreign_engine, foreign_sessions, foreign_broker, _, c4_foreign = await _queued_c4(
            postgres_harness, tmp_path / "foreign"
        )
        try:
            c2_first = await _transcript_checkpoint(sessions, first.recording_id)
            incomplete = StageRequest.model_construct(
                stage="C5",
                transcript_checkpoint_id=c2_first,
                fact_checkpoint_ids=(),
                chunk_index=1,
                model="llama-3.3-70b-versatile",
                max_input_chars=16_000,
                max_completion_tokens=1_800,
                profile=None,
            )
            with pytest.raises(ValidationError, match="complete fact checkpoints"):
                await text_quote(sessions, first, incomplete)

            with pytest.raises(ConversationConflict, match="saved analysis"):
                await text_quote(
                    sessions,
                    first,
                    StageRequest(
                        stage="C5",
                        transcript_checkpoint_id=c2_first,
                        fact_checkpoint_ids=(uuid4(),),
                        max_completion_tokens=1_800,
                    ),
                )

            with pytest.raises(ConversationConflict, match="saved analysis"):
                await text_quote(
                    sessions,
                    first,
                    StageRequest(
                        stage="C5",
                        transcript_checkpoint_id=c2_first,
                        fact_checkpoint_ids=(c4_foreign,),
                        max_completion_tokens=1_800,
                    ),
                )
            assert broker.routes == ["elevenlabs", "groq"]
            assert foreign_broker.routes == ["elevenlabs", "groq"]
            assert c4_first != c4_foreign
        finally:
            await engine.dispose()
            await foreign_engine.dispose()

    run(exercise())


@pytest.mark.parametrize("revocation", ["identity", "quote"])
def test_revoked_identity_or_quote_blocks_queued_c5_before_groq(
    postgres_harness: Any, tmp_path: Path, revocation: str
) -> None:
    async def exercise() -> None:
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path / revocation
        )
        try:
            async with sessions() as db, db.begin():
                if revocation == "identity":
                    await db.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == prepared.state.session_id)
                        .values(revoked_at=datetime.now(UTC))
                    )
                else:
                    task = await db.get(ConversationInferenceTask, UUID(view["id"]))
                    assert task is not None
                    await db.execute(
                        update(ConversationQuote)
                        .where(ConversationQuote.id == task.quote_id)
                        .values(revoked_at=datetime.now(UTC))
                    )

            assert await worker.run_once()
            assert broker.routes == ["elevenlabs", "groq"]
            async with sessions() as db:
                task = await db.get(ConversationInferenceTask, UUID(view["id"]))
                assert task is not None and task.state == "failed"
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCheckpoint)
                        .where(ConversationCheckpoint.stage == "C5")
                    )
                    == 0
                )
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReportDraft)) == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


class MalformedC5Broker(ReportingBroker):
    async def execute(self, reservation: Any, payload: bytes) -> Any:
        if reservation.quote.provider_id == "groq":
            body = json.loads(payload)
            user = body["messages"][1]["content"]
            if not user.startswith("{"):
                self.routes.append("groq")
                self.calls += 1
                self.payloads.append(payload)
                envelope = {"choices": [{"message": {"content": "not-json"}}]}
                raw = canonical(envelope)
                self.response_sha256 = hashlib.sha256(raw).hexdigest()
                return ProviderResult(
                    provider="groq",
                    model=reservation.quote.provider_model,
                    request_id=f"synthetic-malformed-{self.calls}",
                    response_sha256=self.response_sha256,
                    raw_json=raw,
                    data=envelope,
                    usage={"total_tokens": 0},
                    input_sha256=reservation.quote.input_sha256,
                )
        return await super().execute(reservation, payload)


def test_malformed_c5_keeps_private_raw_response_without_c6_or_report(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        broker = MalformedC5Broker(b"synthetic")
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path, broker
        )
        try:
            assert await worker.run_once()
            assert broker.routes == ["elevenlabs", "groq", "groq"]
            assert broker.response_sha256 is not None
            assert any(
                key.kind.value == "provider-response"
                for key in prepared.storage.list_recording(
                    prepared.state.tenant_id, prepared.recording_id
                )
            )
            async with sessions() as db:
                task = await db.get(ConversationInferenceTask, UUID(view["id"]))
                run_row = await db.get(ConversationRun, UUID(view["id"]))
                job = None if task is None else await db.get(Job, task.job_id)
                assert task is not None and task.state == "uncertain"
                assert run_row is not None and run_row.state == "failed"
                assert job is not None and job.provider_receipt is None
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCheckpoint)
                        .where(ConversationCheckpoint.stage.in_(("C5", "C6")))
                    )
                    == 0
                )
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReportDraft)) == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_c5_receipt_survives_ack_crash_and_restart_does_not_regenerate_report(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        prepared, engine, sessions, broker, worker, view = await _queued_c5(
            postgres_harness, tmp_path
        )
        try:
            work = await worker.claim()
            assert work is not None
            original_complete = JobRepository.complete
            failed_once = False

            async def crash_ack(*args: Any, **kwargs: Any) -> Any:
                nonlocal failed_once
                if not failed_once:
                    failed_once = True
                    raise RuntimeError("synthetic c5 acknowledgement crash")
                return await original_complete(*args, **kwargs)

            monkeypatch.setattr(JobRepository, "complete", crash_ack)
            with pytest.raises(RuntimeError, match="synthetic c5 acknowledgement crash"):
                await worker._dispatch(work)
            monkeypatch.undo()
            assert broker.routes == ["elevenlabs", "groq", "groq"]
            async with sessions() as db, db.begin():
                task = await db.get(ConversationInferenceTask, UUID(view["id"]))
                assert task is not None
                job = await db.get(Job, task.job_id)
                assert job is not None and job.provider_receipt is not None
                job.leased_until = datetime.now(UTC) - timedelta(minutes=1)
                c6_count = await db.scalar(
                    select(func.count())
                    .select_from(ConversationCheckpoint)
                    .where(ConversationCheckpoint.stage == "C6")
                )
                draft_count = await db.scalar(
                    select(func.count()).select_from(ConversationReportDraft)
                )
                assert c6_count == 1 and draft_count == 1
            restarted_broker = ReportingBroker(prepared.data)
            restarted = ConversationInferenceWorker(sessions, prepared.storage, restarted_broker)
            assert await restarted.run_once()
            assert restarted_broker.calls == 0
            async with sessions() as db:
                task = await db.get(ConversationInferenceTask, UUID(view["id"]))
                assert task is not None
                job = await db.get(Job, task.job_id)
                assert job is not None and job.status == "succeeded"
                assert job.provider_receipt is not None
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationReportDraft)) == 1
                )
        finally:
            await engine.dispose()

    run(exercise())
