"""Opt-in real lock/commit proof in a new local, random schema for every test."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.audit.models import AuditChainHead, AuditEvent
from ac_platform.audit.service import AuditRepository, verify_audit_chain_sync
from ac_platform.bootstrap import BootstrapApplication, BootstrapError
from ac_platform.db.models import model_metadata
from ac_platform.tenancy.models import Tenant


def _run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(coroutine)
    return asyncio.run(coroutine)


@pytest.fixture
def isolated_schema() -> Iterator[URL]:
    raw = os.getenv("AC_OPERATIONS_BOOTSTRAP_POSTGRES_TEST_URL")
    if not raw:
        if os.getenv("AC_REQUIRE_OPERATIONS_BOOTSTRAP_POSTGRES_TEST") == "1":
            pytest.fail("the explicit operations bootstrap PostgreSQL test URL is required")
        pytest.skip("operations bootstrap PostgreSQL test URL is not configured")
    try:
        base = make_url(raw).set(drivername="postgresql+psycopg")
    except Exception:
        pytest.fail("invalid operations bootstrap PostgreSQL test URL")
    if (
        not raw.startswith("postgresql")
        or base.host not in {"127.0.0.1", "localhost", "::1"}
        or base.port != 55432
        or base.database != "ac_local_sandbox"
        or base.username != "ac_owner"
        or base.query
    ):
        pytest.fail("only the explicit managed loopback owner test target is permitted")
    root = Path(__file__).parents[2]
    schema = f"ops_bootstrap_{uuid4().hex}"
    engine = create_engine(base, pool_pre_ping=True)
    created = False
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        options = f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000"
        scoped = base.set(query={"options": options})
        environment = os.environ.copy()
        environment.update(
            AC_ENVIRONMENT="test",
            AC_DATABASE_URL=base.render_as_string(hide_password=False),
            AC_DATABASE_MIGRATOR_URL=base.render_as_string(hide_password=False),
            PGOPTIONS=options,
            PYTHONPATH=os.pathsep.join(
                value
                for value in (str(root / "packages/python"), environment.get("PYTHONPATH"))
                if value
            ),
        )
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            timeout=180,
            check=False,
        )
        if migration.returncode:
            pytest.fail("isolated operations bootstrap test schema migration failed")
        yield scoped
    finally:
        if created:
            # No runtime/public-schema cleanup and no computed broad identifiers.
            if re.fullmatch(r"ops_bootstrap_[0-9a-f]{32}", schema) is None:
                pytest.fail("unsafe operations bootstrap test schema cleanup refused")
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def _command() -> dict[str, Any]:
    return {
        "command_id": uuid4(),
        "operator_reference": "TEST-ONLY-PG-operator",
        "reason": "TEST-ONLY operations bootstrap concurrency proof",
        "tenant_slug": "test-operations",
        "tenant_name": "Test operations",
    }


@pytest.mark.parametrize("different_intent", [False, True])
def test_real_operations_lock_serializes_replay_or_rejects_second_intent(
    isolated_schema: URL, different_intent: bool
) -> None:
    sync_engine = create_engine(isolated_schema)
    try:
        with Session(sync_engine) as database:
            baseline = {
                table.name: database.scalar(select(func.count()).select_from(table))
                for table in model_metadata().tables.values()
            }
    finally:
        sync_engine.dispose()

    async def scenario() -> None:
        engine = create_async_engine(isolated_schema, pool_size=3, max_overflow=0)
        command = _command()
        following = dict(command)
        if different_intent:
            following.update(command_id=uuid4(), tenant_slug="other-control", tenant_name="Other")
        pending: asyncio.Task[Any] | None = None
        try:
            follower_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

            async def follow() -> Any:
                async with AsyncSession(engine) as database, database.begin():
                    follower_pid.set_result(await database.scalar(text("SELECT pg_backend_pid()")))
                    return await BootstrapApplication(database).bootstrap_operations_tenant(
                        **following
                    )

            async with AsyncSession(engine) as winner, winner.begin():
                first = await BootstrapApplication(winner).bootstrap_operations_tenant(**command)
                pending = asyncio.create_task(follow())
                pid = await asyncio.wait_for(follower_pid, timeout=5)
                async with AsyncSession(engine) as observer:

                    async def observe_block() -> None:
                        while True:
                            blocked = await observer.scalar(
                                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                                {"pid": pid},
                            )
                            if blocked:
                                return
                            assert not pending.done(), "bootstrap bypassed uncommitted intent fence"
                            await asyncio.sleep(0.02)

                    await asyncio.wait_for(observe_block(), timeout=5)
                    assert await observer.scalar(select(func.count()).select_from(Tenant)) == 0
                    assert await observer.scalar(select(func.count()).select_from(AuditEvent)) == 0
            if different_intent:
                with pytest.raises(BootstrapError, match="history exists"):
                    await asyncio.wait_for(pending, timeout=5)
            else:
                replay = await asyncio.wait_for(pending, timeout=5)
                assert first.tenant_created and not first.replayed
                assert not replay.tenant_created and replay.replayed
                assert replay.tenant_id == first.tenant_id
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await engine.dispose()

    _run_async(scenario())
    engine = create_engine(isolated_schema)
    try:
        with Session(engine) as database:
            tenant = database.scalar(select(Tenant))
            assert tenant is not None
            counts = {
                table.name: database.scalar(select(func.count()).select_from(table))
                for table in model_metadata().tables.values()
            }
            expected = dict(baseline)
            for table in ("tenants", "audit_events", "audit_chain_heads"):
                expected[table] += 1
            assert counts == expected
            assert verify_audit_chain_sync(database, tenant.id).valid
    finally:
        engine.dispose()


def test_real_operations_audit_failure_rolls_back_all_command_state(
    isolated_schema: URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    append = AuditRepository.append

    async def fail_after_append(self: AuditRepository, **kwargs: Any) -> AuditEvent:
        await append(self, **kwargs)
        raise RuntimeError("TEST-ONLY failure after canonical audit append")

    monkeypatch.setattr(AuditRepository, "append", fail_after_append)

    async def scenario() -> None:
        engine = create_async_engine(isolated_schema)
        try:
            with pytest.raises(RuntimeError, match="TEST-ONLY failure"):
                async with AsyncSession(engine) as database, database.begin():
                    await BootstrapApplication(database).bootstrap_operations_tenant(**_command())
            async with AsyncSession(engine) as database:
                assert await database.scalar(select(func.count()).select_from(Tenant)) == 0
                assert await database.scalar(select(func.count()).select_from(AuditEvent)) == 0
                assert await database.scalar(select(func.count()).select_from(AuditChainHead)) == 0
        finally:
            await engine.dispose()

    _run_async(scenario())
