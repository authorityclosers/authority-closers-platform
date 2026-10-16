"""Two-hour receipt persistence and guarded rollback on disposable PostgreSQL.

No native decoding, provider call or live allowance changes occur here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.db.models import model_metadata
from tests.database.test_conversation_acquisition_postgresql import issue, service, source
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed


@pytest.fixture
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_two_hours_uses_existing_organisation_plan_and_sufficient_allowance(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine, role="owner")
            foreign = await seed(engine)
            measured = source(7200)
            async with AsyncSession(engine) as db, db.begin():
                app = AcquisitionSessions(
                    db,
                    tenant_id=state.tenant_id,
                    policy_revision="duration-fixture",
                    clock=lambda: state.now,
                    trial_enabled=False,
                )
                account = await app.ledger.organisation_account(
                    tenant_id=state.tenant_id, create=True
                )
                await app.ledger.write_lot(
                    account=account,
                    kind="period_grant",
                    seconds=7200,
                    valid_from=state.now,
                    source_ref="fictional-two-hour-allowance:" + str(uuid4()),
                    actor_type="system",
                    plan_key="organisation",
                )
                assert (await app.allowance(actor=state.actor))["available_seconds"] == 7200
                usage_id = await app.reserve(measured, actor=state.actor)
                assert await app.reserve(measured, actor=state.actor) == usage_id
                with pytest.raises(ConversationDenied, match="remaining trial minutes"):
                    await app.reserve(source(1), actor=state.actor)
                await app.settle(usage_id, charged_seconds=7200, receipt_sha256="d" * 64)
                await app.settle(usage_id, charged_seconds=7200, receipt_sha256="d" * 64)
                assert await app.allowance(actor=state.actor) == {
                    "allowance_seconds": 7200,
                    "committed_seconds": 7200,
                    "available_seconds": 0,
                }
                stored = await db.get(ConversationAcquisitionUsage, usage_id)
                assert stored.source_sha256 == measured.source_sha256
                assert stored.duration_evidence_sha256 == measured.duration_evidence_sha256
                assert stored.reserved_seconds == 7200
                assert (
                    await db.get(ConversationAcquisitionSettlement, usage_id)
                ).charged_seconds == (7200)
            async with AsyncSession(engine) as db, db.begin():
                with pytest.raises(ConversationDenied):
                    await service(db, foreign).reserve(measured, actor=state.actor)
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_larger_receipt_ceiling_does_not_expand_trial_allowance(postgres_harness):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                assert (await app.allowance(token=guest.token))["available_seconds"] == 3600
                with pytest.raises(ConversationDenied, match="longest call"):
                    await app.reserve(source(7200), token=guest.token)
                with pytest.raises(ConversationDenied, match="remaining trial minutes"):
                    await app.reserve(source(4000), token=guest.token)
                assert (
                    await db.scalar(select(func.count()).select_from(ConversationAcquisitionUsage))
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("target", ["usage", "settlement", "journal"])
def test_0090_preserves_history_bounds_each_table_and_refuses_unsafe_rollback(
    postgres_harness, target
):
    async def fixture():
        engine = create_async_engine(postgres_harness.url)
        try:
            state = await seed(engine)
            guest = await issue(engine, state)
            async with AsyncSession(engine) as db, db.begin():
                app = service(db, state)
                usage_id = await app.reserve(source(60), token=guest.token)
                await app.settle(usage_id, charged_seconds=60, receipt_sha256="d" * 64)
                db.add(
                    ConversationReportMinuteEvent(
                        usage_id=usage_id,
                        revision=1,
                        key="fictional-reserved",
                        kind="reserved",
                        seconds=60,
                        plan_id=None,
                        report_draft_id=None,
                        receipt_sha256="e" * 64,
                        created_at=state.now,
                    )
                )
                return usage_id
        finally:
            await engine.dispose()

    usage_id = run(fixture())
    path = (
        Path(__file__).resolve().parents[2]
        / "db/migrations/versions/20261013_0090_recording_duration_7200.py"
    )
    spec = importlib.util.spec_from_file_location("recording_duration_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert (migration.revision, migration.down_revision) == ("20261013_0090", "20261013_0089")
    tables = {
        "usage": (ConversationAcquisitionUsage.__table__, "reserved_seconds"),
        "settlement": (ConversationAcquisitionSettlement.__table__, "charged_seconds"),
        "journal": (ConversationReportMinuteEvent.__table__, "seconds"),
    }
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        old = {
            name: dict(connection.execute(select(table)).mappings().one())
            for name, (table, _) in tables.items()
        }
        migration.downgrade()
        table, column = tables[target]
        # Exercise each physical table bound independently. These inserts are
        # schema probes, not canonical settlement or publication commands.
        new_usage = {**old["usage"], "id": uuid4(), "submission_id": uuid4()}
        if target == "usage":
            large = {**new_usage, "reserved_seconds": 7200}
        elif target == "settlement":
            connection.execute(tables["usage"][0].insert().values(new_usage))
            large = {**old[target], "usage_id": new_usage["id"], "charged_seconds": 7200}
        else:
            large = {**old[target], "revision": 2, "key": "fictional-large", "seconds": 7200}
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(table.insert().values(large))
        migration.upgrade()
        for name, (original_table, _) in tables.items():
            predicate = (
                original_table.c.id == usage_id
                if name == "usage"
                else original_table.c.usage_id == usage_id
            )
            assert (
                dict(connection.execute(select(original_table).where(predicate)).mappings().one())
                == (old[name])
            )
        connection.execute(table.insert().values(large))
        over = {**large, column: 7201}
        if target == "usage":
            over.update(id=uuid4(), submission_id=uuid4())
        elif target == "settlement":
            over_usage = {**new_usage, "id": uuid4(), "submission_id": uuid4()}
            connection.execute(tables["usage"][0].insert().values(over_usage))
            over["usage_id"] = over_usage["id"]
        else:
            over.update(revision=3, key="fictional-over-bound")
        with pytest.raises(DBAPIError), connection.begin_nested():
            connection.execute(table.insert().values(over))
        with pytest.raises(RuntimeError, match="forward recovery"):
            migration.downgrade()
        assert (
            connection.scalar(
                select(func.count()).select_from(table).where(table.c[column] == 7200)
            )
            == 1
        )
        # The rehearsal ends at the repository's current head, whichever later
        # migration that is (a pinned revision broke on every new migration).
        head = ScriptDirectory.from_config(
            Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        ).get_current_head()
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
