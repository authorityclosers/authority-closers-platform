"""Economics settings on PostgreSQL (owner, 23 Oct 2026: fixed costs editable in Admin).

Migration 0126 passes the schema gate and is forward-only; each save is a new revision and
the newest wins; until the first save the code's defaults apply; the ORM refuses updates and
deletes. Disposable loopback PostgreSQL, fictional numbers only.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.economics import policy, store
from ac_platform.economics.models import EconomicsHistoryError, EconomicsSettings
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261023_0126", "20261023_0125"
FILE = "20261023_0126_economics_settings.py"
NOW = datetime(2026, 10, 23, 6, 0, tzinfo=UTC)


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("economics_settings_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_forward_only() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()


def _with_server(rupees: int) -> dict[str, Any]:
    config = policy.validate({})
    config["fixed"] = [
        {**item, "rupees": rupees, "source": "invoice"} if item["key"] == "server_ac" else item
        for item in config["fixed"]
    ]
    return config


def test_saves_are_revisions_newest_wins_and_history_is_append_only(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            async with AsyncSession(engine) as db, db.begin():
                config, revision = await store.read(db)
                assert revision is None and config == policy.validate({})
                first = await store.save(
                    db, _with_server(2499), person_id=None, reason="October invoice", now=NOW
                )
                second = await store.save(
                    db, _with_server(2599), person_id=None, reason="November invoice", now=NOW
                )
                assert (first, second) == (1, 2)
            async with AsyncSession(engine) as db:
                config, revision = await store.read(db)
                assert revision == 2
                server = next(item for item in config["fixed"] if item["key"] == "server_ac")
                assert server["rupees"] == 2599 and server["source"] == "invoice"
                with pytest.raises(policy.SettingsError):
                    await store.save(db, {"routes": []}, person_id=None, reason=None, now=NOW)
                await db.rollback()
                row = await db.scalar(
                    select(EconomicsSettings).where(EconomicsSettings.revision == 1)
                )
                assert row is not None and row.reason == "October invoice"
                row.reason = "changed"
                with pytest.raises(EconomicsHistoryError):
                    await db.flush()
                await db.rollback()
                row = await db.scalar(
                    select(EconomicsSettings).where(EconomicsSettings.revision == 1)
                )
                assert row is not None
                await db.delete(row)
                with pytest.raises(EconomicsHistoryError):
                    await db.flush()
        finally:
            await engine.dispose()

    run(exercise())
