"""0088 constraints/history and physical backup/restore on owned test databases."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from tests.database.conversation_harness import migrated_database
from tests.database.postgres_templates import PostgresTemplatePool, migration_fingerprint
from tests.database.test_conversation_customer_terminal_settlement_postgresql import fail, prepared
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "db/migrations/versions/20261012_0088_customer_terminal_settlement.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def migration() -> Any:
    spec = importlib.util.spec_from_file_location("customer_terminal_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0088_zero_charge_append_only_and_guarded_reversal(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def setup() -> Any:
        engine = create_async_engine(postgres_harness.url)
        try:
            return await prepared(engine, tmp_path)
        finally:
            await engine.dispose()

    f = run(setup())
    module = migration()
    assert (module.revision, module.down_revision) == ("20261012_0088", "20261011_0087")
    with postgres_harness.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(
                    text(
                        "INSERT INTO conversation_acquisition_settlements "
                        "(usage_id, charged_seconds, kind, receipt_sha256, created_at) "
                        "VALUES (:usage, 0, 'terminal_failure', :hash, now())"
                    ),
                    {"usage": f.usage_id, "hash": f.receipt.fingerprint},
                )
            module.upgrade()
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO conversation_acquisition_settlements "
                    "(usage_id, charged_seconds, kind, receipt_sha256, created_at) "
                    "VALUES (:usage, 1, 'terminal_failure', :hash, now())"
                ),
                {"usage": f.usage_id, "hash": f.receipt.fingerprint},
            )
    assert run(fail(f)).changed
    with postgres_harness.begin() as connection:
        with (
            Operations.context(MigrationContext.configure(connection)),
            pytest.raises(RuntimeError, match="forward recovery"),
        ):
            module.downgrade()
        before = connection.execute(
            text(
                "SELECT charged_seconds, kind, receipt_sha256 "
                "FROM conversation_acquisition_settlements WHERE usage_id = :usage"
            ),
            {"usage": f.usage_id},
        ).one()
        for command in (
            "UPDATE conversation_acquisition_settlements SET charged_seconds=7 "
            "WHERE usage_id=:usage",
            "DELETE FROM conversation_acquisition_settlements WHERE usage_id=:usage",
            "DELETE FROM conversation_report_minute_events WHERE usage_id=:usage",
        ):
            with pytest.raises(DBAPIError), connection.begin_nested():
                connection.execute(text(command), {"usage": f.usage_id})
        assert (
            before
            == connection.execute(
                text(
                    "SELECT charged_seconds, kind, receipt_sha256 "
                    "FROM conversation_acquisition_settlements WHERE usage_id = :usage"
                ),
                {"usage": f.usage_id},
            ).one()
        )


def persisted_packet(engine: Any, f: Any) -> dict[str, Any]:
    with engine.connect() as connection:
        result = {}
        for name, query, parameters in (
            (
                "settlement",
                "SELECT * FROM conversation_acquisition_settlements WHERE usage_id=:id",
                {"id": f.usage_id},
            ),
            (
                "journal",
                "SELECT * FROM conversation_report_minute_events "
                "WHERE usage_id=:id ORDER BY revision",
                {"id": f.usage_id},
            ),
            (
                "minutes",
                "SELECT snapshot, revision FROM conversation_minute_accounts "
                "WHERE tenant_id=:tenant AND person_id=:person",
                {"tenant": f.actor.tenant_id, "person": f.actor.person_id},
            ),
            (
                "budget",
                "SELECT snapshot, revision FROM conversation_budget_accounts WHERE scope_id=:id",
                {"id": f.scope_id},
            ),
            (
                "audit",
                "SELECT * FROM audit_events WHERE tenant_id=:id ORDER BY sequence_no",
                {"id": f.actor.tenant_id},
            ),
        ):
            result[name] = [
                dict(row) for row in connection.execute(text(query), parameters).mappings()
            ]
        result["constraints"] = inspect(connection).get_check_constraints(
            "conversation_acquisition_settlements"
        )
        result["triggers"] = list(
            connection.execute(
                text(
                    "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgrelid='conversation_acquisition_settlements'::regclass "
                    "AND NOT tgisinternal"
                )
            )
        )
        result["head"] = connection.scalar(text("SELECT version_num FROM alembic_version"))
        return result


def test_physical_snapshot_restores_receipts_pair_audit_and_guards(tmp_path: Path) -> None:
    # A physical PostgreSQL template snapshot and restore; no pg_dump binary is
    # assumed. The pool only creates/deletes its own explicit disposable DBs.
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    assert raw, "An explicit disposable database is required"

    def initialize(url: Any, schema: str) -> None:
        with migrated_database(
            ROOT, url.render_as_string(hide_password=False), schema=schema, drop_schema=False
        ):
            pass

    pool = PostgresTemplatePool(raw, initialize)
    try:
        with pool.clone(migration_fingerprint(ROOT)) as source:

            async def setup() -> Any:
                engine = create_async_engine(source.url)
                try:
                    f = await prepared(engine, tmp_path)
                    await fail(f)
                    return f
                finally:
                    await engine.dispose()

            f = run(setup())
            expected = persisted_packet(source, f)
            source.dispose()
            snapshot_name = f"ac_pytest_clone_{uuid4().hex}"
            pool._create(snapshot_name, source.url.database)
            restored_name = f"ac_pytest_clone_{uuid4().hex}"
            pool._create(restored_name, snapshot_name)
            restored = create_engine(source.url.set(database=restored_name), hide_parameters=True)
            try:
                assert persisted_packet(restored, f) == expected
                with (
                    restored.begin() as connection,
                    pytest.raises(DBAPIError),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        text("DELETE FROM conversation_acquisition_settlements WHERE usage_id=:id"),
                        {"id": f.usage_id},
                    )
                assert persisted_packet(restored, f) == expected
            finally:
                restored.dispose()
    finally:
        pool.close()
