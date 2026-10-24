"""Migration for the Lead OS foundation (Junk, a lead's stage time and reason, meetings):
passes the schema gate, reversible while unused, matches the models, constraints hold,
and history in use requires forward recovery."""

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
from ac_platform.lead_desk.models import Lead, LeadMeeting
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261024_0128", "20261023_0127"
FILE = "20261024_0128_lead_os.py"
# Migrations after this one that change its tables: unwound around it, then redone.
LATER = ("20261024_0129_lead_desk_tasks.py",)


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration(file: str = FILE) -> Any:
    path = ROOT / "db/migrations/versions" / file
    spec = importlib.util.spec_from_file_location(f"lead_os_migration_{file[:13]}", path)
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
        later = [migration(file) for file in LATER]
        with Operations.context(context):
            for step in reversed(later):
                step.downgrade()
            module.downgrade()
            assert "lead_desk_meetings" not in inspect(connection).get_table_names()
            columns = {c["name"] for c in inspect(connection).get_columns("lead_desk_leads")}
            assert not {"stage_at", "outcome_reason"} & columns
            module.upgrade()
            for step in later:
                step.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _lead(tenant_id: Any, now: datetime, **values: Any) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "revision": 1,
        "source": "manual",
        "payload": {},
        "name": "Fictional Lead",
        "stage": "new",
        "attempts": 0,
        "calls": 0,
        "repeats": 0,
        "test_data": True,
        "created_at": now,
        "updated_at": now,
        **values,
    }


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    leads: Any = Lead.__table__
    meetings: Any = LeadMeeting.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional Sales")
        )
    # A reason only while Lost or Junk; Junk is a stage of its own.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(leads.insert().values(**_lead(tenant_id, now, outcome_reason="price")))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(leads.insert().values(**_lead(tenant_id, now, stage="spam")))
    lead = _lead(tenant_id, now, stage="junk", outcome_reason="fake", stage_at=now)
    with postgres_harness.begin() as connection:
        connection.execute(leads.insert().values(**lead))
    meeting = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "lead_id": lead["id"],
        "revision": 1,
        "status": "scheduled",
        "starts_at": now + timedelta(days=1),
        "duration_minutes": 30,
        "mode": "zoom",
        "created_at": now,
        "updated_at": now,
    }
    for wrong in (
        {"mode": "carrier_pigeon"},
        {"duration_minutes": 2},
        {"status": "done"},  # a closed meeting has its closing time
        {"status": "lost"},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(meetings.insert().values(**{**meeting, **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(meetings.insert().values(**meeting))
    # One scheduled meeting per lead; a held one beside it is fine.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(meetings.insert().values(**{**meeting, "id": uuid4()}))
    with postgres_harness.begin() as connection:
        connection.execute(
            meetings.insert().values(
                **{**meeting, "id": uuid4(), "status": "done", "closed_at": now}
            )
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
