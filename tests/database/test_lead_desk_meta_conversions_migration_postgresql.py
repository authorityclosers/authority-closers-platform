"""Migration 0104 (lead stages back to Meta): reversible while empty, constraints hold."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.lead_desk.models import LeadMetaConversion, LeadMetaConversionAttempt
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]

TABLES = {"lead_desk_meta_conversions", "lead_desk_meta_conversion_attempts"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions/20261019_0104_lead_desk_meta_conversions.py"
    spec = importlib.util.spec_from_file_location("lead_desk_meta_conversions_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261019_0104", "20261019_0103")
    path = Path(module.__file__)
    item = classify_source(path.read_text(), str(path))
    check_operations([item], set())


def test_empty_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        assert set(inspect(connection).get_table_names()) >= TABLES
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not TABLES & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _row(tenant_id: Any, **changes: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "lead_id": uuid4(),
        "source_event_id": uuid4(),
        "dataset_id": "777000222",
        "stage": "won",
        "event_name": "Won",
        "event_time": now,
        "payload": {"event_name": "Won"},
        "payload_sha256": "a" * 64,
        "status": "pending",
        "attempts": 0,
        "next_attempt_at": now,
        "created_at": now,
    }
    values.update(changes)
    return values


def test_one_event_per_lead_and_stage_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    rows: Any = LeadMetaConversion.__table__
    attempts: Any = LeadMetaConversionAttempt.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional org")
        )
    refused: tuple[dict[str, Any], ...] = (
        {"status": "sent"},
        {"stage": "booked"},
        {"dataset_id": "pixel-1"},
        {"event_name": " "},
        {"status": "delivered"},  # delivered needs its time
        {"payload": None},  # an emptied body needs its erasure time
        {"payload_sha256": "short"},
        {"last_http_status": 42},
    )
    for changes in refused:
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(rows.insert().values(**_row(tenant_id, **changes)))
    first = _row(tenant_id)
    with postgres_harness.begin() as connection:
        connection.execute(rows.insert().values(**first))
    # The same lead, dataset and stage name is one event.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(rows.insert().values(**{**first, "id": uuid4()}))
    now = datetime.now(UTC)
    attempt = {
        "conversion_id": first["id"],
        "attempt": 1,
        "started_at": now,
        "finished_at": now,
        "http_status": 200,
        "error_code": None,
        "events_received": 1,
        "fbtrace_id": "T1",
        "duration_ms": 120,
    }
    for changes in ({"attempt": 0}, {"http_status": None}, {"duration_ms": -1}):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(attempts.insert().values(**{**attempt, **changes}))
    with postgres_harness.begin() as connection:
        connection.execute(attempts.insert().values(**attempt))
    module = migration()
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
