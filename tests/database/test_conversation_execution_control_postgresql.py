"""Real disposable PostgreSQL; synthetic provider, no external inference."""

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.execution_control import (
    ConversationExecutionPaused,
    ExecutionControls,
    execution_state,
)
from ac_platform.conversation_intelligence.execution_control_models import (
    ConversationExecutionControl,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
)
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from ac_platform.identity.models import Person
from ac_platform.outbox.models import Job
from tests.database.test_conversation_authority_postgresql import (
    _application,
    _issue,
    _setup,
    _start,
    completed_checkpoint,
)
from tests.database.test_conversation_authority_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run, seed


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def controls(setup, database, *, environment="test"):
    return ExecutionControls(
        _application(setup, database),
        environment=environment,
        operations_tenant_id=setup.actor.tenant_id,
    )


async def pause(setup, *, value=True, revision=0, key="pause"):
    async with setup.sessions() as database, database.begin():
        return await controls(setup, database).set_paused(
            setup.actor, paused=value, expected_revision=revision, key=key
        )


def test_control_history_scope_auth_idempotency_and_immutability(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        try:
            first = await pause(setup)
            assert first == await pause(setup)
            with pytest.raises(ConversationConflict):
                await pause(setup, value=False, revision=0, key="conflicting-key")
            async with setup.sessions() as database, database.begin():
                service = controls(setup, database)
                with pytest.raises(ConversationDenied):
                    await service.current(replace(setup.actor, permissions=frozenset()))
                with pytest.raises(ConversationDenied):
                    await service.current(replace(setup.actor, tenant_id=uuid4()))
                assert not (
                    await execution_state(
                        database,
                        environment="production",
                        operations_tenant_id=setup.actor.tenant_id,
                    )
                )["paused"]
            resumed = await pause(setup, value=False, revision=1, key="resume")
            assert resumed["revision"] == 2 and not resumed["paused"]
            async with setup.sessions() as database, database.begin():
                view = await controls(setup, database).current(setup.actor)
                assert [r["paused"] for r in view["history"]] == [False, True]
            with pytest.raises(DBAPIError):
                async with setup.sessions() as database, database.begin():
                    await database.execute(
                        update(ConversationExecutionControl)
                        .where(ConversationExecutionControl.tenant_id == setup.actor.tenant_id)
                        .values(paused=False)
                    )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_paused_pinned_queued_work_retains_budget_and_never_dispatches(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path, funded=True)
        try:
            quote = await _issue(setup, key="before-pause")
            started = await _start(setup, quote, key="queued-old-config")
            work = await setup.worker.claim()
            assert work is not None
            async with setup.sessions() as database:
                before = (
                    await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                ).snapshot
            await pause(setup)
            with pytest.raises(ConversationExecutionPaused):
                await _issue(setup, key="paused-quote")
            with pytest.raises(ConversationExecutionPaused):
                await _start(setup, quote, key="paused-existing-start")
            # Existing quote/config and already-claimed job cannot bypass pause.
            with pytest.raises(ConversationExecutionPaused):
                await setup.worker._dispatch(work)
            assert setup.broker.calls == 0
            async with setup.sessions() as database, database.begin():
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert budget.snapshot == before
                job = await database.get(Job, work.job_id)
                assert job.dispatch_started_at is None
                task = await database.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.run_id == UUID(started["id"])
                    )
                )
                assert task.state == "queued"
                # Generic admission and retained recording reads remain usable.
                await setup.authority.admit(_application(setup, database), setup.actor)
                await _application(setup, database).get(setup.actor, setup.prepared.recording_id)
            await pause(setup, value=False, revision=1, key="resume")
            await setup.worker._dispatch(work)
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_saved_report_is_readable_while_new_analysis_is_paused(
    postgres_harness: Any, tmp_path: Path
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        try:
            transcript = await _start(setup, await _issue(setup, key="c2-q"), key="c2")
            assert await setup.worker.run_once()
            c2 = await completed_checkpoint(setup.sessions, transcript)
            fact_request = StageRequest(stage="C4", transcript_checkpoint_id=c2)
            facts = await _start(
                setup,
                await _issue(setup, key="c4-q", request=fact_request),
                key="c4",
                request=fact_request,
            )
            assert await setup.worker.run_once()
            c4 = await completed_checkpoint(setup.sessions, facts)
            report_request = StageRequest(
                stage="C5", transcript_checkpoint_id=c2, fact_checkpoint_ids=(c4,)
            )
            report_run = await _start(
                setup,
                await _issue(setup, key="c5-q", request=report_request),
                key="c5",
                request=report_request,
            )
            assert await setup.worker.run_once()
            await pause(setup)
            async with setup.sessions() as database, database.begin():
                result = await ConversationReports(_application(setup, database)).get(
                    setup.actor, UUID(report_run["id"])
                )
                assert result["report"]["summary"] == "A synthetic draft from saved facts."
            assert await setup.worker.claim() is None
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_another_admin_can_pause_while_an_already_started_effect_finishes(
    postgres_harness, tmp_path
):
    async def exercise():
        setup = await _setup(postgres_harness, tmp_path)
        operator = await seed(setup.engine, tenant_id=setup.actor.tenant_id, role="admin")
        async with setup.sessions() as database, database.begin():
            await database.execute(
                update(Person)
                .where(Person.id == operator.person_id)
                .values(email="suyash@authorityclosers.com")
            )
        admin_setup = replace(
            setup, actor=replace(operator.actor, permissions=frozenset({"admin_surface"}))
        )
        entered, finish = asyncio.Event(), asyncio.Event()
        original = setup.broker.execute

        async def bounded_effect(reservation, payload):
            entered.set()
            await finish.wait()
            return await original(reservation, payload)

        setup.broker.execute = bounded_effect
        running = None
        try:
            await _start(setup, await _issue(setup, key="before-pause"), key="already-started")
            running = asyncio.create_task(setup.worker.run_once())
            await asyncio.wait_for(entered.wait(), 10)
            # A different verified admin is independent of the recording owner's
            # canonical lock. Same-owner commands may wait for bounded inference.
            result = await asyncio.wait_for(pause(admin_setup), 5)
            assert result["paused"] and not running.done()
            finish.set()
            assert await running
            assert setup.broker.calls == 1
            assert await setup.worker.claim() is None
        finally:
            finish.set()
            if running is not None:
                await running
            await setup.engine.dispose()

    run(exercise())
