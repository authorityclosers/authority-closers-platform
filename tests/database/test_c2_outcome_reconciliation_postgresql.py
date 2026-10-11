"""Original owner retry after exact operator evidence; no real providers."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import ConversationReportMinuteEvent
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.entitlements import Quote
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationQuote,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.provider_reconciliation import (
    ACTION,
    C2OutcomeEvidence,
    record_c2_outcome,
)
from ac_platform.outbox.models import Job
from tests.database.test_conversation_failure_observation_postgresql import (
    RefusalBroker,
    seed_measured_fixture,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
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


def test_exact_confirmation_unlocks_fresh_owner_retry_without_replaying_or_charging(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True, c2_max_requests=2)
        setup.native.validate_source = ValidationFixtureRuntime().validate_source
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                path, submission_id = await _upload_for_read_test(setup, client)
                await _reconcile(setup.sessions, setup.state)
                recording_id = UUID((await client.get(path)).json()["recording_id"])
                digest = hashlib.sha256(_wav_one_second_48k()).hexdigest()
                await seed_measured_fixture(
                    setup.sessions,
                    SimpleNamespace(recording_id=recording_id),
                    signal_payload=_signal(source_sha256=digest),
                )
                quoted = await client.post(
                    path + "/plan/quote",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "outcome:quote"},
                )
                assert quoted.status_code == 201, quoted.text
                plan = quoted.json()
                accepted = await client.post(
                    path + "/plan",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "outcome:accept"},
                    json={
                        "plan_id": plan["id"],
                        "plan_fingerprint": plan["plan_fingerprint"],
                        "privacy_revision": plan["privacy_revision"],
                        "accepted": True,
                    },
                )
                assert accepted.status_code == 202, accepted.text
                refusal = RefusalBroker(missing_evidence=True)
                worker = ConversationInferenceWorker(
                    setup.sessions, setup.runtime.storage, refusal, authority=setup.authority
                )
                assert await worker.run_once()
                assert await ProcessingPlanScheduler(setup.sessions, setup.authority).step()
                before = (await client.get(path)).json()
                assert (before["run_state"], before["minute_state"]) == ("failed", "released")
                headers = {"Origin": ORIGIN, "Idempotency-Key": "outcome:retry"}
                refused = await client.post(path + "/retry", headers=headers)
                assert refused.status_code == 409
                async with setup.sessions() as db:
                    task = await db.scalar(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == recording_id,
                            ConversationInferenceTask.stage == "C2",
                        )
                    )
                    job = await db.get(Job, task.job_id)
                    quote_row = await db.get(ConversationQuote, task.quote_id)
                    quote = Quote.from_dict(quote_row.quote)
                    original_dispatch = job.dispatch_started_at
                    proof = C2OutcomeEvidence(
                        schema="ac.sales-xray.c2-outcome-evidence/1",
                        environment="development",
                        issue="AUT-1801",
                        approval_reference="AUT-1801",
                        approver_person_id=setup.state.person_id,
                        operator_person_id=setup.state.person_id,
                        tenant_id=setup.state.tenant_id,
                        submission_id=submission_id,
                        recording_id=recording_id,
                        run_id=task.run_id,
                        job_id=job.id,
                        generation=task.generation,
                        recovery_generation=job.recovery_generation,
                        attempt_count=job.attempt_count,
                        provider_attempt_id=job.provider_idempotency_key,
                        dispatch_started_at=job.dispatch_started_at,
                        source_sha256=digest,
                        quote_fingerprint=quote.fingerprint,
                        input_sha256=quote.input_sha256,
                        provider="elevenlabs",
                        model=quote.provider_model,
                        verified_at=datetime.now(UTC),
                        verification_method="provider_support",
                        provider_request_id_sha256="c" * 64,
                        provider_confirmation_sha256="d" * 64,
                        outcome="not_accepted",
                    )

                async def record(value=proof, *, apply=False):
                    async with setup.sessions() as db, db.begin():
                        return await record_c2_outcome(
                            db, value, environment="development", now=datetime.now(UTC), apply=apply
                        )

                for changes in (
                    {"outcome": "unknown"},
                    {"outcome": "completed"},
                    {"job_id": uuid4()},
                    {"input_sha256": "e" * 64},
                    {"recovery_generation": proof.recovery_generation + 1},
                    {"approver_person_id": uuid4()},
                ):
                    with pytest.raises(ConversationConflict):
                        await record(proof.model_copy(update=changes), apply=True)
                preview = await record()
                assert preview["applied"] is False and preview["event_id"] is None
                assert (await client.post(path + "/retry", headers=headers)).status_code == 409
                applied = await record(apply=True)
                replay = await record(apply=True)
                assert applied["event_id"] == replay["event_id"]
                with pytest.raises(ConversationConflict):
                    await record(
                        proof.model_copy(update={"provider_confirmation_sha256": "e" * 64}),
                        apply=True,
                    )
                async with setup.sessions() as db:
                    retained = await db.get(Job, proof.job_id)
                    assert retained.dispatch_started_at == original_dispatch
                    assert retained.status == "dead_letter" and retained.provider_receipt is None
                    events = list(
                        (
                            await db.scalars(select(AuditEvent).where(AuditEvent.action == ACTION))
                        ).all()
                    )
                    assert len(events) == 1
                setup.clock[0] = datetime.now(UTC)
                prepared = await client.post(path + "/retry", headers=headers)
                assert prepared.status_code == 201, prepared.text
                assert prepared.json()["id"] != plan["id"]
                assert refusal.calls == 1
                assert (await client.get(path)).json()["has_report"] is False
                successor = prepared.json()
                accepted = await client.post(
                    path + "/plan",
                    headers={"Origin": ORIGIN, "Idempotency-Key": "outcome:accept-successor"},
                    json={
                        "plan_id": successor["id"],
                        "plan_fingerprint": successor["plan_fingerprint"],
                        "privacy_revision": successor["privacy_revision"],
                        "accepted": True,
                    },
                )
                assert accepted.status_code == 202, accepted.text
                success = ReportingBroker(_wav_one_second_48k())
                worker.broker = success
                scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
                for _ in range(8):
                    await worker.run_once()
                    await scheduler.step()
                    delivered = (await client.get(path)).json()
                    if delivered["has_report"]:
                        break
                assert delivered["has_report"] and delivered["minute_state"] == "delivered"
                assert success.calls == 3 and refusal.calls == 1
                # Repeated reads/delivery scans cannot charge the same call again.
                assert (await client.get(path + "/report")).status_code == 200
                await scheduler.step()
                async with setup.sessions() as db:
                    link = await db.get(
                        ConversationGuestSubmission, (proof.tenant_id, proof.submission_id)
                    )
                    journals = list(
                        await db.scalars(
                            select(ConversationReportMinuteEvent).where(
                                ConversationReportMinuteEvent.usage_id == link.usage_id
                            )
                        )
                    )
                    assert sum(event.kind == "delivered" for event in journals) == 1
                    assert any(event.kind == "released" for event in journals)
                    original = await db.get(Job, proof.job_id)
                    assert original.dispatch_started_at == original_dispatch
                    assert original.status == "dead_letter" and original.provider_receipt is None
        finally:
            await setup.engine.dispose()

    run(exercise())
