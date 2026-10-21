"""Migration for several pipelines per organisation: reversible while unused, matches the
models, constraints hold, and pipelines in use require forward recovery."""

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
from ac_platform.lead_desk.models import LeadPipeline
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261022_0121", "20261021_0120"
FILE = "20261022_0121_lead_desk_pipelines.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_pipelines_migration", path)
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
    found = classify_source(path.read_text(), str(path))
    assert found.verdict == "additive", found.reasons
    check_operations([found], set())


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration()
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert "lead_desk_pipelines" not in inspect(connection).get_table_names()
            for table in ("lead_desk_leads", "lead_desk_journey_versions"):
                columns = {c["name"] for c in inspect(connection).get_columns(table)}
                assert "pipeline_key" not in columns, table
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_constraints_hold_and_pipelines_in_use_require_forward_recovery(
    postgres_harness: Engine,
) -> None:
    pipelines: Any = LeadPipeline.__table__
    tenants: Any = Tenant.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        connection.execute(
            tenants.insert().values(id=tenant_id, slug=tenant_id.hex, name="Fictional Homes")
        )
    row = {
        "tenant_id": tenant_id,
        "key": "partner_outreach",
        "name": "Partner outreach",
        "position": 1,
        "sources": ["csv"],
        "created_at": now,
        "updated_at": now,
    }
    for wrong in ({"name": "  "}, {"position": -1}):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(pipelines.insert().values(**{**row, **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(pipelines.insert().values(**row))
    # One row per key in an organisation.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(pipelines.insert().values(**row))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
