"""Migration 0134, duplicate leads' pairs, decisions and merges: passes the schema gate,
reversible while unused, matches the models, its checks hold (a pair in order, a known band
and decision, a merge of two leads, a retried merge once), and a decision requires forward
recovery."""

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
from ac_platform.lead_desk.models import (
    Lead,
    LeadDuplicateDecision,
    LeadDuplicatePair,
    LeadMerge,
)
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261025_0134", "20261025_0133"
FILE = "20261025_0134_lead_desk_duplicates.py"
NEW = {"lead_desk_duplicate_pairs", "lead_desk_duplicate_decisions", "lead_desk_merges"}


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("lead_desk_duplicates_migration", path)
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
            inspector = inspect(connection)
            assert not NEW & set(inspector.get_table_names())
            columns = {column["name"] for column in inspector.get_columns("lead_desk_leads")}
            assert not {"merged_into_id", "merged_at"} & columns
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_checks_hold_and_decisions_require_forward_recovery(postgres_harness: Engine) -> None:
    pairs: Any = LeadDuplicatePair.__table__
    decisions: Any = LeadDuplicateDecision.__table__
    merges: Any = LeadMerge.__table__
    tenant_id = uuid4()
    now = datetime.now(UTC)
    low, high = sorted((uuid4(), uuid4()))
    with Session(postgres_harness) as db, db.begin():
        db.add(Tenant(id=tenant_id, slug=tenant_id.hex, name="Fictional Sales"))
        db.flush()
        for lead_id, phone in ((low, "+919876078001"), (high, "+919876078002")):
            db.add(
                Lead(
                    id=lead_id,
                    tenant_id=tenant_id,
                    revision=1,
                    source="manual",
                    payload={},
                    name="Fictional Lead",
                    phone=phone,
                    stage="new",
                    attempts=0,
                    calls=0,
                    repeats=0,
                    test_data=False,
                    created_at=now,
                    updated_at=now,
                )
            )
    pair = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "first_lead_id": low,
        "second_lead_id": high,
        "score": 80,
        "band": "probable",
        "reasons": ["same last 10 digits of the phone"],
        "against": [],
        "computed_at": now,
    }
    for wrong in (
        {"band": "maybe"},
        {"first_lead_id": high, "second_lead_id": low},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(pairs.insert().values(**{**pair, **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(pairs.insert().values(**pair))
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(pairs.insert().values(**{**pair, "id": uuid4()}))
    merge = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "survivor_lead_id": low,
        "merged_lead_id": high,
        "owner_reason": "Kept with nobody: no one worked on it",
        "moved": {},
        "command_id": uuid4(),
        "created_at": now,
    }
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(merges.insert().values(**{**merge, "merged_lead_id": low}))
    with postgres_harness.begin() as connection:
        connection.execute(merges.insert().values(**merge))
    # A retried merge command is one merge.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(merges.insert().values(**{**merge, "id": uuid4()}))
    decision = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "first_lead_id": low,
        "second_lead_id": high,
        "decision": "not_same",
        "decided_at": now,
    }
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(decisions.insert().values(**{**decision, "decision": "maybe"}))
    with postgres_harness.begin() as connection:
        connection.execute(decisions.insert().values(**decision))
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
