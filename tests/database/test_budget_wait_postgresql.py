"""A scheduled call out of AI budget waits and resumes by itself (owner, 19 Oct 2026).

Before: the scheduler marked the plan "held" and nothing ever resumed it. Now it
stays active with budget_cap_reached, is rechecked in about a minute, and the
next pass continues it once the budget allows. Disposable loopback PostgreSQL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence.application import BudgetCapReached, utc
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    ProcessingPlanScheduler,
)
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _count,
    _make_due,
    _quote,
    _setup,
    _view,
)
from tests.database.test_conversation_processing_plan_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


def test_a_call_out_of_budget_waits_and_continues_on_a_later_pass(
    postgres_harness: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "budget-wait-quote")
            await _accept(setup, quote, "budget-wait-accept")
            plan_id = UUID(quote["id"])
            tasks_before = await _count(setup, ConversationInferenceTask)
            await _make_due(setup, plan_id)

            async def out_of_budget(self: Any, actor: Any, row: Any) -> None:
                raise BudgetCapReached(
                    "The remaining approved processing allowance is unavailable."
                )

            monkeypatch.setattr(ConversationProcessingPlans, "advance", out_of_budget)
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            started = datetime.now(UTC)
            assert await scheduler.step() is True
            assert (await _view(setup))["state"] == "active"
            async with setup.sessions() as database:
                stored = await database.get(ConversationProcessingPlan, plan_id)
                assert stored is not None and stored.state == "active"
                assert stored.progress["failure_code"] == "budget_cap_reached"
                wait = utc(stored.next_check_at) - started
                assert timedelta(seconds=50) <= wait <= timedelta(seconds=70) or utc(
                    stored.next_check_at
                ) == utc(stored.expires_at)
            # Nothing was half-started, and it isn't due again yet.
            assert await _count(setup, ConversationInferenceTask) == tasks_before
            assert await scheduler.step() is False

            # The budget allows it again: the next pass continues the same plan.
            resumed: list[UUID] = []

            async def continues(self: Any, actor: Any, row: Any) -> None:
                resumed.append(row.id)
                row.progress = {"current_stage": "C2"}

            monkeypatch.setattr(ConversationProcessingPlans, "advance", continues)
            await _make_due(setup, plan_id)
            assert await scheduler.step() is True
            assert resumed == [plan_id]
            async with setup.sessions() as database:
                stored = await database.get(ConversationProcessingPlan, plan_id)
                assert stored is not None and stored.state == "active"
                assert "failure_code" not in stored.progress
        finally:
            await setup.engine.dispose()

    run(exercise())
