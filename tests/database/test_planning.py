from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

from ac_platform.db.models import model_metadata


class _MigrationRecorder:
    def __init__(self) -> None:
        self.metadata = sa.MetaData()
        self.tables: dict[str, sa.Table] = {}
        self.indexes: dict[str, tuple[str, tuple[str, ...], bool]] = {}

    def f(self, name: str) -> str:
        return name

    def create_table(self, name: str, *items: Any) -> sa.Table:
        table = sa.Table(name, self.metadata, *items)
        self.tables[name] = table
        return table

    def create_index(
        self,
        name: str,
        table_name: str,
        columns: list[str],
        *,
        unique: bool = False,
        **_kwargs: Any,
    ) -> None:
        self.indexes[name] = (table_name, tuple(columns), unique)


def _migration() -> Any:
    path = (
        Path(__file__).parents[2]
        / "db"
        / "migrations"
        / "versions"
        / "20260902_0014_planning_analytics.py"
    )
    spec = importlib.util.spec_from_file_location("planning_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_planning_models_are_registered_and_migration_is_forward_only() -> None:
    metadata = model_metadata()
    assert {
        "learning_plan_items",
        "learning_next_action_projections",
        "analytics_events",
    } <= set(metadata.tables)

    migration = _migration()
    assert migration.revision == "20260902_0014"
    assert migration.down_revision == "20260902_0013"
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()


def test_planning_migration_columns_foreign_keys_and_indexes_match_models() -> None:
    migration = _migration()
    recorder = _MigrationRecorder()
    migration.op = recorder
    migration.upgrade()
    metadata = model_metadata()

    assert set(recorder.tables) == {
        "learning_plan_items",
        "learning_next_action_projections",
        "analytics_events",
    }
    for table_name, migration_table in recorder.tables.items():
        model_table = metadata.tables[table_name]
        assert {
            column.name: (column.nullable, type(column.type)) for column in migration_table.columns
        } == {column.name: (column.nullable, type(column.type)) for column in model_table.columns}
        assert tuple(column.name for column in migration_table.primary_key.columns) == tuple(
            column.name for column in model_table.primary_key.columns
        )
        assert {
            constraint.name: (
                tuple(constraint.column_keys),
                tuple(element.target_fullname for element in constraint.elements),
            )
            for constraint in migration_table.foreign_key_constraints
        } == {
            constraint.name: (
                tuple(constraint.column_keys),
                tuple(element.target_fullname for element in constraint.elements),
            )
            for constraint in model_table.foreign_key_constraints
        }

    expected_indexes = {
        item.name: (item.table.name, tuple(column.name for column in item.columns), item.unique)
        for table in metadata.tables.values()
        for item in table.indexes
        if item.name in recorder.indexes
    }
    assert recorder.indexes == expected_indexes
