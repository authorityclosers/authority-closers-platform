"""Migration 0129, the work-memory engine's tasks and reminder ledger: passes the schema
gate, reversible while unused, matches the models, its constraints hold (a retried
command makes no second task, a reminder goes once per task, kind and due), and history
in use requires forward recovery."""

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
from ac_platform.lead_desk.models import Lead, LeadTask, LeadTaskReminder
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261024_0129", "20261024_0128"
FILE = "20261024_0129_lead_desk_tasks.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_tasks_migration", path)
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
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            tables = set(inspect(connection).get_table_names())
            assert not {"lead_desk_tasks", "lead_desk_task_reminders"} & tables
            columns = {c["name"] for c in inspect(connection).get_columns("lead_desk_meetings")}
            assert "task_id" not in columns
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    leads: Any = Lead.__table__
    tasks: Any = LeadTask.__table__
    reminders: Any = LeadTaskReminder.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    lead_id = uuid4()
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional Sales")
        )
        connection.execute(
            leads.insert().values(
                id=lead_id,
                tenant_id=tenant_id,
                revision=1,
                source="manual",
                payload={},
                name="Fictional Lead",
                stage="new",
                attempts=0,
                calls=0,
                repeats=0,
                test_data=True,
                created_at=now,
                updated_at=now,
            )
        )
    due = now + timedelta(hours=1)
    task = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "command_id": uuid4(),
        "revision": 1,
        "kind": "call_back",
        "title": "Call back Fictional Lead",
        "starts_at": due,
        "status": "open",
        "original_due_at": due,
        "snoozes": 0,
        "rollovers": 0,
        "source": "commitment",
        "created_at": now,
        "updated_at": now,
    }
    for wrong in (
        {"kind": "fax"},
        {"status": "later"},
        {"status": "done"},  # a done task has its time
        {"ends_at": due - timedelta(minutes=1)},
        {"remind_before_minutes": 2000},
        {"source": "guess"},
        {"title": "  "},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(tasks.insert().values(**{**task, "id": uuid4(), **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(tasks.insert().values(**task))
    # A retried command makes no second task.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(tasks.insert().values(**{**task, "id": uuid4()}))
    reminder = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "task_id": task["id"],
        "kind": "before",
        "for_due_at": due,
        "send_at": due - timedelta(minutes=5),
        "deferred": False,
        "claimed_at": now,
    }
    with postgres_harness.begin() as connection:
        connection.execute(reminders.insert().values(**reminder))
    # One reminder per task, kind and due: a second sender's claim fails.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(reminders.insert().values(**{**reminder, "id": uuid4()}))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(reminders.insert().values(**{**reminder, "id": uuid4(), "kind": "nag"}))
    # A snoozed task's new due reminds again.
    with postgres_harness.begin() as connection:
        connection.execute(
            reminders.insert().values(
                **{**reminder, "id": uuid4(), "for_due_at": due + timedelta(minutes=15)}
            )
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
