"""Disposable-loopback PostgreSQL migration, authorization and concurrency evidence.

Run explicitly with AC_CONVERSATION_POSTGRES_TEST_URL (or AC_TEST_DATABASE_URL).
Missing/remote database configuration FAILS this proof harness; it never reports a
skipped database test as passed. No server, provider, keys or paid route is activated.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    DELETE_JOB,
    LOCAL_JOB,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.contracts import RecordingIntent, RunIntent
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    BudgetCapApproval,
    ExecutionPermission,
    MinuteAccount,
    MinuteGrant,
    Quote,
    grant_minutes,
)
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationCommand,
    ConversationMinuteAccount,
    ConversationPermission,
    ConversationQuote,
    ConversationRecording,
    ConversationRun,
)
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.sales_xray_profile_models import SalesXrayProfile
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Tenant

ROOT = Path(__file__).parents[2]


def _migration_head() -> str:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "db/migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.fail(
            "NOT EXECUTED: an explicit disposable loopback PostgreSQL URL is required",
            pytrace=False,
        )
    try:
        url = make_url(raw)
    except Exception:
        pytest.fail(
            "invalid disposable PostgreSQL URL; value intentionally not displayed", pytrace=False
        )
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Sales Xray database proof refuses non-loopback PostgreSQL", pytrace=False)
    if any(key.lower() in {"host", "hostaddr", "service", "servicefile"} for key in url.query):
        pytest.fail(
            "alternate PostgreSQL host/service routing is forbidden in this harness", pytrace=False
        )
    url = url.set(drivername="postgresql+psycopg")
    schema = f"conversation_proof_{uuid4().hex}"
    admin = create_engine(url)
    scoped: Engine | None = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        options = f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=30000"
        scoped_url = url.set(query={**url.query, "options": options})
        scoped = create_engine(scoped_url)
        environment = os.environ.copy()
        environment.update(
            # env.py feeds this URL to Alembic's ConfigParser. Percent-encoded query
            # options would trigger interpolation; keep schema scoping in PGOPTIONS.
            AC_DATABASE_URL=url.render_as_string(hide_password=False),
            AC_DATABASE_MIGRATOR_URL=url.render_as_string(hide_password=False),
            AC_ENVIRONMENT="test",
            PGOPTIONS=options,
            PYTHONPATH=str(ROOT / "packages/python"),
        )

        def migrate(target: str) -> None:
            try:
                result = subprocess.run(  # noqa: S603 - fixed Alembic command, disposable local schema
                    [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
                    cwd=ROOT,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                pytest.fail(
                    f"Sales Xray migration process failed: {type(error).__name__}", pytrace=False
                )
            if result.returncode:
                # Never echo URL/environment or unbounded driver tracebacks containing credentials.
                exception_types = sorted(
                    set(
                        re.findall(
                            r"(?m)^((?:[A-Za-z_]\w*\.)*[A-Za-z_]\w*(?:Error|Exception))(?=:)",
                            result.stderr,
                        )
                    )
                    | {
                        f"psycopg.errors.{name}"
                        for name in re.findall(
                            r"\bpsycopg\.errors\.([A-Za-z_]\w*)\b",
                            result.stderr,
                        )
                    }
                )
                diagnostic = ", ".join(exception_types) or "exception type unavailable"
                pytest.fail(
                    f"Migration to {target} failed (exit {result.returncode}; {diagnostic})",
                    pytrace=False,
                )

        migrate("20260910_0029")
        preserved_tenant = uuid4()
        with Session(scoped) as database, database.begin():
            database.add(
                Tenant(
                    id=preserved_tenant,
                    slug=preserved_tenant.hex,
                    name="Disposable pre-Sales-Xray tenant",
                )
            )
        migrate("head")
        with Session(scoped) as database:
            existing = database.get(Tenant, preserved_tenant)
            assert existing is not None and existing.name == "Disposable pre-Sales-Xray tenant"
        yield scoped
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


@dataclass(frozen=True)
class ActorFixture:
    now: datetime
    tenant_id: UUID
    person_id: UUID
    session_id: UUID
    permission_id: UUID
    source_sha256: str

    @property
    def actor(self) -> ActorContext:
        return ActorContext(self.person_id, self.session_id, self.tenant_id)

    @property
    def recording_intent(self) -> RecordingIntent:
        return RecordingIntent(
            source_sha256=self.source_sha256,
            source_bytes=1024,
            content_type="audio/wav",
            permission_reference=self.permission_id,
            purpose="internal_analysis",
        )


async def seed(
    engine: AsyncEngine, *, tenant_id: UUID | None = None, role: str = "learner"
) -> ActorFixture:
    state = ActorFixture(
        datetime.now(UTC), tenant_id or uuid4(), uuid4(), uuid4(), uuid4(), uuid4().hex * 2
    )
    async with AsyncSession(engine) as database, database.begin():
        if tenant_id is None:
            database.add(
                Tenant(
                    id=state.tenant_id,
                    slug=state.tenant_id.hex,
                    name="Disposable Sales Xray tenant",
                )
            )
        database.add(
            Person(
                id=state.person_id,
                email=f"worker-{state.person_id.hex}@example.test",
                display_name="Synthetic Worker Owner",
                email_verified_at=state.now,
            )
        )
        await database.flush()
        database.add(
            SalesXrayProfile(
                person_id=state.person_id,
                phone_number_e164=f"+1555{state.person_id.int % 10_000_000_000:010d}",
            )
        )
        await database.flush()
        database.add(Membership(tenant_id=state.tenant_id, person_id=state.person_id, role=role))
        await database.flush()
        database.add(
            IdentitySession(
                id=state.session_id,
                person_id=state.person_id,
                selected_tenant_id=state.tenant_id,
                token_hash=state.session_id.bytes * 2,
                expires_at=state.now + timedelta(days=1),
            )
        )
        database.add(
            ConversationPermission(
                id=state.permission_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                source_sha256=state.source_sha256,
                provider="local",
                permission_reference="synthetic-fixture:local-analysis",
                retention_reference="synthetic-fixture:delete-after-test",
                created_at=state.now,
                expires_at=state.now + timedelta(hours=2),
                retention_until=state.now + timedelta(hours=3),
            )
        )
    return state


def application(database: AsyncSession, state: ActorFixture) -> ConversationApplication:
    return ConversationApplication(database, clock=lambda: state.now)


def run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        return runner.run(coroutine)


async def wait_blocked(engine: AsyncEngine, pid: int, task: asyncio.Task[Any]) -> None:
    async with AsyncSession(engine) as observer:

        async def inspect_block() -> None:
            while not await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
            ):
                assert not task.done(), (
                    "concurrent command bypassed the expected PostgreSQL row lock"
                )
                await asyncio.sleep(0.02)

        await asyncio.wait_for(inspect_block(), timeout=5)


async def cancel_pending(task: asyncio.Task[Any] | None) -> None:
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_populated_migration_head_matches_real_model_registry(postgres_harness):
    with postgres_harness.connect() as connection:
        assert (
            connection.scalar(text("SELECT version_num FROM alembic_version")) == _migration_head()
        )
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


@pytest.mark.parametrize("conflicting", [False, True])
def test_register_race_serializes_replay_and_conflicting_keys(postgres_harness, conflicting):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        writer = None
        try:
            state = await seed(engine)
            pid_ready = asyncio.get_running_loop().create_future()
            second_intent = state.recording_intent
            if conflicting:
                second_intent = RecordingIntent(
                    **{
                        **second_intent.model_dump(),
                        "source_bytes": 2048,
                    }
                )

            async def duplicate():
                async with AsyncSession(engine) as database, database.begin():
                    pid_ready.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    return await application(database, state).register(
                        state.actor,
                        second_intent,
                        key="race-register",
                    )

            async with AsyncSession(engine) as first, first.begin():
                app = application(first, state)
                await app.admit(state.actor)
                writer = asyncio.create_task(duplicate())
                pid = await asyncio.wait_for(pid_ready, 5)
                await wait_blocked(engine, pid, writer)
                committed = await app.register(
                    state.actor, state.recording_intent, key="race-register"
                )
            if conflicting:
                with pytest.raises(ConversationConflict):
                    await asyncio.wait_for(writer, 5)
            else:
                assert await asyncio.wait_for(writer, 5) == committed
            async with AsyncSession(engine) as database, database.begin():
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationRecording)
                        .where(
                            ConversationRecording.tenant_id == state.tenant_id,
                        )
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(
                            ConversationCommand.tenant_id == state.tenant_id,
                        )
                    )
                    == 1
                )
                assert (await verify_audit_chain(database, state.tenant_id)).valid
        finally:
            await cancel_pending(writer)
            await engine.dispose()

    run(exercise())


def test_recording_owner_tenant_and_current_permission_are_required(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = await seed(engine)
            admin = await seed(engine, tenant_id=owner.tenant_id, role="admin")
            foreign = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                record = await application(database, owner).register(
                    owner.actor,
                    owner.recording_intent,
                    key="owner-record",
                )
            recording_id = UUID(record["id"])
            for actor in (
                admin.actor,
                foreign.actor,
                replace(owner.actor, tenant_id=foreign.tenant_id),
            ):
                for method_name in ("get", "checkpoints", "request_deletion"):
                    async with AsyncSession(engine) as database, database.begin():
                        method = getattr(application(database, owner), method_name)
                        args = (
                            {"key": "forbidden-delete"} if method_name == "request_deletion" else {}
                        )
                        with pytest.raises((ConversationDenied, ConversationNotFound)):
                            await method(actor, recording_id, **args)
            async with AsyncSession(engine) as database, database.begin():
                await database.execute(
                    update(ConversationPermission)
                    .where(
                        ConversationPermission.id == owner.permission_id,
                    )
                    .values(revoked_at=owner.now)
                )
            async with AsyncSession(engine) as database, database.begin():
                with pytest.raises(ConversationDenied):
                    await application(database, owner).get(owner.actor, recording_id)
        finally:
            await engine.dispose()

    run(exercise())


def test_deletion_fences_lookup_and_enqueues_exactly_one_job(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                record = await application(database, state).register(
                    state.actor,
                    state.recording_intent,
                    key="record",
                )
            recording_id = UUID(record["id"])
            async with AsyncSession(engine) as database, database.begin():
                app = application(database, state)
                first = await app.request_deletion(state.actor, recording_id, key="delete")
                assert first["state"] == "deleting"
                with pytest.raises(ConversationNotFound):
                    await app.checkpoints(state.actor, recording_id)
            async with AsyncSession(engine) as database, database.begin():
                app = application(database, state)
                assert await app.request_deletion(state.actor, recording_id, key="delete") == first
                with pytest.raises(ConversationNotFound):
                    await app.get(state.actor, recording_id)
                jobs = (
                    await database.scalars(
                        select(Job).where(
                            Job.tenant_id == state.tenant_id,
                            Job.kind == DELETE_JOB,
                        )
                    )
                ).all()
                assert len(jobs) == 1 and jobs[0].external_side_effect is False
                assert jobs[0].payload == {"recording_id": str(recording_id), "generation": 2}
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(
                            ConversationCommand.tenant_id == state.tenant_id,
                            ConversationCommand.action == "delete",
                        )
                    )
                    == 1
                )
                assert (await verify_audit_chain(database, state.tenant_id)).valid
        finally:
            await engine.dispose()

    run(exercise())


async def seed_budget(engine: AsyncEngine) -> UUID:
    identifier = uuid4()
    snapshot = BudgetAccount(
        str(identifier),
        150_000,
        BudgetCapApproval(
            str(identifier),
            "synthetic-initial-cap",
            "owner-fixture",
            150_000,
            "0" * 64,
            "local integration test budget; no money spent",
        ),
    )
    async with AsyncSession(engine) as database, database.begin():
        database.add(
            ConversationBudgetAccount(scope_id=identifier, snapshot=snapshot.as_dict(), revision=1)
        )
    return identifier


async def seed_run_intent(
    engine: AsyncEngine,
    state: ActorFixture,
    scope_id: UUID,
    *,
    allowance_seconds: int = 180,
    add_allowance: bool = True,
) -> RunIntent:
    async with AsyncSession(engine) as database, database.begin():
        result = await application(database, state).register(
            state.actor,
            state.recording_intent,
            key=f"fixture-register-{uuid4().hex}",
        )
        recording_id, quote_id = UUID(result["id"]), uuid4()
        # Synthetic setup only: storage transport is covered by its own adapter tests.
        recording = await database.get(ConversationRecording, recording_id)
        assert recording is not None
        recording.state = "ready"
        if add_allowance:
            minutes = grant_minutes(
                MinuteAccount(str(state.tenant_id), str(state.person_id)),
                MinuteGrant(
                    str(state.tenant_id),
                    str(state.person_id),
                    uuid4().hex,
                    allowance_seconds,
                    "synthetic-allowance-approval",
                    "authorized-fixture-admin",
                    "integration test",
                ),
            )
            database.add(
                ConversationMinuteAccount(
                    tenant_id=state.tenant_id,
                    person_id=state.person_id,
                    snapshot=minutes.as_dict(),
                    revision=1,
                )
            )
        quoted = Quote(
            quote_id=str(quote_id),
            source=SourceBinding(str(state.tenant_id), str(recording_id), state.source_sha256, "1"),
            account_id=str(state.person_id),
            budget_scope_id=str(scope_id),
            provider_id="local",
            provider_model="audioatlas",
            recipe_revision=AUDIOATLAS_RECIPE,
            operation="inspect_audioatlas",
            input_sha256=state.source_sha256,
            privacy_revision="synthetic-local-privacy",
            permission_ref=str(state.permission_id),
            provider_terms_ref="native-source-license",
            retention_ref="delete-test-schema",
            professional_gate_ref="synthetic-fixture-only",
            pricing_ref="local-zero-price",
            entitlement_seconds=120,
            max_cost_paise=0,
            created_at_epoch=int(state.now.timestamp()) - 1,
            expires_at_epoch=int(state.now.timestamp()) + 3600,
        )
        approval = ExecutionPermission(
            "synthetic-exact-execution-approval",
            quoted.fingerprint,
            "authorized-fixture-owner",
            int(state.now.timestamp()) + 3600,
        )
        database.add(
            ConversationQuote(
                id=quote_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=recording_id,
                budget_scope_id=scope_id,
                quote=quoted.as_dict(),
                execution_permission=approval.as_dict(),
            )
        )
        await database.flush()
        return RunIntent(
            recording_id=recording_id,
            source_revision="1",
            quote_id=quote_id,
            recipe_revision=quoted.recipe_revision,
        )


def test_concurrent_run_commands_cannot_spend_one_allowance_twice(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state, scope_id = await seed(engine), await seed_budget(engine)
            first = await seed_run_intent(engine, state, scope_id)
            second = await seed_run_intent(engine, state, scope_id, add_allowance=False)
            start = asyncio.Event()

            async def request(intent):
                await start.wait()
                async with AsyncSession(engine) as database, database.begin():
                    return await application(database, state).request_run(
                        state.actor, intent, key=uuid4().hex
                    )

            tasks = [asyncio.create_task(request(intent)) for intent in (first, second)]
            start.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 15)
            assert sum(isinstance(result, dict) for result in results) == 1
            assert sum(isinstance(result, ConversationConflict) for result in results) == 1
            async with AsyncSession(engine) as database:
                row = await database.get(
                    ConversationMinuteAccount, (state.tenant_id, state.person_id)
                )
                budget = await database.get(ConversationBudgetAccount, scope_id)
                assert row is not None and budget is not None
                assert MinuteAccount.from_dict(row.snapshot).available_seconds == 60
                assert len(BudgetAccount.from_dict(budget.snapshot).reservations) == 1
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationRun)
                        .where(
                            ConversationRun.tenant_id == state.tenant_id,
                        )
                    )
                    == 1
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(
                            Job.tenant_id == state.tenant_id,
                            Job.kind == LOCAL_JOB,
                        )
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_different_accounts_serialize_the_shared_budget_snapshot(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        second_task = None
        try:
            first_state, second_state = await seed(engine), await seed(engine)
            scope_id = await seed_budget(engine)
            first_intent = await seed_run_intent(engine, first_state, scope_id)
            second_intent = await seed_run_intent(engine, second_state, scope_id)
            pid_ready = asyncio.get_running_loop().create_future()

            async def second_request():
                async with AsyncSession(engine) as database, database.begin():
                    pid_ready.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    return await application(database, second_state).request_run(
                        second_state.actor,
                        second_intent,
                        key="second-run",
                    )

            async with AsyncSession(engine) as first_db, first_db.begin():
                await first_db.scalar(
                    select(ConversationBudgetAccount)
                    .where(
                        ConversationBudgetAccount.scope_id == scope_id,
                    )
                    .with_for_update()
                )
                second_task = asyncio.create_task(second_request())
                pid = await asyncio.wait_for(pid_ready, 5)
                await wait_blocked(engine, pid, second_task)
                first_result = await application(first_db, first_state).request_run(
                    first_state.actor,
                    first_intent,
                    key="first-run",
                )
            second_result = await asyncio.wait_for(second_task, 5)
            assert first_result["id"] != second_result["id"]
            async with AsyncSession(engine) as database, database.begin():
                row = await database.get(ConversationBudgetAccount, scope_id)
                assert row is not None
                shared = BudgetAccount.from_dict(row.snapshot)
                assert len(shared.reservations) == 2 and row.revision == 3
                assert shared.available_paise == 150_000  # Explicit zero-price local route only.
                for state in (first_state, second_state):
                    minute = await database.get(
                        ConversationMinuteAccount, (state.tenant_id, state.person_id)
                    )
                    assert (
                        minute is not None
                        and MinuteAccount.from_dict(minute.snapshot).available_seconds == 60
                    )
                    assert (await verify_audit_chain(database, state.tenant_id)).valid
        finally:
            await cancel_pending(second_task)
            await engine.dispose()

    run(exercise())


def test_run_rollback_restores_both_snapshots_and_removes_job_and_command(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state, scope_id = await seed(engine), await seed_budget(engine)
            intent = await seed_run_intent(engine, state, scope_id)

            class RollbackProbe(Exception):
                pass

            with pytest.raises(RollbackProbe):
                async with AsyncSession(engine) as database, database.begin():
                    await application(database, state).request_run(
                        state.actor, intent, key="rolled-back-run"
                    )
                    raise RollbackProbe
            async with AsyncSession(engine) as database:
                minute = await database.get(
                    ConversationMinuteAccount, (state.tenant_id, state.person_id)
                )
                budget = await database.get(ConversationBudgetAccount, scope_id)
                assert minute is not None and budget is not None
                assert minute.revision == budget.revision == 1
                assert MinuteAccount.from_dict(minute.snapshot).available_seconds == 180
                assert BudgetAccount.from_dict(budget.snapshot).reservations == ()
                for model in (ConversationRun, Job):
                    assert (
                        await database.scalar(
                            select(func.count())
                            .select_from(model)
                            .where(
                                model.tenant_id == state.tenant_id,
                            )
                        )
                        == 0
                    )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(
                            ConversationCommand.tenant_id == state.tenant_id,
                            ConversationCommand.action == "run",
                        )
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_command_facts_are_database_append_only(postgres_harness, operation):
    async def prepare():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            async with AsyncSession(engine) as database, database.begin():
                await application(database, state).register(
                    state.actor, state.recording_intent, key="history"
                )
            return state
        finally:
            await engine.dispose()

    state = run(prepare())
    statement = (
        update(ConversationCommand)
        .where(ConversationCommand.tenant_id == state.tenant_id)
        .values(
            action="mutated-history",
        )
        if operation == "update"
        else delete(ConversationCommand).where(
            ConversationCommand.tenant_id == state.tenant_id,
        )
    )
    with (
        pytest.raises(DBAPIError, match="conversation commands are append-only"),
        postgres_harness.begin() as connection,
    ):
        connection.execute(statement)
