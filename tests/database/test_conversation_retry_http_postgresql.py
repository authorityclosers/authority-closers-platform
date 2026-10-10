"""Real owner HTTP retry, journal, workers and races on disposable PostgreSQL."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.acquisition_usage import acquisition_seconds
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import RetryPolicy
from tests.database.test_conversation_failure_observation_postgresql import (
    RefusalBroker,
    seed_measured_fixture,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _make_due,
    _setup,
    _sign_in,
    _upload_for_read_test,
)
from tests.database.test_conversation_worker_postgresql import (
    _postgres_harness,
    _reconcile,
    _wav_one_second_48k,
)
from tests.unit.conversation_intelligence.test_acquisition_source import ValidationFixtureRuntime
from tests.unit.conversation_intelligence.test_alignment import _signal


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("cap", [1, 2])
def test_owner_retry_preserves_source_cap_and_captures_one_delivered_report(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cap: int
) -> None:
    import asyncio

    monkeypatch.setattr(RetryPolicy, "delay_for_attempt", lambda *a, **k: timedelta(microseconds=1))

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True, c2_max_requests=cap)
        # Keep the real byte/hash/receipt validation boundary; native decoding
        # returns an explicitly fictional one-second receipt in this fixture.
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path, submission = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                import hashlib
                from types import SimpleNamespace

                progress = await client.get(path)
                assert progress.status_code == 200, progress.text
                recording_id = UUID(progress.json()["recording_id"])
                # Native decoding is a separate worker proof. This route test
                # seeds a fictional, complete signal to isolate retry semantics.
                await seed_measured_fixture(
                    setup.sessions,
                    SimpleNamespace(recording_id=recording_id),
                    signal_payload=_signal(
                        source_sha256=hashlib.sha256(_wav_one_second_48k()).hexdigest()
                    ),
                )
                first_response = await client.post(
                    path + "/plan/quote", headers={"Origin": ORIGIN, "Idempotency-Key": "original"}
                )
                assert first_response.status_code == 201
                first = first_response.json()

                async def accept(plan, key):
                    return await client.post(
                        path + "/plan",
                        json={
                            "plan_id": plan["id"],
                            "plan_fingerprint": plan["plan_fingerprint"],
                            "privacy_revision": plan["privacy_revision"],
                            "accepted": True,
                        },
                        headers={"Origin": ORIGIN, "Idempotency-Key": key},
                    )

                assert (await accept(first, "original:accept")).status_code == 202
                refusal = RefusalBroker(retry_after=0)
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, refusal, authority=setup.authority
                )
                assert await worker.run_once()
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                await _make_due(setup, UUID(first["id"]))
                assert await scheduler.step()
                async with setup.sessions() as db:
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission
                        )
                    )
                    original = await db.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == UUID(first["recording_id"])
                        )
                    )
                    original_job = await db.get(Job, original.job_id)
                    original_intent = original.intent
                    dispatch = original_job.dispatch_started_at
                    assert (
                        await acquisition_seconds(
                            db, tenant_id=usage.tenant_id, person_id=usage.person_id
                        )
                    ) == 0
                failed = await client.get(path)
                assert failed.status_code == 200
                assert (failed.json()["run_state"], failed.json()["minute_state"]) == (
                    "failed",
                    "released",
                )
                assert failed.json()["retry_available"] is True
                setup.clock[0] = datetime.now(UTC)

                async def prepare(key):
                    return await client.post(
                        path + "/retry", headers={"Origin": ORIGIN, "Idempotency-Key": key}
                    )

                if cap == 1:
                    denied = await prepare("retry:limited")
                    assert denied.status_code == 403
                    assert denied.headers["cache-control"] == "private, no-store"
                    async with setup.sessions() as db:
                        events = list(
                            await db.scalars(
                                select(ConversationReportMinuteEvent).where(
                                    ConversationReportMinuteEvent.usage_id == usage.id
                                )
                            )
                        )
                        assert [e.kind for e in events] == ["released"]
                        plans = list(
                            await db.scalars(
                                select(ConversationProcessingPlan).where(
                                    ConversationProcessingPlan.recording_id == original.recording_id
                                )
                            )
                        )
                        assert len(plans) == 1
                    assert refusal.calls == 1
                    return
                # Two tabs retry the same key. Both recover the same durable
                # plan; no extra source reservation, task or provider send.
                prepared, replay = await asyncio.gather(
                    prepare("retry:owner"), prepare("retry:owner")
                )
                assert prepared.status_code == replay.status_code == 201
                assert prepared.json()["id"] == replay.json()["id"]
                fresh = prepared.json()
                assert fresh["state"] == "quoted" and not fresh["accepted"]
                assert (await prepare("retry:other-tab")).status_code == 409
                accepted = await accept(fresh, "retry:owner:accept")
                assert accepted.status_code == 202
                assert (await accept(fresh, "retry:owner:accept")).status_code == 202
                broker = ReportingBroker(_wav_one_second_48k())
                worker.broker = broker
                for _ in range(8):
                    await worker.run_once()
                    await _make_due(setup, UUID(fresh["id"]))
                    await scheduler.step()
                progress = (await client.get(path)).json()
                assert (progress["run_state"], progress["minute_state"]) == ("done", "delivered")
                assert (await client.get(path + "/report")).status_code == 200
                async with setup.sessions() as db:
                    events = list(
                        await db.scalars(
                            select(ConversationReportMinuteEvent)
                            .where(ConversationReportMinuteEvent.usage_id == usage.id)
                            .order_by(ConversationReportMinuteEvent.revision)
                        )
                    )
                    assert [e.kind for e in events] == [
                        "released",
                        "reserved",
                        "reserved",
                        "delivered",
                    ]
                    assert (
                        await acquisition_seconds(
                            db, tenant_id=usage.tenant_id, person_id=usage.person_id
                        )
                    ) == 1
                    retained = await db.get(ConversationInferenceTask, original.run_id)
                    job = await db.get(Job, original.job_id)
                    assert retained.intent == original_intent and retained.state == "uncertain"
                    assert job.dispatch_started_at == dispatch and job.attempt_count == 1
                assert broker.calls == 3 and refusal.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())
