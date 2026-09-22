"""PostgreSQL proof for compact C4 prompt-version recovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.checkpoints import canonical, content_hash
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProcessingPlan,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_plan import (
    FACT_PROMPT_COMPACT,
    FACT_PROMPT_LEGACY,
    ProcessingPlanScheduler,
    manifest_for,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.outbox.models import Job
from tests.database import test_conversation_authority_postgresql as authority_fixtures
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _make_due,
    _quote,
)
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class LegacyC4MaxTokensBroker(ReportingBroker):
    """Hold only the legacy C4 request; all compact requests are synthetic-success."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.legacy_c4_calls = 0

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id == "gemini":
            body = json.loads(payload)
            user = body["contents"][0]["parts"][0]["text"]
            if user.startswith("{"):
                system = body["systemInstruction"]["parts"][0]["text"]
                if "FACT_OUTPUT: compact-facts-v2." not in system:
                    self.routes.append("gemini")
                    self.calls += 1
                    self.legacy_c4_calls += 1
                    self.payloads.append(payload)
                    envelope = {
                        "candidates": [
                            {
                                "finishReason": "MAX_TOKENS",
                                "content": {
                                    "role": "model",
                                    "parts": [{"text": '{"summary":"truncated"}'}],
                                },
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 8_972,
                            "candidatesTokenCount": 1_393,
                            "totalTokenCount": 10_365,
                        },
                    }
                    raw = canonical(envelope)
                    return ProviderResult(
                        provider="gemini",
                        model=reservation.quote.provider_model,
                        request_id="synthetic-legacy-c4-max-tokens",
                        response_sha256=hashlib.sha256(raw).hexdigest(),
                        raw_json=raw,
                        data=envelope,
                        usage={
                            "promptTokenCount": 8_972,
                            "candidatesTokenCount": 1_393,
                            "totalTokenCount": 10_365,
                        },
                        input_sha256=reservation.quote.input_sha256,
                    )
        return await super().execute(reservation, payload)


def test_legacy_c4_hold_is_preserved_while_compact_plan_reuses_c2(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        # Construct an initially funded synthetic approval with enough room
        # for both plan quotes, including the unreconciled first C2 hold.
        # This changes fixture creation, never a recovery-time ledger balance.
        original_bundle = authority_fixtures._bundle
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                authority_fixtures,
                "_bundle",
                lambda *args, **kwargs: original_bundle(*args, **kwargs).model_copy(
                    update={"budget_cap_paise": 150_000}
                ),
            )
            setup = await _setup(
                postgres_harness,
                tmp_path,
                funded=True,
                text_provider="gemini",
                text_cost_paise=25,
            )
        # The upgrade intentionally exercises two bounded C4 attempts: one
        # legacy hold and one compact retry. Keep the synthetic approval at
        # two requests; production approval remains the controlling limit.
        bundle = setup.bundle_box["bundle"]
        setup.bundle_box["bundle"] = bundle.model_copy(
            update={
                "stages": tuple(
                    stage.model_copy(update={"max_requests": 2, "max_completion_tokens": 1_400})
                    if stage.stage == "C4"
                    else stage
                    for stage in bundle.stages
                )
            }
        )
        broker = LegacyC4MaxTokensBroker(setup.prepared.data)
        router = FixedProviderRouter(
            {
                provider: ProviderRoute(provider, f"ref:credential:{provider}", broker)
                for provider in ("elevenlabs", "gemini")
            },
            authority=setup.authority,
        )
        setup = replace(
            setup,
            broker=broker,
            worker=ConversationInferenceWorker(
                setup.sessions,
                setup.prepared.storage,
                router,
                authority=setup.authority,
            ),
        )
        try:
            # Simulate a plan persisted by the pre-upgrade code: legacy is the
            # default and therefore absent from the serialized manifest.
            # Insert a historical legacy row.  The production trigger makes a
            # persisted plan immutable, so migration coverage must represent
            # the pre-upgrade row at insert time rather than editing it.
            compact_quote = await _quote(setup, "legacy-fact-prompt-quote")
            async with setup.sessions() as database, database.begin():
                quoted_plan = await database.get(
                    ConversationProcessingPlan, UUID(compact_quote["id"])
                )
                assert quoted_plan is not None and quoted_plan.manifest is not None
                compact_manifest = manifest_for(quoted_plan)
                assert compact_manifest.fact_prompt_revision == FACT_PROMPT_COMPACT
                legacy_manifest = compact_manifest.model_copy(
                    update={"fact_prompt_revision": FACT_PROMPT_LEGACY}
                )
                legacy_plan_id = uuid4()
                legacy_plan_sha256 = content_hash(legacy_manifest.as_dict())
                legacy_plan = ConversationProcessingPlan(
                    id=legacy_plan_id,
                    tenant_id=quoted_plan.tenant_id,
                    person_id=quoted_plan.person_id,
                    recording_id=quoted_plan.recording_id,
                    session_id=quoted_plan.session_id,
                    processing_lease_id=quoted_plan.processing_lease_id,
                    generation=quoted_plan.generation,
                    plan_sha256=legacy_plan_sha256,
                    manifest=legacy_manifest.as_dict(),
                    acceptance_command_id=None,
                    state="quoted",
                    progress={},
                    next_check_at=quoted_plan.next_check_at,
                    created_at=quoted_plan.created_at,
                    expires_at=quoted_plan.expires_at,
                    erased_at=None,
                )
                database.add(legacy_plan)
            legacy_quote = {"id": str(legacy_plan_id), "plan_fingerprint": legacy_plan_sha256}

            await _accept(setup, legacy_quote, "legacy-fact-prompt-accept")
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)

            # C2 completes once, then the legacy C4 call returns MAX_TOKENS and
            # is durably held with its provider receipt and reservation.
            assert await setup.worker.run_once()
            await _make_due(setup, legacy_plan_id)
            assert await scheduler.step()
            assert await setup.worker.run_once()
            await _make_due(setup, legacy_plan_id)
            assert await scheduler.step()

            async with setup.sessions() as database:
                tasks = (
                    await database.scalars(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == setup.prepared.recording_id
                        )
                    )
                ).all()
                c2_task = next(task for task in tasks if task.stage == "C2")
                legacy_c4_task = next(task for task in tasks if task.stage == "C4")
                assert c2_task.state == "completed"
                assert legacy_c4_task.state == "uncertain"
                old_c4_run_id = legacy_c4_task.run_id
                old_c4_job_id = legacy_c4_task.job_id
                old_c4_cache_key = legacy_c4_task.cache_key
                old_run = await database.get(ConversationRun, old_c4_run_id)
                old_job = await database.get(Job, old_c4_job_id)
                old_plan = await database.get(ConversationProcessingPlan, legacy_plan_id)
                assert old_plan is not None and old_plan.state == "held"
                old_command = await database.get(
                    ConversationCommand, old_plan.acceptance_command_id
                )
                assert old_run is not None and old_run.state == "failed"
                assert old_job is not None and old_job.status == "dead_letter"
                assert old_job.last_error == "conversation_gemini_response_incomplete"
                assert old_job.provider_receipt is not None
                assert old_job.provider_receipt["validation_state"] == "provider_returned"
                old_provider_receipt = canonical(old_job.provider_receipt)
                assert old_plan.progress == {
                    "current_stage": "C4",
                    "failure_code": "stage_uncertain",
                }
                assert old_command is not None and old_command.action == "processing_plan_accepted"
                old_acceptance_command_hash = old_command.intent_sha256
                minutes = await database.get(
                    # The provider reservation is recorded in the durable minute ledger.
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                old_reservation = next(
                    item
                    for item in MinuteAccount.from_dict(minutes.snapshot).reservations
                    if item.reservation_id == str(old_c4_run_id)
                )
                assert old_reservation.state == "uncertain"
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert budget is not None
                old_budget_reservation = next(
                    item
                    for item in BudgetAccount.from_dict(budget.snapshot).reservations
                    if item.reservation_id == str(old_c4_run_id)
                )
                assert old_budget_reservation.state == "uncertain"

            assert broker.legacy_c4_calls == 1
            assert broker.calls == 2

            # A fresh plan selects facts-v2. Its C2 stage must reuse the exact
            # completed transcript, while its C4 cache key is distinct.
            compact_quote = await _quote(setup, "compact-fact-prompt-quote")
            compact_plan_id = UUID(compact_quote["id"])
            async with setup.sessions() as database:
                compact_plan = await database.get(ConversationProcessingPlan, compact_plan_id)
                assert compact_plan is not None and compact_plan.manifest is not None
                assert compact_plan.manifest["fact_prompt_revision"] == FACT_PROMPT_COMPACT
            accepted = await _accept(setup, compact_quote, "compact-fact-prompt-accept")
            assert accepted["state"] == "active"

            assert await setup.worker.run_once()  # compact C4
            await _make_due(setup, compact_plan_id)
            assert await scheduler.step()  # enqueue C5
            assert await setup.worker.run_once()  # C5
            await _make_due(setup, compact_plan_id)
            assert await scheduler.step()  # publish C6/report

            async with setup.sessions() as database, database.begin():
                tasks = (
                    await database.scalars(
                        select(ConversationInferenceTask).where(
                            ConversationInferenceTask.recording_id == setup.prepared.recording_id
                        )
                    )
                ).all()
                c2_tasks = [task for task in tasks if task.stage == "C2"]
                c4_tasks = [task for task in tasks if task.stage == "C4"]
                c5_task = next(task for task in tasks if task.stage == "C5")
                assert len(c2_tasks) == 1 and c2_tasks[0].run_id == c2_task.run_id
                assert c2_tasks[0].checkpoint_id == c2_task.checkpoint_id
                assert c2_tasks[0].state == "completed"
                assert len(c4_tasks) == 2
                compact_c4_task = next(task for task in c4_tasks if task.run_id != old_c4_run_id)
                legacy_c4_after = next(task for task in c4_tasks if task.run_id == old_c4_run_id)
                assert legacy_c4_after.state == "uncertain"
                assert legacy_c4_after.cache_key == old_c4_cache_key
                assert compact_c4_task.state == "completed"
                assert compact_c4_task.cache_key != old_c4_cache_key
                assert c5_task.state == "completed"
                assert (
                    await database.scalar(
                        select(ConversationCheckpoint.id).where(
                            ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                            ConversationCheckpoint.stage == "C4",
                        )
                    )
                    is not None
                )
                compact_plan = await database.get(ConversationProcessingPlan, compact_plan_id)
                assert compact_plan is not None and compact_plan.state == "completed"
                report = await ConversationReports(ConversationApplication(database)).get(
                    setup.actor, c5_task.run_id
                )
                assert report["report"] is not None

                # The failed legacy run, dead-letter receipt, hold and
                # append-only acceptance history remain addressable unchanged.
                old_run_after = await database.get(ConversationRun, old_c4_run_id)
                old_job_after = await database.get(Job, old_c4_job_id)
                old_plan_after = await database.get(ConversationProcessingPlan, legacy_plan_id)
                assert old_plan_after is not None and old_plan_after.state == "held"
                old_command_after = await database.get(
                    ConversationCommand, old_plan_after.acceptance_command_id
                )
                assert old_run_after is not None and old_run_after.state == "failed"
                assert old_job_after is not None and old_job_after.status == "dead_letter"
                assert old_job_after.provider_receipt is not None
                assert canonical(old_job_after.provider_receipt) == old_provider_receipt
                assert old_job_after.last_error == "conversation_gemini_response_incomplete"
                assert old_plan_after.progress == {
                    "current_stage": "C4",
                    "failure_code": "stage_uncertain",
                }
                assert old_command_after is not None
                assert old_command_after.intent_sha256 == old_acceptance_command_hash
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                old_reservation_after = next(
                    item
                    for item in MinuteAccount.from_dict(minutes.snapshot).reservations
                    if item.reservation_id == str(old_c4_run_id)
                )
                assert old_reservation_after == old_reservation
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert budget is not None
                old_budget_reservation_after = next(
                    item
                    for item in BudgetAccount.from_dict(budget.snapshot).reservations
                    if item.reservation_id == str(old_c4_run_id)
                )
                assert old_budget_reservation_after == old_budget_reservation
            assert broker.calls == 4
        finally:
            await setup.engine.dispose()

    run(exercise())
