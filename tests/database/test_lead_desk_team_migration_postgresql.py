"""Migration 0130, the team engine's targets and nudge ledger: passes the schema gate,
reversible while unused, matches the models, its constraints hold (a retried command sets
no second target, one nudge per seller and window), and history in use requires forward
recovery."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
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
from ac_platform.lead_desk.models import LeadNudge, LeadTarget
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261025_0130", "20261024_0129"
FILE = "20261025_0130_lead_desk_team.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_team_migration", path)
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
            assert not {"lead_desk_targets", "lead_desk_nudges"} & tables
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    targets: Any = LeadTarget.__table__
    nudges: Any = LeadNudge.__table__
    tenant_id, person_id = uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(postgres_harness) as db, db.begin():
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
    target = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "person_id": person_id,
        "period": "day",
        "metric": "calls",
        "value": 40,
        "effective_from": date(2026, 10, 26),
        "command_id": uuid4(),
        "created_at": now,
    }
    for wrong in ({"period": "month"}, {"metric": "smiles"}, {"value": -1}, {"value": 10001}):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(targets.insert().values(**{**target, "id": uuid4(), **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(targets.insert().values(**target))
    # A retried command sets no second target.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(targets.insert().values(**{**target, "id": uuid4()}))
    # A new value from the next day is a new row: the old one stays for its days.
    with postgres_harness.begin() as connection:
        connection.execute(
            targets.insert().values(
                **{
                    **target,
                    "id": uuid4(),
                    "command_id": uuid4(),
                    "value": 50,
                    "effective_from": date(2026, 10, 27),
                }
            )
        )
    window = now.replace(minute=0, second=0, microsecond=0)
    nudge = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "person_id": person_id,
        "kind": "drift",
        "window_start": window,
        "words": "You're 6 calls behind today's pace.",
        "claimed_at": now,
    }
    with postgres_harness.begin() as connection:
        connection.execute(nudges.insert().values(**nudge))
    # One nudge per seller and window: a second sender's claim fails, whatever its kind.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(nudges.insert().values(**{**nudge, "id": uuid4(), "kind": "idle"}))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            nudges.insert().values(
                **{
                    **nudge,
                    "id": uuid4(),
                    "kind": "nag",
                    "window_start": window + timedelta(hours=2),
                }
            )
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
