"""Migration 0122: the call-history index passes the schema gate, builds CONCURRENTLY
outside a transaction, matches what the Calls list asks for, and rolls back only while there is
no call history."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, text

from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261022_0122", "20261022_0121"
FILE = "20261022_0122_lead_desk_call_submission_index.py"
INDEX = "ix_lead_desk_event_call_submission"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("call_submission_index_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _index(engine: Engine) -> tuple[str, bool] | None:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT pg_get_indexdef(i.indexrelid), i.indisvalid FROM pg_index i"
                " JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
            ),
            {"name": INDEX},
        ).first()
    return None if row is None else (row[0], row[1])


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    found = classify_source(path.read_text(), str(path))
    # The schema gate proves the concurrent build lock-safe. The classifier reads any
    # block in upgrade() as "unknown" (manual review), and only because of the
    # autocommit block: nothing destructive, nothing else unclassified.
    check_operations([found], set())
    assert found.verdict == "unknown"
    assert set(found.reasons) == {
        "upgrade() contains unsupported With control flow",
        "op.create_index adds schema objects",
        "upgrade() contains a helper or unsupported call",
        "nested op.create_index call is not classified",
        "nested op.get_context call is not classified",
    }


def test_index_builds_concurrently_and_matches_the_lookup(postgres_harness: Engine) -> None:
    built = _index(postgres_harness)
    assert built is not None and built[1]
    definition = built[0]
    assert "lead_desk_events" in definition
    assert "(tenant_id, ((data ->> 'submission_id'::text)))" in definition
    assert "WHERE ((kind)::text = 'call'::text)" in definition
    # Rebuilt by the migration itself, outside a transaction (CONCURRENTLY).
    with postgres_harness.connect() as connection:
        connection.execute(text(f"DROP INDEX {INDEX}"))
        connection.commit()
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
    assert _index(postgres_harness) == built


def test_rollback_with_call_history_requires_forward_recovery() -> None:
    module = migration()
    module.op = SimpleNamespace(get_bind=lambda: SimpleNamespace(scalar=lambda statement: True))
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()


def test_rollback_without_call_history_drops_the_index_concurrently(
    postgres_harness: Engine,
) -> None:
    built = _index(postgres_harness)
    assert built is not None
    with postgres_harness.connect() as connection:
        calls = connection.execute(
            text("SELECT count(*) FROM lead_desk_events WHERE kind = 'call'")
        ).scalar_one()
        assert calls == 0  # the module's database holds no call history
        connection.commit()
        with Operations.context(MigrationContext.configure(connection)):
            migration().downgrade()
        connection.commit()
    assert _index(postgres_harness) is None
    with postgres_harness.connect() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        connection.commit()
    assert _index(postgres_harness) == built
