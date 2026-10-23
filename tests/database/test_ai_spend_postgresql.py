"""AI spend on PostgreSQL: the ledger, the guard before every model call, the migration.

Owner, 20 Oct 2026: "stop the leakage of credits and tokens". Disposable loopback
PostgreSQL, fictional rows only; the text model is a local fake (no network, no key).
"""

from __future__ import annotations

import argparse
import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, insert, inspect
from sqlalchemy.orm import sessionmaker

from ac_platform.ai_spend import guard, ledger, policy
from ac_platform.ai_spend.models import AiSpendSettings
from ac_platform.call_data.runner import run_pass
from ac_platform.db.models import model_metadata
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import FakeModel, _call, _process

ROOT = Path(__file__).resolve().parents[2]
FILE = ROOT / "db/migrations/versions/20261020_0112_ai_spend_settings.py"


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def _save(engine: Engine, environment: str, config: dict[str, Any]) -> None:
    with engine.begin() as connection:
        revision = (guard.read_settings(connection, environment)[1] or 0) + 1
        connection.execute(
            insert(AiSpendSettings).values(
                id=uuid4(),
                revision=revision,
                config=policy.validate(environment, config),
                reason="test",
                created_by_person_id=None,
                created_at=datetime.now(UTC),
            )
        )


def _code(engine: Engine, feature: str, environment: str, trigger: str = "auto") -> str | None:
    with engine.connect() as connection:
        refusal = guard.check(connection, feature, environment=environment, trigger=trigger)
    return None if refusal is None else refusal.code


def test_the_ledger_reads_a_run_and_the_guard_applies_every_rule(
    postgres_harness: Engine,
) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"
    with postgres_harness.connect() as connection:
        rows = ledger.read(connection, datetime.now(UTC) - timedelta(hours=1))
    fast = [row for row in rows if row.feature == "call_data_fast"]
    assert len(fast) == 1
    assert (fast[0].trigger, fast[0].requests, fast[0].priced) == ("operator", 1, True)
    spent = fast[0].inr  # 7,000 in and 1,500 out on Gemini 3.8 Flash: about ₹1
    assert Decimal("0.5") < spent < Decimal("2")

    # Hard rules on development, then its background switch (off by default).
    assert _code(postgres_harness, "call_data_deep", "development-live") == (
        "ai_spend_no_automatic_deep_on_development"
    )
    assert _code(postgres_harness, "pointer_review", "development", "backfill") == (
        "ai_spend_no_backfill_on_development"
    )
    assert _code(postgres_harness, "call_data_fast", "development") == "ai_spend_background_off"
    assert _code(postgres_harness, "lead_desk_ai", "development", "person") is None
    # A backfill needs its own cap, ₹0 until raised; everything else is under its caps.
    assert _code(postgres_harness, "call_data_fast", "staging", "backfill") == (
        "ai_spend_backfill_cap"
    )
    assert _code(postgres_harness, "pointer_review", "staging") is None
    assert _code(postgres_harness, "call_data_fast", "production") is None

    _save(postgres_harness, "staging", {"daily_cap_inr": 1})
    with postgres_harness.connect() as connection:
        refusal = guard.check(connection, "call_data_fast", environment="staging")
    assert refusal is not None
    assert refusal.line() == {
        "stopped": "ai_spend_daily_cap",
        "feature": "call_data_fast",
        "spent_inr": f"{spent:.2f}",
        "cap_inr": 1,
    }
    _save(postgres_harness, "staging", {"daily_cap_inr": 100, "monthly_cap_inr": 1})
    assert _code(postgres_harness, "call_data_fast", "staging") == "ai_spend_monthly_cap"
    _save(postgres_harness, "staging", {"feature_caps_inr": {"pointer_review": 0}})
    assert _code(postgres_harness, "pointer_review", "staging") == "ai_spend_feature_cap"
    assert _code(postgres_harness, "call_data_fast", "staging") is None
    _save(postgres_harness, "staging", {"background_enabled": False})
    assert _code(postgres_harness, "call_data_fast", "staging") == "ai_spend_background_off"
    _save(postgres_harness, "staging", {"backfill_daily_cap_inr": 15})
    assert _code(postgres_harness, "call_data_fast", "staging", "backfill") is None


