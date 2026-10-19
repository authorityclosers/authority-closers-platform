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

from ac_platform.conversation_intelligence.application import (
    BudgetCapReached,
    ConversationApplication,
    ConversationDenied,
    utc,
)
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import (
    NEEDS_ACCEPTANCE_CODE,
    ConversationProcessingPlans,
    PlanNeedsAcceptance,
    ProcessingPlanScheduler,
    actor_from_row,
    manifest_for,
    require_plan_consent,
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


def test_an_accepted_plan_holds_24_hours_and_a_waiting_call_resumes_inside_them(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """Accepted once, valid 24 h: past the old 1-hour limit it still continues.

    This fixture's call permission lasts 2 hours, so the resume is checked at 100
    minutes; after 24 hours the plan (and here the permission) no longer allows it.
    """

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # A release approval (and its stages) that lasts a week.
            week = int(setup.prepared.state.now.timestamp()) + 7 * 24 * 3600
            setup.bundle_box["bundle"] = setup.bundle.model_copy(
                update={
                    "expires_at_epoch": week,
                    "stages": tuple(
                        stage.model_copy(update={"expires_at_epoch": week})
                        for stage in setup.bundle.stages
                    ),
                }
            )
            quote = await _quote(setup, "validity-quote")
            await _accept(setup, quote, "validity-accept")
            plan_id = UUID(quote["id"])
            async with setup.sessions() as database:
                stored = await database.get(ConversationProcessingPlan, plan_id)
                assert stored is not None
                manifest = manifest_for(stored)
                assert manifest.expires_at_epoch - manifest.created_at_epoch == 24 * 3600
                actor = actor_from_row(stored)
            created = setup.prepared.state.now
            for later, allowed in ((timedelta(minutes=100), True), (timedelta(hours=24), False)):
                async with setup.sessions() as database, database.begin():
                    app = ConversationApplication(
                        database, clock=lambda later=later: created + later
                    )
                    row = await database.get(ConversationProcessingPlan, plan_id)
                    assert row is not None
                    if allowed:
                        await require_plan_consent(app, actor, row, setup.authority)
                    else:
                        with pytest.raises(ConversationDenied) as refused:
                            await require_plan_consent(app, actor, row, setup.authority)
                        # Expired, not a new release: the scheduler holds it as
                        # processing_budget_expired and the app offers one tap.
                        assert not isinstance(refused.value, PlanNeedsAcceptance)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_new_release_while_waiting_stops_with_needs_your_ok(
    postgres_harness: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another release could quote more: the call stops and the person taps to continue."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "release-quote")
            await _accept(setup, quote, "release-accept")
            plan_id = UUID(quote["id"])
            tasks_before = await _count(setup, ConversationInferenceTask)
            accepted = setup.authority.admit

            async def new_release(app: Any, actor: Any) -> Any:
                bundle = await accepted(app, actor)
                # A different approval: here a higher budget ceiling, so a new digest.
                return bundle.model_copy(update={"budget_cap_paise": bundle.budget_cap_paise + 1})

            monkeypatch.setattr(setup.authority, "admit", new_release)
            await _make_due(setup, plan_id)
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            assert await scheduler.step() is True
            async with setup.sessions() as database:
                stored = await database.get(ConversationProcessingPlan, plan_id)
                assert stored is not None and stored.state == "held"
                assert stored.progress["failure_code"] == NEEDS_ACCEPTANCE_CODE
            # Nothing was quoted or started under the new release.
            assert await _count(setup, ConversationInferenceTask) == tasks_before
        finally:
            await setup.engine.dispose()

    run(exercise())
