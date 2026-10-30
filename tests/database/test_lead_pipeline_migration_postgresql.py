"""Migration 0146, live or cold on every lead: passes the schema gate, reversible while
unused, matches the models, and leaves every existing lead as it was (owner, 30 Oct 2026:
no update may modify, reset or re-stage existing lead data)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect

from ac_platform.db.models import model_metadata
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261030_0146", "20261030_0145"
FILE = "20261030_0146_lead_pipeline.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_pipeline_migration", path)
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
            columns = {
                column["name"] for column in inspect(connection).get_columns("lead_desk_leads")
            }
            assert "pipeline" not in columns
            module.upgrade()
        column = next(
            column
            for column in inspect(connection).get_columns("lead_desk_leads")
            if column["name"] == "pipeline"
        )
        # Additive only: empty for every existing lead (read as live), no default rewrite.
        assert column["nullable"] is True
        assert column["default"] is None
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
