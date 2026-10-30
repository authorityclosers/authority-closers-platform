"""Migration 0147, a task of your own: passes the schema gate, reversible while every task
has a lead, matches the models, and a task always has a lead or an owner. Once a task
without a lead exists, going back refuses: that history requires forward recovery."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from ac_platform.lead_desk.models import LeadTask
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261030_0147", "20261030_0146"
FILE = "20261030_0147_lead_desk_tasks_own.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_tasks_own_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    source = path.read_text()
    check_operations([classify_source(source, str(path))], set())
    assert "history requires forward recovery" in source


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            columns = {c["name"]: c for c in inspect(connection).get_columns("lead_desk_tasks")}
            assert columns["lead_id"]["nullable"] is False
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_a_task_has_a_lead_or_an_owner(postgres_harness: Engine) -> None:
    tasks: Any = LeadTask.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    due = now + timedelta(hours=1)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional Sales")
        )
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            tasks.insert().values(
                id=uuid4(),
                tenant_id=tenant_id,
                lead_id=None,
                owner_person_id=None,
                command_id=uuid4(),
                revision=1,
                kind="call_back",
                title="To do",
                starts_at=due,
                status="open",
                original_due_at=due,
                snoozes=0,
                rollovers=0,
                source="seller",
                created_at=now,
                updated_at=now,
            )
        )
