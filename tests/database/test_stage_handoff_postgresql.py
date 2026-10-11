"""Real worker completions wake the accepted plan without rewriting history."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import update

from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.stage_handoff import (
    committed_work_listener,
    notify_work,
)
from tests.database.test_conversation_authority_postgresql import _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _accept, _quote, _view
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_provider_completion_makes_plan_immediately_due(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "handoff")
            await _accept(setup, quote, "handoff-accept")
            identifier = UUID(quote["id"])
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            for _ in range(12):
                # Completion must override even a distant fallback schedule.
                future = datetime.now(UTC) + timedelta(minutes=1)
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationProcessingPlan)
                        .where(ConversationProcessingPlan.id == identifier)
                        .values(next_check_at=future)
                    )
                assert await setup.worker.run_once()
                async with setup.sessions() as db:
                    plan = await db.get(ConversationProcessingPlan, identifier)
                    assert plan is not None and plan.next_check_at < future
                assert await scheduler.step()
                if (await _view(setup, identifier))["state"] == "completed":
                    break
            assert (await _view(setup, identifier))["report_ready"] is True
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_notifications_are_commit_bound_and_listener_closes(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with committed_work_listener(
                setup.engine.url.render_as_string(hide_password=False)
            ) as wakeups:
                for event in wakeups:
                    await asyncio.wait_for(event.wait(), 2)
                    event.clear()
                async with setup.sessions() as db:
                    await notify_work(db)
                    await asyncio.sleep(0.02)
                    assert all(not event.is_set() for event in wakeups)
                    await db.rollback()
                await asyncio.sleep(0.02)
                assert all(not event.is_set() for event in wakeups)
                async with setup.sessions() as db, db.begin():
                    await notify_work(db)
                for event in wakeups:
                    await asyncio.wait_for(event.wait(), 2)
            assert not any(
                task.get_name() == "conversation-committed-work-listener"
                for task in asyncio.all_tasks()
            )
        finally:
            await setup.engine.dispose()

    run(exercise())
