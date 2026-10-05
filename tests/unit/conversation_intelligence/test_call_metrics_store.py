"""Fictional migrated store/erasure checks; upstream provider admission is stubbed."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.application import DELETE_JOB, ConversationApplication
from ac_platform.conversation_intelligence.call_metrics import stored_summary
from ac_platform.conversation_intelligence.call_metrics_models import ConversationCallMetrics
from ac_platform.conversation_intelligence.checkpoints import build_checkpoint, content_hash
from ac_platform.conversation_intelligence.inference import ConversationInference, binding_for
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.reporting_pipeline import ReportingPipeline
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import JobRepository, RecoveryStateRepository
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_worker_postgresql import _reconcile

SEGMENTS = [
    {"id": "s1", "speaker_id": "speaker_0", "start_ms": 0, "end_ms": 500, "text": "Price?"},
    {"id": "s2", "speaker_id": "speaker_1", "start_ms": 700, "end_ms": 1000, "text": "Later."},
]


def test_model_builds_on_sqlite_and_erased_summary_is_sql_null() -> None:
    engine = create_engine("sqlite://")
    table = ConversationCallMetrics.__table__
    table.create(engine)
    now = datetime.now(UTC)
    usage_id = uuid4()
    row = dict(
        usage_id=usage_id,
        tenant_id=uuid4(),
        submission_id=uuid4(),
        recording_id=uuid4(),
        report_draft_id=uuid4(),
        rules="call-metrics/2",
        summary=stored_summary(SEGMENTS, 1000),
        summary_sha256="a" * 64,
        outcome_kind="follow_up",
        created_at=now,
    )
    try:
        with engine.begin() as connection:
            connection.execute(table.insert().values(**row))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(table.insert().values(**row))
        with engine.begin() as connection:
            connection.execute(
                table.update().values(summary=None, outcome_kind=None, erased_at=now)
            )
            assert (
                connection.scalar(text("SELECT summary IS NULL FROM conversation_call_metrics"))
                == 1
            )
            assert connection.scalar(select(table.c.summary_sha256)) == "a" * 64
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@pytest.fixture
def retention_harness():
    # A separate migrated schema keeps each deadline test independent of older calls.
    yield from _postgres_harness.__wrapped__()


def test_metrics_migration_is_forward_only() -> None:
    config = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    migration = ScriptDirectory.from_config(config).get_revision("20261003_0071")
    assert migration is not None
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.module.downgrade()


async def _source(engine, *, retention_days=None):
    state = await seed(engine)
    usage_id = uuid4()
    async with AsyncSession(engine) as database, database.begin():
        application = ConversationApplication(database, clock=lambda: state.now)
        if retention_days is not None:
            permission = await database.get(ConversationPermission, state.permission_id)
            permission.retention_until = state.now + timedelta(days=retention_days)
        view = await application.register(state.actor, state.recording_intent, key="metrics-source")
        recording = await database.get(ConversationRecording, UUID(view["id"]))
        assert recording is not None
        usage = ConversationAcquisitionUsage(
            id=usage_id,
            tenant_id=state.tenant_id,
            person_id=state.person_id,
            visitor_id=None,
            submission_id=uuid4(),
            source_sha256=state.source_sha256,
            duration_evidence_sha256="a" * 64,
            reserved_seconds=1,
            policy_revision="metrics-fictional-v1",
            created_at=state.now,
        )
        database.add(usage)
        await database.flush()
        pipeline = ReportingPipeline(ConversationInference(application))
        transcript = {"revision": "fictional-metrics-revision", "segments": deepcopy(SEGMENTS)}
        binding = binding_for(recording)
        c0 = build_checkpoint(binding, "C0", "synthetic-source-v1", {}, (), "a" * 64)
        c1 = build_checkpoint(binding, "C1", "synthetic-timing-v1", {}, (c0,), "b" * 64)
        c2 = build_checkpoint(
            binding,
            "C2",
            "synthetic-metrics-transcript-v1",
            {},
            (c0,),
            content_hash(transcript),
        )
        transcript_row = await pipeline.save(recording, c2, transcript)
        c3 = build_checkpoint(binding, "C3", "synthetic-align-v1", {}, (c1, c2), "c" * 64)
        c4 = build_checkpoint(binding, "C4", "synthetic-facts-v1", {}, (c2, c3), "d" * 64)
        return state, recording.id, usage_id, transcript_row.id, c4


async def _finish(database, source, monkeypatch, *, outcome="follow_up"):
    state, recording_id, usage_id, transcript_id, c4 = source
    application = ConversationApplication(database, clock=lambda: state.now)
    monkeypatch.setattr(application, "_receipt", AsyncMock())
    pipeline = ReportingPipeline(ConversationInference(application))
    recording = await database.get(ConversationRecording, recording_id)
    usage = await database.get(ConversationAcquisitionUsage, usage_id)
    monkeypatch.setattr(
        "ac_platform.conversation_intelligence.guest_ownership.admit_processing_actor",
        AsyncMock(return_value=usage),
    )
    job = Job(
        tenant_id=state.tenant_id, kind="synthetic-metrics", dedupe_key=uuid4().hex, payload={}
    )
    database.add(job)
    await database.flush()
    report_run = ConversationRun(
        id=uuid4(),
        tenant_id=state.tenant_id,
        person_id=state.person_id,
        recording_id=recording_id,
        request_key=uuid4().hex,
        intent_sha256="b" * 64,
        recipe_revision="synthetic-metrics-v1",
        generation=1,
        state="completed",
        job_id=job.id,
        created_at=state.now,
        completed_at=state.now,
    )
    database.add(report_run)
    await database.flush()
    normalized = {
        "overview": {
            "outcome": None
            if outcome is None
            else {
                "kind": outcome,
                "text": "Private fictional outcome words.",
                "evidence": [],
            }
        }
    }
    c5 = build_checkpoint(
        binding_for(recording),
        "C5",
        "synthetic-metrics-report-v1",
        {"run_id": str(report_run.id)},
        (c4,),
        content_hash(normalized),
    )
    c5_row = await pipeline.save(recording, c5, normalized)
    task = SimpleNamespace(
        person_id=state.person_id,
        tenant_id=state.tenant_id,
        session_id=None,
        processing_lease_id=uuid4(),
        run_id=report_run.id,
        quote_id=uuid4(),
    )
    monkeypatch.setattr(
        pipeline,
        "provider_task",
        AsyncMock(
            return_value=(
                task,
                {"response_sha256": "c" * 64},
            )
        ),
    )
    transcript = {"revision": "fictional-metrics-revision", "segments": deepcopy(SEGMENTS)}
    plan = SimpleNamespace(
        request=SimpleNamespace(
            transcript_checkpoint_id=transcript_id, coaching_prompt_revision="coaching-v6"
        ),
        profile={"revision": "synthetic-metrics-v1"},
        transcript=transcript,
        native_transcript=transcript,
        duration_ms=1000,
    )
    await pipeline.finish(
        recording,
        task,
        report_run,
        plan,
        c5_row,
        normalized,
        SimpleNamespace(response_sha256="d" * 64),
    )


@pytest.mark.parametrize("failure", [None, "compute", "insert"])
def test_first_report_is_atomic_and_metrics_failure_does_not_fail_it(
    postgres_harness,
    monkeypatch,
    caplog,
    failure,
) -> None:
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            source = await _source(engine)
            if failure == "compute":

                def broken(*_args):
                    raise ValueError("Private fictional transcript must not enter logs.")

                monkeypatch.setattr(
                    "ac_platform.conversation_intelligence.reporting_pipeline.stored_summary",
                    broken,
                )

            def invalid_reference(_mapper, _connection, target):
                target.report_draft_id = uuid4()  # real PostgreSQL FK violation

            if failure == "insert":
                event.listen(ConversationCallMetrics, "before_insert", invalid_reference)
            try:
                async with AsyncSession(engine) as database, database.begin():
                    await _finish(database, source, monkeypatch)
            finally:
                if failure == "insert":
                    event.remove(ConversationCallMetrics, "before_insert", invalid_reference)
            async with AsyncSession(engine) as database:
                settlement = await database.get(ConversationAcquisitionSettlement, source[2])
                assert settlement is not None and settlement.kind == "completed"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(ConversationReportDraft.recording_id == source[1])
                    )
                    == 1
                )
                metrics = await database.get(ConversationCallMetrics, source[2])
                if failure:
                    assert metrics is None
                else:
                    assert metrics is not None and metrics.rules == "call-metrics/2"
                    assert metrics.summary == stored_summary(SEGMENTS, 1000)
                    assert metrics.summary_sha256 == content_hash(metrics.summary)
                    assert metrics.outcome_kind == "follow_up"
                    assert metrics.recording_id == source[1]
                    assert "Private fictional outcome words" not in str(metrics.summary)
                    first_draft_id = metrics.report_draft_id
            # A subsequent report retains the first summary, or the first skip.
            async with AsyncSession(engine) as database, database.begin():
                await _finish(database, source, monkeypatch, outcome="closed")
            async with AsyncSession(engine) as database:
                metrics = await database.get(ConversationCallMetrics, source[2])
                assert (metrics is None) == (failure is not None)
                if metrics is not None:
                    assert metrics.report_draft_id == first_draft_id
                    assert metrics.outcome_kind == "follow_up"
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(ConversationReportDraft.recording_id == source[1])
                    )
                    == 2
                )
        finally:
            await engine.dispose()

    run(exercise())
    messages = [record.getMessage() for record in caplog.records]
    expected = {"compute": "ValueError", "insert": "IntegrityError"}
    assert messages == ([] if failure is None else [f"call_metrics_skipped {expected[failure]}"])


@pytest.mark.parametrize("retention_days", [7, 730])
@pytest.mark.parametrize("reason", ["expiry", "explicit"])
def test_metrics_inherit_recording_retention_and_clear_on_erasure(
    retention_harness,
    monkeypatch,
    retention_days,
    reason,
) -> None:
    async def exercise():
        engine = create_async_engine(retention_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            source = await _source(engine, retention_days=retention_days)
            state, recording_id, usage_id, _, _ = source
            await _reconcile(sessions, state)
            async with sessions() as database, database.begin():
                await _finish(database, source, monkeypatch)
            deadline = state.now + timedelta(days=retention_days)
            erase_time = deadline if reason == "expiry" else state.now + timedelta(hours=1)
            scheduler = ConversationRetentionScheduler(
                sessions, clock=lambda: erase_time - timedelta(seconds=1)
            )
            assert not await scheduler.step()
            async with sessions() as database:
                metrics = await database.get(ConversationCallMetrics, usage_id)
                assert metrics.summary == stored_summary(SEGMENTS, 1000)
                assert metrics.outcome_kind == "follow_up" and metrics.erased_at is None
                provenance = (
                    metrics.summary_sha256,
                    metrics.rules,
                    metrics.tenant_id,
                    metrics.submission_id,
                    metrics.report_draft_id,
                    metrics.created_at,
                )
            if reason == "expiry":
                scheduler = ConversationRetentionScheduler(sessions, clock=lambda: erase_time)
                assert await scheduler.step()
                assert not await scheduler.step()
            else:
                async with sessions() as database, database.begin():
                    await ConversationApplication(
                        database, clock=lambda: erase_time
                    ).request_deletion(state.actor, recording_id, key="fictional-explicit-erasure")
            async with sessions() as database:
                metrics = await database.get(ConversationCallMetrics, usage_id)
                assert metrics.summary is not None and metrics.erased_at is None
                recording = await database.get(ConversationRecording, recording_id)
                assert recording.state == "deleting"
            # No source objects were registered in this fictional fixture. Confirm
            # that empty adapter erasure and use the real lease and finish hook.
            async with sessions() as database, database.begin():
                recovery = await RecoveryStateRepository(database).require_ready(
                    lock=True, shared_lock=True
                )
                jobs = await JobRepository(database).claim(kinds={DELETE_JOB}, now=erase_time)
                assert len(jobs) == 1 and jobs[0].payload["recording_id"] == str(recording_id)
                job_id, token, generation = (
                    jobs[0].id,
                    jobs[0].lease_token,
                    recovery.generation,
                )
            async with sessions() as database, database.begin():
                await ConversationApplication(database, clock=lambda: erase_time).finish_erasure(
                    job_id=job_id, lease_token=token, recovery_generation=generation
                )
            async with sessions() as database:
                metrics = await database.get(ConversationCallMetrics, usage_id)
                assert metrics.summary is None and metrics.outcome_kind is None
                assert metrics.erased_at == erase_time
                assert (
                    metrics.summary_sha256,
                    metrics.rules,
                    metrics.tenant_id,
                    metrics.submission_id,
                    metrics.report_draft_id,
                    metrics.created_at,
                ) == provenance
                assert await database.scalar(
                    select(ConversationCallMetrics.summary.is_(None)).where(
                        ConversationCallMetrics.usage_id == usage_id
                    )
                )
                recording = await database.get(ConversationRecording, recording_id)
                assert recording.state == "deleted" and recording.deleted_at == erase_time
                draft = await database.get(ConversationReportDraft, metrics.report_draft_id)
                assert draft.payload is None and draft.erased_at == erase_time
                settlement = await database.get(ConversationAcquisitionSettlement, usage_id)
                assert settlement.kind == "completed"
        finally:
            await engine.dispose()

    run(exercise())


def test_outer_transaction_rollback_removes_report_settlement_and_metrics(
    postgres_harness,
    monkeypatch,
) -> None:
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            source = await _source(engine)
            with pytest.raises(RuntimeError, match="fictional outer rollback"):
                async with AsyncSession(engine) as database, database.begin():
                    await _finish(database, source, monkeypatch, outcome=None)
                    metrics = await database.get(ConversationCallMetrics, source[2])
                    assert metrics is not None and metrics.outcome_kind is None
                    raise RuntimeError("fictional outer rollback")
            async with AsyncSession(engine) as database:
                assert await database.get(ConversationAcquisitionSettlement, source[2]) is None
                assert await database.get(ConversationCallMetrics, source[2]) is None
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(ConversationReportDraft.recording_id == source[1])
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())
