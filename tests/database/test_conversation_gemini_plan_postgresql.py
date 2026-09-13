"""Actual durable Gemini plan, with intercepted synthetic provider responses."""

from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.broker_router import FixedProviderRouter, ProviderRoute
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import ConversationInferenceTask
from ac_platform.conversation_intelligence.report_store import ConversationReports
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _drive_to_completion,
    _quote,
)
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


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
