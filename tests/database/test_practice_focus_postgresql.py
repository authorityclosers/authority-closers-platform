"""Fresh-schema PostgreSQL Focus migration, history and actual blocking races."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.practice.focus import FocusApplication, FocusConflict
from ac_platform.practice.focus_models import PracticeFocusEvent, PracticeFocusRun
from tests.database import test_practice_engine_postgresql as engine_tests
from tests.unit.test_practice_focus import advance, end, issue, start


@pytest.fixture(scope="module")
def postgres_harness():
    yield from engine_tests.postgres_harness.__wrapped__()


@pytest.fixture(scope="module")
def ended_run(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await engine_tests.seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                attempt, result = await start(state)
                attempt = await advance(state, attempt)
                ended = await end(state, attempt, result["run"])
                state.run_id = UUID(ended["run"]["id"])
                assert ended["summary"]["charges"] == 2
                assert (await verify_audit_chain(db, state.tenant)).valid
            return state
        finally:
            await engine.dispose()

    return engine_tests.run(exercise())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_focus_history_and_terminal_runs_cannot_be_rewritten(
    postgres_harness, ended_run, operation
):
    for model in (PracticeFocusEvent, PracticeFocusRun):
        table = model.__table__
        statement = (
            update(table).where(table.c.tenant_id == ended_run.tenant).values(person_id=uuid4())
            if operation == "update"
            else delete(table).where(table.c.tenant_id == ended_run.tenant)
        )
        diagnostic = (
            "practice history is immutable"
            if model is PracticeFocusEvent
            else (
                "Focus run lifecycle cannot be rewritten"
                if operation == "update"
                else "Focus runs cannot be deleted"
            )
        )
        with pytest.raises(DBAPIError, match=diagnostic), postgres_harness.begin() as connection:
            connection.execute(statement)


@pytest.mark.parametrize(
    "mutation,diagnostic",
    [
        ("gap", "Focus history must be contiguous and balanced"),
        ("balance", "Focus history must be contiguous and balanced"),
        ("old_day", "Focus day can only reset forward"),
        ("bounds", "ck_practice_focus_events_charge_bounds"),
        ("null_balance", 'null value in column "charges_after"'),
    ],
)
def test_focus_raw_chain_and_charge_constraints_fail_closed(
    postgres_harness, ended_run, mutation, diagnostic
):
    with postgres_harness.connect() as connection:
        previous = dict(
            connection.execute(
                select(PracticeFocusEvent.__table__)
                .where(PracticeFocusEvent.tenant_id == ended_run.tenant)
                .order_by(PracticeFocusEvent.revision.desc())
                .limit(1)
            )
            .mappings()
            .one()
        )
    values = {
        **previous,
        "id": uuid4(),
        "run_id": None,
        "kind": "day_reset",
        "revision": previous["revision"] + 1,
        "charges_before": previous["charges_after"],
        "charges_after": 3,
        "local_day": previous["local_day"] + timedelta(days=1),
        "reset_day": previous["reset_day"] + timedelta(days=1),
    }
    if mutation == "gap":
        values["revision"] += 1
    elif mutation == "balance":
        values["charges_before"] = 0
    elif mutation == "old_day":
        values["local_day"] = previous["local_day"]
        values["reset_day"] = previous["reset_day"]
    elif mutation == "bounds":
        values["charges_after"] = 4
    else:
        values["charges_after"] = None
    # These malformed writes are restricted to this disposable random test schema.
    # Assert the intended guard, not merely an error: the copied audit ID is
    # unique too and must not make a missing chain/bounds guard falsely pass.
    with pytest.raises(DBAPIError, match=diagnostic), postgres_harness.begin() as connection:
        connection.execute(insert(PracticeFocusEvent).values(**values))


def test_focus_missing_start_event_cannot_commit_a_run(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await engine_tests.seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                attempt = await issue(state)
            with pytest.raises(DBAPIError, match="immutable start event"):
                async with AsyncSession(engine) as db, db.begin():
                    db.add(
                        PracticeFocusRun(
                            id=uuid4(),
                            tenant_id=state.tenant,
                            person_id=state.person,
                            attempt_id=UUID(attempt["id"]),
                            state="active",
                            started_at=state.now,
                            exit_cost=0,
                            completion_restore=0,
                        )
                    )
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(PracticeFocusRun)
                        .where(PracticeFocusRun.tenant_id == state.tenant)
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    engine_tests.run(exercise())


async def observe_block(engine, writer, pid):
    async with AsyncSession(engine) as observer:

        async def blocked():
            while not await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
            ):
                assert not writer.done(), "competing Focus command bypassed the person fence"
                await asyncio.sleep(0.02)

        await asyncio.wait_for(blocked(), 5)


@pytest.mark.parametrize("command", ["start", "end"])
def test_actual_concurrent_start_and_duplicate_end_use_one_person_fence(postgres_harness, command):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        writer = None
        try:
            state = await engine_tests.seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                if command == "start":
                    first_attempt, second_attempt = await issue(state), await issue(state)
                else:
                    first_attempt, started = await start(state)
                    first_attempt = await advance(state, first_attempt)
                    run_id = UUID(started["run"]["id"])
            ready = asyncio.get_running_loop().create_future()

            async def duplicate():
                async with AsyncSession(engine) as db, db.begin():
                    ready.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    focus = FocusApplication(engine_tests.application(db, state))
                    if command == "start":
                        with pytest.raises(FocusConflict) as conflict:
                            await focus.start(
                                state.actor,
                                UUID(second_attempt["id"]),
                                key="second-start",
                                expected_revision=0,
                                expected_attempt_revision=0,
                            )
                        assert conflict.value.reason == "active_run_conflict"
                        return None
                    return await focus.end(
                        state.actor,
                        run_id,
                        key="end-race",
                        expected_revision=1,
                        expected_attempt_revision=first_attempt["revision"],
                    )

            async with AsyncSession(engine) as db, db.begin():
                app = engine_tests.application(db, state)
                await app._admit(state.actor)
                writer = asyncio.create_task(duplicate())
                await observe_block(engine, writer, await asyncio.wait_for(ready, 5))
                focus = FocusApplication(app)
                if command == "start":
                    result = await focus.start(
                        state.actor,
                        UUID(first_attempt["id"]),
                        key="first-start",
                        expected_revision=0,
                        expected_attempt_revision=0,
                    )
                else:
                    result = await focus.end(
                        state.actor,
                        run_id,
                        key="end-race",
                        expected_revision=1,
                        expected_attempt_revision=first_attempt["revision"],
                    )
            duplicate_result = await asyncio.wait_for(writer, 5)
            if command == "end":
                assert duplicate_result == result and result["summary"]["charges"] == 2
            async with AsyncSession(engine) as db, db.begin():
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(PracticeFocusRun)
                        .where(PracticeFocusRun.tenant_id == state.tenant)
                    )
                    == 1
                )
                assert await db.scalar(
                    select(func.count())
                    .select_from(PracticeFocusEvent)
                    .where(PracticeFocusEvent.tenant_id == state.tenant)
                ) == (1 if command == "start" else 2)
                assert (await verify_audit_chain(db, state.tenant)).valid
        finally:
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            await engine.dispose()

    engine_tests.run(exercise())


@pytest.mark.parametrize("winner", ["completion", "end"])
def test_completion_vs_end_cannot_both_refill_and_charge(postgres_harness, winner):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        writer = None
        try:
            state = await engine_tests.seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                attempt, started = await start(state)
                attempt = await advance(state, attempt, count=len(attempt["set"]["items"]) - 1)
                attempt = await advance(state, attempt, acknowledge=False)
                response_id = UUID(attempt["item_states"][-1]["response_id"])
            ready = asyncio.get_running_loop().create_future()

            async def action(db, kind):
                app = engine_tests.application(db, state)
                if kind == "completion":
                    return await app.acknowledge(
                        state.actor,
                        UUID(attempt["id"]),
                        response_id,
                        key="finish-race",
                        expected_revision=attempt["revision"],
                    )
                return await FocusApplication(app).end(
                    state.actor,
                    UUID(started["run"]["id"]),
                    key="exit-race",
                    expected_revision=1,
                    expected_attempt_revision=attempt["revision"],
                )

            async def competing():
                async with AsyncSession(engine) as db, db.begin():
                    ready.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    if winner == "completion":
                        with pytest.raises(FocusConflict) as conflict:
                            await action(db, "end")
                        assert conflict.value.reason == "revision_conflict"
                    else:
                        assert (await action(db, "completion"))["state"] == "completed"

            async with AsyncSession(engine) as db, db.begin():
                await engine_tests.application(db, state)._admit(state.actor)
                writer = asyncio.create_task(competing())
                await observe_block(engine, writer, await asyncio.wait_for(ready, 5))
                await action(db, winner)
            await asyncio.wait_for(writer, 5)
            async with AsyncSession(engine) as db, db.begin():
                app = engine_tests.application(db, state)
                assert (await FocusApplication(app).summary(state.actor))["charges"] == (
                    3 if winner == "completion" else 2
                )
                progress = await app.progress(state.actor)
                assert progress["credits_balance"] == 10 and progress["xp_total"] == 30
                assert (await verify_audit_chain(db, state.tenant)).valid
        finally:
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            await engine.dispose()

    engine_tests.run(exercise())


def test_postgres_rollover_and_rollback_do_not_change_old_focus_receipts(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await engine_tests.seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                attempt, started = await start(state)
                await end(state, await advance(state, attempt), started["run"])
                historical = list(
                    (
                        await db.execute(
                            select(
                                PracticeFocusEvent.id,
                                PracticeFocusEvent.local_day,
                                PracticeFocusEvent.charges_after,
                            ).where(PracticeFocusEvent.tenant_id == state.tenant)
                        )
                    ).all()
                )
            state.now += timedelta(days=1)
            async with AsyncSession(engine) as db, db.begin():
                state.app = engine_tests.application(db, state)
                before = await FocusApplication(state.app).summary(state.actor)
                assert before["charges"] == 3 and before["revision"] == 2
                audit_count = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.tenant_id == state.tenant)
                )
                savepoint = await db.begin_nested()
                await start(state)
                await savepoint.rollback()
                assert await FocusApplication(state.app).summary(state.actor) == before
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == state.tenant)
                    )
                    == audit_count
                )
                _, result = await start(state)
                assert result["summary"]["revision"] == 4
                after = list(
                    (
                        await db.execute(
                            select(
                                PracticeFocusEvent.id,
                                PracticeFocusEvent.local_day,
                                PracticeFocusEvent.charges_after,
                            ).where(PracticeFocusEvent.id.in_([row.id for row in historical]))
                        )
                    ).all()
                )
                assert set(after) == set(historical)
                assert (await verify_audit_chain(db, state.tenant)).valid
        finally:
            await engine.dispose()

    engine_tests.run(exercise())