def test_brain4_reads_stop_only_at_their_own_cap(postgres_harness: Engine) -> None:
    """Owner, 23 Oct 2026 (launch decision 2): Brain 4.0's read is the Report, so the
    environment's totals and the background switch never stop it; its own cap does."""
    caps = {"brain4_shadow": 300, "pointer_review": 200}
    _save(
        postgres_harness,
        "production",
        {"daily_cap_inr": 0, "monthly_cap_inr": 0, "feature_caps_inr": caps},
    )
    assert _code(postgres_harness, "pointer_review", "production") == "ai_spend_daily_cap"
    assert _code(postgres_harness, "brain4_shadow", "production") is None
    _save(
        postgres_harness,
        "production",
        {"background_enabled": False, "feature_caps_inr": caps},
    )
    assert _code(postgres_harness, "pointer_review", "production") == "ai_spend_background_off"
    assert _code(postgres_harness, "brain4_shadow", "production") is None
    # A zero cap still turns it off, and the hard rules and the backfill cap still apply.
    _save(postgres_harness, "production", {"feature_caps_inr": {"brain4_shadow": 0}})
    assert _code(postgres_harness, "brain4_shadow", "production") == "ai_spend_feature_cap"
    assert _code(postgres_harness, "brain4_shadow", "development", "backfill") == (
        "ai_spend_no_backfill_on_development"
    )
    _save(postgres_harness, "production", {"feature_caps_inr": caps})
    assert _code(postgres_harness, "brain4_shadow", "production", "backfill") == (
        "ai_spend_backfill_cap"
    )
    with postgres_harness.connect() as connection, pytest.raises(ValueError):
        guard.check(connection, "call_report", environment="production")


def test_a_saved_document_that_no_longer_validates_falls_back_to_the_defaults(
    postgres_harness: Engine,
) -> None:
    with postgres_harness.begin() as connection:
        connection.execute(
            insert(AiSpendSettings).values(
                id=uuid4(),
                revision=1,
                config={"daily_cap_inr": "lots"},
                reason=None,
                created_by_person_id=None,
                created_at=datetime.now(UTC),
            )
        )
    with postgres_harness.connect() as connection:
        config, revision = guard.read_settings(connection, "production")
        assert guard.skipped_tenants(connection, "production") == set()
    assert (config, revision) == (policy.defaults("production"), 1)


def test_the_call_data_runner_asks_the_guard_before_the_model(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    sessions = sessionmaker(postgres_harness, expire_on_commit=False)
    arguments = argparse.Namespace(
        pipeline="fast",
        backfill=False,
        recording=seeded["recording_id"],
        force=False,
        not_before=datetime.now(UTC) - timedelta(hours=1),
        recent_hours=48,
        limit=5,
        apply=True,
    )
    model = FakeModel()
    lines = run_pass(
        sessions, arguments, model, created_by="test:ai-spend", spend_environment="development"
    )
    assert model.calls == 0
    assert {"stopped": "ai_spend_background_off"}.items() <= next(
        line for line in lines if line.get("stopped")
    ).items()
    lines = run_pass(
        sessions, arguments, model, created_by="test:ai-spend", spend_environment="staging"
    )
    assert model.calls == 1
    assert lines[0]["outcome"] == "succeeded"


def _migration() -> Any:
    spec = importlib.util.spec_from_file_location("ai_spend_migration_test", FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_additive_and_passes_the_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = _migration()
    assert (module.revision, module.down_revision) == ("20261020_0112", "20261020_0111")
    item = classify_source(FILE.read_text(), str(FILE))
    check_operations([item], set())
    assert item.verdict == "additive"


def test_empty_migration_round_trips_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    module = _migration()
    with postgres_harness.begin() as connection:
        assert "ai_spend_settings" in inspect(connection).get_table_names()
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert "ai_spend_settings" not in inspect(connection).get_table_names()
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
    _save(postgres_harness, "staging", {"daily_cap_inr": 200})
    with (
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        module.downgrade()
