"""A 503 gets a distinct approved successor, never a replayed dispatch marker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.conversation_intelligence.reporting_pipeline import FACT_RECIPE
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import RetryPolicy
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_failure_observation_postgresql import (
    RefusalBroker,
    seed_measured_fixture,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness
from tests.unit.conversation_intelligence.test_alignment import _signal


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("failed_stage", ["C2", "C4", "C5"])
def test_refusal_successor_finishes_without_replaying_original(
    postgres_harness: Any, tmp_path: Any, failed_stage: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The production backoff is tested separately. Keep this end-to-end fixture
    # on the real database clock, with an elapsed deterministic tiny backoff.
    monkeypatch.setattr(RetryPolicy, "delay_for_attempt", lambda *a, **k: timedelta(microseconds=1))

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, complete_local_fixture=False)
        now = setup.prepared.state.now
        try:
            # Full-shaped synthetic signal, not native decode/quality evidence.
            await seed_measured_fixture(
                setup.sessions,
                setup.prepared,
                signal_payload=_signal(source_sha256=setup.prepared.state.source_sha256),
            )
            # Explicit synthetic three-send approval. The implementation must
            # still refuse a source whose approved provider cap is one.
            setup.bundle_box["bundle"] = setup.bundle.model_copy(
                update={
                    "stages": tuple(
                        stage.model_copy(update={"max_requests": 3})
                        for stage in setup.bundle.stages
                    ),
                }
            )
            original_broker = setup.broker
            refusal = RefusalBroker(retry_after=0)

            class Once:
                refused = False

                async def execute(self, reservation, payload):
                    stage = (
                        "C2"
                        if reservation.quote.operation == "transcribe_scribe_v2"
                        else "C4"
                        if reservation.quote.recipe_revision == FACT_RECIPE
                        else "C5"
                    )
                    # C4 and C5 share a provider operation; recipe is canonical.
                    if reservation.quote.recipe_revision == "qualitative-coaching-v1":
                        stage = "C5"
                    if stage == failed_stage and not self.refused:
                        self.refused = True
                        return await refusal.execute(reservation, payload)
                    return await original_broker.execute(reservation, payload)

            setup.worker.broker = Once()
            errors = []
            fail = setup.worker._fail

            async def observed_fail(work, **arguments):
                error = arguments.get("error")
                errors.append((type(error).__name__, str(error)))
                await fail(work, **arguments)

            setup.worker._fail = observed_fail

            async def quote_and_accept(key: str, retry_of: UUID | None = None):
                async with setup.sessions() as db, db.begin():
                    service = ConversationProcessingPlans(
                        ConversationApplication(db, clock=lambda: now), setup.authority
                    )
                    quote = await service.quote(
                        setup.actor, setup.prepared.recording_id, key=key, retry_of=retry_of
                    )
                    accepted = await service.accept(
                        setup.actor,
                        setup.prepared.recording_id,
                        PlanAcceptance(
                            plan_id=UUID(quote["id"]),
                            plan_fingerprint=quote["plan_fingerprint"],
                            privacy_revision=quote["privacy_revision"],
                            accepted=True,
                        ),
                        key=key + ":accept",
                    )
                    return UUID(accepted["id"])

            async def advance(plan_id: UUID):
                async with setup.sessions() as db, db.begin():
                    service = ConversationProcessingPlans(
                        ConversationApplication(db, clock=lambda: now), setup.authority
                    )
                    row = await db.get(ConversationProcessingPlan, plan_id, with_for_update=True)
                    await service.advance(setup.actor, row)
                    return service.view(row)

            first_id = await quote_and_accept("original-plan")
            for _ in range(8):
                await setup.worker.run_once()
                first = await advance(first_id)
                if first["state"] == "held":
                    break
            assert first["state"] == "held"
            assert refusal.calls == 1
            async with setup.sessions() as db:
                original = await db.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.recording_id == setup.prepared.recording_id,
                        ConversationInferenceTask.state == "uncertain",
                    )
                )
                assert original is not None and original.stage == failed_stage
                original_job = await db.get(Job, original.job_id)
                original_intent, original_key = original.intent, original.cache_key
                original_dispatch = original_job.dispatch_started_at
                original_attempts = original_job.attempt_count
            now = datetime.now(UTC)
            second_id = await quote_and_accept("retry-plan", original.run_id)
            assert second_id != first_id
            for _ in range(8):
                await setup.worker.run_once()
                second = await advance(second_id)
                if second["state"] in {"completed", "held"}:
                    break
            async with setup.sessions() as db:
                diagnostics = list(
                    (
                        await db.execute(
                            select(
                                ConversationInferenceTask.stage,
                                ConversationInferenceTask.state,
                                Job.last_error,
                            )
                            .join(Job, Job.id == ConversationInferenceTask.job_id)
                            .where(
                                ConversationInferenceTask.recording_id
                                == setup.prepared.recording_id
                            )
                        )
                    ).all()
                )
            assert second["state"] == "completed", (second.get("failure_code"), diagnostics, errors)
            assert second["report_ready"]
            async with setup.sessions() as db:
                retained = await db.get(ConversationInferenceTask, original.run_id)
                job = await db.get(Job, original.job_id)
                assert retained.state == "uncertain"
                assert retained.intent == original_intent and retained.cache_key == original_key
                assert job.status == "dead_letter"
                assert (
                    job.dispatch_started_at == original_dispatch
                    and job.attempt_count == original_attempts
                )
                tasks = list(
                    await db.scalars(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == setup.prepared.recording_id,
                            ConversationInferenceTask.stage == failed_stage,
                        )
                    )
                )
                assert len(tasks) == 2
                successor = next(t for t in tasks if t.run_id != original.run_id)
                assert successor.state == "completed"
                assert successor.intent["checkpoint"]["replicate"] == f"retry:{original.run_id}"
                assert successor.cache_key != original.cache_key
            assert refusal.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())
