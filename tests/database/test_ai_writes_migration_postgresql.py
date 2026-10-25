"""Migrations 0131 (the AI-write ledger) and 0132 (tasks from AI apps): they pass the schema
gate, are reversible while unused, match the models, their constraints hold (a retried
request records nothing twice, a change is undone at most once, each door names its
connection or key), and history in use requires forward recovery."""

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
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.models import Lead, LeadTask
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ("20261025_0131", "20261025_0130", "20261025_0131_integration_writes.py")
TASKS = ("20261025_0132", "20261025_0131", "20261025_0132_lead_desk_task_assistant.py")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration(file: str) -> Any:
    path = ROOT / "db/migrations/versions" / file
    spec = importlib.util.spec_from_file_location(file.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("chain", [LEDGER, TASKS])
def test_migration_chain_and_schema_gate_rules(chain: tuple[str, str, str]) -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    revision, down, file = chain
    module = migration(file)
    assert (module.revision, module.down_revision) == (revision, down)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_unused_migrations_downgrade_reupgrade_and_match_the_models(
    postgres_harness: Engine,
) -> None:
    ledger, tasks = migration(LEDGER[2]), migration(TASKS[2])
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            tasks.downgrade()
            ledger.downgrade()
            assert "integration_writes" not in set(inspect(connection).get_table_names())
            ledger.upgrade()
            tasks.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _world(engine: Engine) -> tuple[Any, Any, Any]:
    tenant_id, person_id, lead_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        db.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Fictional Sales"))
        db.add(
            Person(
                id=person_id,
                email=f"seller-{person_id.hex}@example.test",
                display_name="Fictional Seller",
                email_verified_at=now,
            )
        )
        db.flush()
        db.add(Membership(tenant_id=tenant_id, person_id=person_id, role="member"))
        db.flush()
        db.add(
            Lead(
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
                test_data=False,
                created_at=now,
                updated_at=now,
            )
        )
    return tenant_id, person_id, lead_id


def test_ledger_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    writes: Any = IntegrationWrite.__table__
    tenant_id, person_id, lead_id = _world(postgres_harness)
    change = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "person_id": person_id,
        "via": "connection",
        "grant_id": uuid4(),
        "app_label": "ChatGPT",
        "action": "note",
        "lead_id": lead_id,
        "request_sha256": "a" * 64,
        "command_id": uuid4(),
        "event_id": uuid4(),
        "fields": ["note"],
        "created_at": datetime.now(UTC),
    }
    wrong_rows = (
        {"via": "email"},
        {"via": "key"},  # a key without its key id, and a connection id it must not have
        {"grant_id": None},  # a connection without its connection id
        {"action": "delete"},
        {"action": "undo"},  # an undo must say what it undoes
        {"request_sha256": None},  # only the app's own undo has no request
    )
    for wrong in wrong_rows:
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(
                writes.insert().values(**{**change, "id": uuid4(), "command_id": uuid4(), **wrong})
            )
    with postgres_harness.begin() as connection:
        connection.execute(writes.insert().values(**change))
    # A retried request records nothing twice.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(writes.insert().values(**{**change, "id": uuid4()}))
    undo = {
        **change,
        "id": uuid4(),
        "via": "app",
        "grant_id": None,
        "app_label": "Sales X-Ray",
        "action": "undo",
        "request_sha256": None,
        "command_id": uuid4(),
        "event_id": uuid4(),
        "fields": [],
        "undoes_id": change["id"],
    }
    with postgres_harness.begin() as connection:
        connection.execute(writes.insert().values(**undo))
    # A change is undone at most once.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(writes.insert().values(**{**undo, "id": uuid4(), "command_id": uuid4()}))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration(LEDGER[2]).downgrade()


def test_a_task_from_an_ai_app_requires_forward_recovery(postgres_harness: Engine) -> None:
    tasks: Any = LeadTask.__table__
    tenant_id, _, lead_id = _world(postgres_harness)
    now = datetime.now(UTC)
    task = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "lead_id": lead_id,
        "command_id": uuid4(),
        "revision": 1,
        "kind": "call_back",
        "title": "Call back Fictional Lead",
        "starts_at": now,
        "status": "open",
        "original_due_at": now,
        "snoozes": 0,
        "rollovers": 0,
        "source": "assistant",
        "created_at": now,
        "updated_at": now,
    }
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(tasks.insert().values(**{**task, "id": uuid4(), "source": "robot"}))
    with postgres_harness.begin() as connection:
        connection.execute(tasks.insert().values(**task))
    with (
        postgres_harness.begin() as connection,
        Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        ),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration(TASKS[2]).downgrade()
