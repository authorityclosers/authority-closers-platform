"""Actual durable Gemini plan, with intercepted synthetic provider responses."""

import hashlib
import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.entitlements import MinuteAccount
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationRun,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.outbox.models import Job
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _drive_to_completion,
    _make_due,
    _quote,
)
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class MaxTokensReportingBroker(ReportingBroker):
    """Return one bounded Gemini MAX_TOKENS envelope without a provider call."""

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        if reservation.quote.provider_id == "gemini":
            body = json.loads(payload)
            user = body["contents"][0]["parts"][0]["text"]
            if not user.startswith("{"):
                self.routes.append("gemini")
                self.calls += 1
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
                        "candidatesTokenCount": 3_196,
                        "totalTokenCount": 12_168,
                    },
                }
                raw = canonical(envelope)
                response_sha256 = hashlib.sha256(raw).hexdigest()
                self.response_sha256 = response_sha256
                return ProviderResult(
                    provider="gemini",
                    model=reservation.quote.provider_model,
                    request_id="synthetic-max-tokens",
                    response_sha256=response_sha256,
                    raw_json=raw,
                    data=envelope,
                    usage={
                        "promptTokenCount": 8_972,
                        "candidatesTokenCount": 3_196,
                        "totalTokenCount": 12_168,
                    },
                    input_sha256=reservation.quote.input_sha256,
                )
        return await super().execute(reservation, payload)


@pytest.mark.parametrize("funded", [False, True])
def test_server_approved_gemini_plan_reaches_private_structured_report(
    postgres_harness: Any,
    tmp_path: Any,
    funded: bool,
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            text_provider="gemini",
            funded=funded,
            text_cost_paise=25 if funded else 0,
        )
        router = FixedProviderRouter(
            {
                provider: ProviderRoute(provider, f"ref:credential:{provider}", setup.broker)
                for provider in ("elevenlabs", "gemini")
            },
            authority=setup.authority,
        )
        setup = replace(
            setup,
            worker=ConversationInferenceWorker(
                setup.sessions,
                setup.prepared.storage,
                router,
                authority=setup.authority,
            ),
        )
        try:
            quote = await _quote(setup, "gemini-plan-quote")
            assert quote["max_cost_paise"] == (50_050 if funded else 0)
            assert quote["cost_label"] == (
                "Up to ₹500.50 · approved budget" if funded else "₹0 · approved allowance"
            )
            assert [stage["provider"] for stage in quote["stages"]] == [
                "elevenlabs",
                "gemini",
                "gemini",
            ]
            assert setup.broker.calls == 0
            accepted = await _accept(setup, quote, "gemini-plan-accept")
            assert accepted["accepted"] is True
            completed = await _drive_to_completion(setup, UUID(quote["id"]))
            assert completed["state"] == "completed"
            assert setup.broker.routes == ["elevenlabs", "gemini", "gemini"]
            async with setup.sessions() as db, db.begin():
                tasks = (await db.scalars(select(ConversationInferenceTask))).all()
                assert len(tasks) == 3 and all(task.state == "completed" for task in tasks)
                coaching = next(task for task in tasks if task.stage == "C5")
                response = await ConversationReports(ConversationApplication(db)).get(
                    setup.actor, coaching.run_id
                )
                assert response["report"]["overview"]["version"] == "dipak-14-point-v1"
                assert response["report"]["review_status"] == "draft_not_dipak_adjudicated"
                assert response["report"]["source_sha256"] == setup.prepared.state.source_sha256
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_gemini_max_tokens_persists_usage_without_checkpoint_or_redispatch(
    postgres_harness: Any,
    tmp_path: Any,
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            text_provider="gemini",
            funded=True,
            text_cost_paise=25,
        )
        broker = MaxTokensReportingBroker(setup.prepared.data)
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
            quote = await _quote(setup, "gemini-max-tokens-quote")
            plan_id = UUID(quote["id"])
            accepted = await _accept(setup, quote, "gemini-max-tokens-accept")
            assert accepted["state"] == "active"
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            for _ in range(2):
                assert await setup.worker.run_once()
                await _make_due(setup, plan_id)
                await scheduler.step()

            # C2 and C4 publish normally; C5 returns MAX_TOKENS and is held
            # uncertain after its provider-returned receipt is committed.
            assert await setup.worker.run_once()
            assert broker.routes == ["elevenlabs", "gemini", "gemini"]
            assert broker.calls == 3
            async with setup.sessions() as db:
                tasks = (await db.scalars(select(ConversationInferenceTask))).all()
                coaching = next(task for task in tasks if task.stage == "C5")
                assert coaching.state == "uncertain"
                run_row = await db.get(ConversationRun, coaching.run_id)
                assert run_row is not None and run_row.state == "failed"
                job = await db.get(Job, coaching.job_id)
                assert job is not None and job.status == "dead_letter"
                assert job.last_error == "conversation_gemini_response_incomplete"
                receipt = job.provider_receipt
                assert receipt is not None
                assert receipt["provider"] == "gemini"
                assert receipt["model"] == "gemini-3.8-flash"
                assert receipt["usage"] == {
                    "promptTokenCount": 8_972,
                    "candidatesTokenCount": 3_196,
                    "totalTokenCount": 12_168,
                }
                assert receipt["validation_state"] == "provider_returned"
                assert receipt["cost_state"] == "reconciliation_required"
                assert receipt["actual_cost_paise"] is None
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationCheckpoint)
                        .where(
                            ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                            ConversationCheckpoint.stage == "C5",
                        )
                    )
                    == 0
                )
                minutes = await db.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                reservation = next(
                    item
                    for item in MinuteAccount.from_dict(minutes.snapshot).reservations
                    if item.reservation_id == str(coaching.run_id)
                )
                assert reservation.state == "uncertain"

            # The durable dead-letter and receipt fence prevent any second
            # provider execution or additional reservation transition.
            assert await setup.worker.run_once() is False
            assert broker.calls == 3
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_total_plan_cannot_exceed_shared_owner_cap_even_when_each_stage_fits(
    postgres_harness: Any,
    tmp_path: Any,
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness, tmp_path, text_provider="gemini", funded=True, text_cost_paise=30_000
        )
        try:
            # 50,000 ASR + 30,000 facts + 30,000 coaching exceeds the 100,000 cap.
            with pytest.raises(ConversationDenied, match="complete plan exceeds"):
                await _quote(setup, "gemini-plan-over-cap")
            assert setup.broker.calls == 0
        finally:
            await setup.engine.dispose()

    run(exercise())
