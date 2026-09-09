"""Disposable-schema migration, transactional race and immutable earned-journal proof."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, delete, func, insert, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.practice.application import PracticeApplication, PracticeConflict
from ac_platform.practice.models import (
    IMMUTABLE_MODELS,
    PracticeParticipation,
    PracticeRewardClaim,
)
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.test_practice_engine import finish

ROOT = Path(__file__).parents[2]


def _migration_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "db" / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


@pytest.fixture(scope="module")
def postgres_harness():
    raw = os.getenv("AC_PRACTICE_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("disposable practice PostgreSQL URL is not configured")
    url = make_url(raw)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.skip("practice proof refuses a non-loopback PostgreSQL connection")
    url = url.set(drivername="postgresql+psycopg")
    schema = f"practice_engine_{uuid4().hex}"
    admin = create_engine(url)
    scoped = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        query = {**url.query, "options": f"-csearch_path={schema}"}
        scoped = create_engine(url.set(query=query))
        environment = os.environ.copy()
        environment.update(
            AC_DATABASE_URL=url.render_as_string(hide_password=False),
            AC_DATABASE_MIGRATOR_URL=url.render_as_string(hide_password=False),
            AC_ENVIRONMENT="test",
            PGOPTIONS=f"-csearch_path={schema}",
            PYTHONPATH=str(ROOT / "packages/python"),
        )

        def migrate(target):
            result = subprocess.run(  # noqa: S603 - fixed test-schema Alembic command
                [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            # Do not emit potentially credential-bearing process environments or tracebacks.
            if result.returncode != 0:
                diagnostic = "\n".join(
                    line
                    for line in result.stderr.splitlines()
                    if line.startswith(("psycopg.errors.", "LINE "))
                )
                pytest.fail(
                    f"isolated practice migration to {target} failed: {diagnostic}", pytrace=False
                )

        migrate("20260907_0019")
        original = uuid4()
        with Session(scoped) as db, db.begin():
            db.add(Tenant(id=original, slug=original.hex, name="Preexisting 0019 academy"))
        migrate("20260908_0020")
        migrate("20260908_0021")
        migrate("head")
        with Session(scoped) as db:
            assert db.get(Tenant, original).name == "Preexisting 0019 academy"
        yield scoped
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


async def seed(engine):
    state = SimpleNamespace(now=datetime.now(UTC), tenant=uuid4(), person=uuid4(), session=uuid4())
    state.actor = ActorContext(state.person, state.session, state.tenant)
    async with AsyncSession(engine) as db, db.begin():
        db.add(Tenant(id=state.tenant, slug=state.tenant.hex, name="Disposable practice academy"))
        db.add(Person(id=state.person, email_verified_at=state.now))
        await db.flush()
        db.add(Membership(tenant_id=state.tenant, person_id=state.person, role="learner"))
        await db.flush()
        db.add(
            IdentitySession(
                id=state.session,
                person_id=state.person,
                selected_tenant_id=state.tenant,
                token_hash=state.session.bytes * 2,
                expires_at=state.now + timedelta(days=30),
            )
        )
        await db.flush()
        state.app = application(db, state)
        await state.app.save_profile(state.actor, key="zone", timezone="UTC", expected_revision=0)
    return state


def application(db, state):
    return PracticeApplication(
        db,
        academy_tenant_id=state.tenant,
        environment="test",
        preview_enabled=True,
        clock=lambda: state.now,
    )


def run(coroutine):
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


def test_populated_upgrade_registry_and_distinct_constraint_names(postgres_harness):
    with postgres_harness.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == _migration_head()
        )
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
        names = [
            constraint["name"]
            for constraint in inspect(connection).get_unique_constraints("practice_reward_claims")
        ]
        assert len(names) == len(set(names))


@pytest.fixture(scope="module")
def completed(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                result = await finish(state)
                assert result["state"] == "completed"
                assert (await verify_audit_chain(db, state.tenant)).valid
            return state
        finally:
            await engine.dispose()

    return run(exercise())


@pytest.mark.parametrize("model", IMMUTABLE_MODELS)
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_direct_sql_history_is_immutable(postgres_harness, completed, model, operation):
    table = model.__table__
    with postgres_harness.connect() as connection:
        row_id = connection.scalar(select(table.c.id).where(table.c.tenant_id == completed.tenant))
        assert row_id is not None
    statement = (
        update(table).where(table.c.id == row_id).values(created_at=datetime.now(UTC))
        if operation == "update"
        else delete(table).where(table.c.id == row_id)
    )
    with (
        pytest.raises(DBAPIError, match="practice history is immutable"),
        postgres_harness.begin() as connection,
    ):
        connection.execute(statement)


def test_incomplete_balanced_journal_and_null_daily_slot_fail_closed(postgres_harness, completed):
    with postgres_harness.connect() as connection:
        source = dict(
            connection.execute(
                select(PracticeRewardClaim.__table__).where(
                    PracticeRewardClaim.tenant_id == completed.tenant
                )
            )
            .mappings()
            .first()
        )
    for slot, expected in ((None, "approved_award_shape"), (2, "balanced claim")):
        values = {
            **source,
            "id": uuid4(),
            "daily_slot": slot,
            "dedup_key": f"{source['local_day']}:new-family",
        }
        with pytest.raises(DBAPIError, match=expected), postgres_harness.begin() as connection:
            connection.execute(insert(PracticeRewardClaim).values(**values))
            # No entries: deferred validation must fail at COMMIT, not silently mint credits.


def test_two_simultaneous_final_ack_replays_commit_only_one_reward(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        writer = None
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                result, current = await finish(state, until_last_ack=True)
            arguments = dict(key="final-ack", expected_revision=result["revision"])
            attempt_id, response_id = UUID(result["id"]), UUID(current["response_id"])
            pid_ready = asyncio.get_running_loop().create_future()

            async def duplicate():
                async with AsyncSession(engine) as db, db.begin():
                    pid_ready.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    return await application(db, state).acknowledge(
                        state.actor, attempt_id, response_id, **arguments
                    )

            async with AsyncSession(engine) as first, first.begin():
                service = application(first, state)
                await service._admit(state.actor)
                writer = asyncio.create_task(duplicate())
                pid = await asyncio.wait_for(pid_ready, 5)
                async with AsyncSession(engine) as observer:

                    async def blocked():
                        while not await observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
                        ):
                            assert not writer.done(), "the duplicate bypassed the person fence"
                            await asyncio.sleep(0.02)

                    await asyncio.wait_for(blocked(), 5)
                committed = await service.acknowledge(
                    state.actor, attempt_id, response_id, **arguments
                )
            duplicate_result = await asyncio.wait_for(writer, 5)
            assert committed == duplicate_result
            async with AsyncSession(engine) as db, db.begin():
                result = await application(db, state).progress(state.actor)
                assert result["credits_balance"] == 10 and result["xp_total"] == 30
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(PracticeParticipation)
                        .where(PracticeParticipation.tenant_id == state.tenant)
                    )
                    == 1
                )
                assert (await verify_audit_chain(db, state.tenant)).valid
        finally:
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("families,expected_credits", [("distinct", 20), ("same", 10)])
def test_simultaneous_family_completions_enforce_cap_and_atomic_rollback(
    postgres_harness, families, expected_credits
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            pending = []
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                for family in (
                    ("gaps", "match", "sequence")
                    if families == "distinct"
                    else ("gaps", "gaps", "gaps")
                ):
                    pending.append(await finish(state, family, until_last_ack=True))

            async def complete(pair):
                result, current = pair
                async with AsyncSession(engine) as db, db.begin():
                    return await application(db, state).acknowledge(
                        state.actor,
                        UUID(result["id"]),
                        UUID(current["response_id"]),
                        key=uuid4().hex,
                        expected_revision=result["revision"],
                    )

            results = await asyncio.wait_for(
                asyncio.gather(*(complete(pair) for pair in pending)), 15
            )
            assert all(result["state"] == "completed" for result in results)
            async with AsyncSession(engine) as db, db.begin():
                app = application(db, state)
                state.now += timedelta(days=1)
                before = await app.progress(state.actor)
                assert before["credits_balance"] == expected_credits
                assert before["xp_total"] == expected_credits * 3
                audit_count = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.tenant_id == state.tenant)
                )
                savepoint = await db.begin_nested()
                state.app = app
                await finish(state, "build")
                assert (await app.progress(state.actor))["credits_balance"] == expected_credits + 10
                await savepoint.rollback()
                assert await app.progress(state.actor) == before
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(AuditEvent.tenant_id == state.tenant)
                    )
                    == audit_count
                )
                assert (await verify_audit_chain(db, state.tenant)).valid
                with pytest.raises(PracticeConflict):
                    await app.issue(state.actor, set_id="gaps", key="zone")
        finally:
            await engine.dispose()

    run(exercise())


def test_postgresql_timezone_boundary_uses_scheduled_zone_without_rebucketing(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                scheduled = await state.app.save_profile(
                    state.actor, key="new-zone", timezone="Asia/Kolkata", expected_revision=1
                )
                boundary = datetime.fromisoformat(scheduled["pending_effective_at"])
            state.now = boundary - timedelta(seconds=1)
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                old = await finish(state)
                assert (await state.app.profile(state.actor))["timezone"] == "UTC"
            state.now = boundary
            async with AsyncSession(engine) as db, db.begin():
                state.app = application(db, state)
                assert (await state.app.profile(state.actor))["timezone"] == "Asia/Kolkata"
                current = await finish(state)
                assert (
                    current["reward_receipts"][0]["local_day"]
                    != old["reward_receipts"][0]["local_day"]
                )
                assert (
                    current["reward_receipts"][0]["week_start"]
                    != old["reward_receipts"][0]["week_start"]
                )
                assert (await state.app.attempt(state.actor, UUID(old["id"])))[
                    "reward_receipts"
                ] == old["reward_receipts"]
                assert (await verify_audit_chain(db, state.tenant)).valid
        finally:
            await engine.dispose()

    run(exercise())
