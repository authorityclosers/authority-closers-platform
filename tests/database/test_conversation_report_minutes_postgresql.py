"""Fictional ledger-only proof: failed reports release; one delivery captures.

Draft content here is a minimal synthetic ledger fixture, never report quality
or provider evidence. Real C5 validation remains covered by the worker suites.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.acquisition_usage import acquisition_seconds
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.intake import ConversationIntake
from ac_platform.conversation_intelligence.models import (
    ConversationProcessingPlan,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from ac_platform.db.models import model_metadata
from ac_platform.outbox.repository import JobRepository
from tests.database.test_conversation_guest_ownership_postgresql import (
    _guest,
    _processing_actor,
    _provision,
    policy,
)
from tests.database.test_conversation_postgresql import run, seed, seed_budget
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def setup_case(engine: Any) -> Any:
    from types import SimpleNamespace

    state = await seed(engine)
    scope_id = await seed_budget(engine)
    await _provision(engine, state)
    guest, measured, intent, usage_id = await _guest(
        engine, state, duration_seconds=120, marker=uuid4().hex
    )
    actor = await _processing_actor(engine, state, measured.submission_id, guest.token)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db, db.begin():
        intake = ConversationIntake(
            ConversationApplication(db, clock=lambda: state.now), policy(scope_id, state.tenant_id)
        )
        quote = await intake.prepare(actor, intent, key="ledger-intake")
        recording_id = UUID(quote["recording_id"])
        plan = ConversationProcessingPlan(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            processing_lease_id=actor.processing_lease_id,
            recording_id=recording_id,
            generation=1,
            manifest={},
            plan_sha256="a" * 64,
            state="held",
            progress={"failure_code": "stage_uncertain"},
            created_at=state.now,
            expires_at=state.now + timedelta(hours=1),
            next_check_at=state.now,
        )
        db.add(plan)
        await db.flush()
        # Fixture run has no external send or receipt. Only source FK/ledger
        # serialization is under test; these values do not certify a report.
        fixture_job = await JobRepository(db).enqueue(
            kind="conversation.ledger_fixture.v1",
            dedupe_key=uuid4().hex,
            payload={"schema": 1},
            tenant_id=actor.tenant_id,
        )
        run_row = ConversationRun(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            recording_id=recording_id,
            request_key=uuid4().hex,
            intent_sha256="b" * 64,
            job_id=fixture_job.id,
            recipe_revision="ledger-fixture-only",
            generation=1,
            state="completed",
            created_at=state.now,
            completed_at=state.now,
        )
        db.add(run_row)
        await db.flush()
        draft = ConversationReportDraft(
            id=uuid4(),
            tenant_id=actor.tenant_id,
            person_id=actor.person_id,
            recording_id=recording_id,
            run_id=run_row.id,
            source_revision=1,
            source_sha256=intent.source_sha256,
            report_sha256="c" * 64,
            transcript_sha256="d" * 64,
            profile_sha256="e" * 64,
            evidence_receipt_sha256="f" * 64,
            payload={},
            transcript={},
            evidence_receipt={"fixture": "ledger-only"},
            created_at=state.now,
        )
        db.add(draft)
    return SimpleNamespace(
        state=state,
        actor=actor,
        usage_id=usage_id,
        plan=plan,
        draft=draft,
        sessions=sessions,
        guest=guest,
    )


def test_migration_matches_registry(postgres_harness: Any) -> None:
    with postgres_harness.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_failed_report_releases_and_retry_delivers_once(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            async with case.sessions() as db, db.begin():
                minutes = ReportMinutes(db)
                assert (
                    await acquisition_seconds(
                        db, tenant_id=case.actor.tenant_id, visitor_id=case.guest.visitor_id
                    )
                    == 120
                )
                assert await minutes.release_plan(case.plan)
                assert not await minutes.release_plan(case.plan)
                assert (
                    await acquisition_seconds(
                        db, tenant_id=case.actor.tenant_id, visitor_id=case.guest.visitor_id
                    )
                    == 0
                )
                with pytest.raises(ConversationConflict):
                    async with db.begin_nested():
                        await minutes.deliver(case.usage_id, case.draft, plan_id=case.plan.id)
            # New process / explicit retry: reserve once, never infer no provider cost.
            async with case.sessions() as db, db.begin():
                minutes = ReportMinutes(db)
                await minutes.reserve_retry(
                    case.usage_id, case.actor.tenant_id, key="retry-1", available_seconds=120
                )
                await minutes.reserve_retry(
                    case.usage_id, case.actor.tenant_id, key="retry-1", available_seconds=120
                )
                await minutes.deliver(case.usage_id, case.draft, plan_id=case.plan.id)
                await minutes.deliver(case.usage_id, case.draft, plan_id=case.plan.id)
                assert not await minutes.release_plan(case.plan)
                assert (
                    await acquisition_seconds(
                        db, tenant_id=case.actor.tenant_id, visitor_id=case.guest.visitor_id
                    )
                    == 120
                )
            async with case.sessions() as db:
                events = list(
                    await db.scalars(
                        select(ConversationReportMinuteEvent)
                        .where(ConversationReportMinuteEvent.usage_id == case.usage_id)
                        .order_by(ConversationReportMinuteEvent.revision)
                    )
                )
                assert [(e.kind, e.seconds) for e in events] == [
                    ("released", 0),
                    ("reserved", 120),
                    ("delivered", 120),
                ]
                usage = await db.get(ConversationAcquisitionUsage, case.usage_id)
                assert usage is not None and usage.reserved_seconds == 120
            async with case.sessions() as db, db.begin():
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(
                            update(ConversationReportMinuteEvent)
                            .where(ConversationReportMinuteEvent.usage_id == case.usage_id)
                            .values(seconds=0)
                        )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("winner", ["release", "delivery"])
def test_release_delivery_race_has_one_customer_outcome(postgres_harness: Any, winner: str) -> None:
    import asyncio

    from sqlalchemy import text

    from tests.database.test_conversation_postgresql import cancel_pending, wait_blocked

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        contender = None
        try:
            case = await setup_case(engine)
            ready = asyncio.get_running_loop().create_future()

            async def compete() -> bool:
                async with case.sessions() as second, second.begin():
                    ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                    minutes = ReportMinutes(second)
                    if winner == "delivery":
                        return await minutes.release_plan(case.plan)
                    try:
                        await minutes.deliver(case.usage_id, case.draft, plan_id=case.plan.id)
                    except ConversationConflict:
                        return False
                    return True

            async with case.sessions() as first, first.begin():
                minutes = ReportMinutes(first)
                await minutes._lock(case.usage_id, case.actor.tenant_id)
                contender = asyncio.create_task(compete())
                pid = await ready
                await wait_blocked(engine, pid, contender)
                if winner == "release":
                    assert await minutes.release_plan(case.plan)
                else:
                    await minutes.deliver(case.usage_id, case.draft, plan_id=case.plan.id)
            assert await asyncio.wait_for(contender, 5) is False
            async with case.sessions() as db:
                events = list(
                    await db.scalars(
                        select(ConversationReportMinuteEvent).where(
                            ConversationReportMinuteEvent.usage_id == case.usage_id
                        )
                    )
                )
                assert len(events) == 1
                assert events[0].kind == ("released" if winner == "release" else "delivered")
                assert await acquisition_seconds(
                    db, tenant_id=case.actor.tenant_id, visitor_id=case.guest.visitor_id
                ) == (0 if winner == "release" else 120)
        finally:
            await cancel_pending(contender)
            await engine.dispose()

    run(exercise())


def test_release_rollback_and_insufficient_retry_do_not_change_capacity(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            with pytest.raises(RuntimeError):
                async with case.sessions() as db, db.begin():
                    assert await ReportMinutes(db).release_plan(case.plan)
                    raise RuntimeError("process loss before commit")
            async with case.sessions() as db, db.begin():
                minutes = ReportMinutes(db)
                assert await minutes.latest(case.usage_id) is None
                assert await minutes.release_plan(case.plan)
            async with case.sessions() as db, db.begin():
                minutes = ReportMinutes(db)
                with pytest.raises(ConversationConflict):
                    await minutes.reserve_retry(
                        case.usage_id, case.actor.tenant_id, key="too-large", available_seconds=119
                    )
                assert (await minutes.latest(case.usage_id)).kind == "released"
                assert (
                    await acquisition_seconds(
                        db, tenant_id=case.actor.tenant_id, visitor_id=case.guest.visitor_id
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())
