"""Migration 0133, a seller's open-lead limit may be none: passes the schema gate, reversible
while no seller has No limit, matches the models, its check still refuses 0 and 1001, and a
seller with No limit requires forward recovery."""

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
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.lead_desk.models import LeadRep
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261025_0133", "20261025_0132"
FILE = "20261025_0133_lead_desk_rep_no_limit.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_rep_limit_migration", path)
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
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_the_check_holds_and_no_limit_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    reps: Any = LeadRep.__table__
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
    row = {
        "tenant_id": tenant_id,
        "person_id": person_id,
        "revision": 1,
        "available": True,
        "languages": [],
        "areas": [],
        "interests": [],
        "updated_at": now,
    }
    for wrong in (0, 1001):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(reps.insert().values(**row, max_open=wrong))
    with postgres_harness.begin() as connection:
        connection.execute(reps.insert().values(**row, max_open=None))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
