"""Real PostgreSQL proof for the plans catalogue (migration 0065, Plans C1).

0065 applies after 0064 under the current head; the ``plans`` model has no drift; the
three seeds are ``coming_soon`` with every price and limit NULL; the database
checks and the PostgreSQL key regex refuse bad rows; the migration is forward-only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.plans import Plan
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness

ROOT = Path(__file__).parents[2]
REVISION = "20261002_0065"
HEAD = "20261002_0066"
SEEDS = {
    "personal": ("Personal", "For one salesperson", 10),
    "organisation": ("Organisation", "For sales teams", 20),
    "enterprise": ("Enterprise", "For large sales companies", 30),
}


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": uuid4(),
        "key": "draft_" + uuid4().hex[:8],
        "name": "Draft",
        "audience": "Fictional",
        "status": "draft",
        "feature_keys": [],
        "top_up_packs": [],
        "sort_order": 99,
        "revision": 1,
    }
    row.update(overrides)
    return row


def test_0065_applies_after_0064_under_the_head(postgres_harness: Engine) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision(REVISION).down_revision == "20261001_0064"
    assert scripts.get_current_head() == HEAD
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert "plans" in inspect(connection).get_table_names()


def test_plans_table_has_no_model_drift(postgres_harness: Engine) -> None:
    with postgres_harness.connect() as connection:
        drift = compare_metadata(MigrationContext.configure(connection), model_metadata())
    assert [entry for entry in drift if "plans" in repr(entry)] == []


def test_seeds_are_three_coming_soon_rows_with_nothing_set(postgres_harness: Engine) -> None:
    with Session(postgres_harness) as session:
        plans = session.scalars(select(Plan).order_by(Plan.sort_order)).all()
    assert [plan.key for plan in plans] == ["personal", "organisation", "enterprise"]
    for plan in plans:
        name, audience, sort_order = SEEDS[plan.key]
        assert (plan.name, plan.audience, plan.sort_order) == (name, audience, sort_order)
        assert (plan.status, plan.revision, plan.per_seat) == ("coming_soon", 1, False)
        assert (plan.feature_keys, plan.top_up_packs) == ([], [])
        assert plan.monthly_price_paise is None and plan.yearly_price_paise is None
        assert plan.monthly_price_cents is None and plan.yearly_price_cents is None
        assert plan.included_minutes is None and plan.seat_min is None and plan.seat_max is None
        assert plan.longest_call_minutes is None and plan.retention_days is None
        assert plan.rollover_months is None
        assert plan.created_at is not None and plan.updated_at is not None


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"key": "Personal"}, "ck_plans_key_shape"),
        ({"key": "1plan"}, "ck_plans_key_shape"),
        ({"key": "p"}, "ck_plans_key_shape"),
        ({"key": "personal"}, "uq_plans_key"),
        ({"status": "trial"}, "ck_plans_status_supported"),
        ({"monthly_price_paise": -1}, "ck_plans_monthly_price_paise_not_negative"),
        ({"seat_min": 3, "seat_max": 2}, "ck_plans_seat_max_not_below_seat_min"),
        ({"longest_call_minutes": 0}, "ck_plans_longest_call_minutes_positive"),
        ({"revision": 0}, "ck_plans_revision_positive"),
    ],
)
def test_database_refuses_bad_rows_even_without_the_model(
    postgres_harness: Engine, overrides: dict[str, object], constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=constraint), postgres_harness.begin() as connection:
        connection.execute(insert(Plan.__table__).values(**_row(**overrides)))
    with postgres_harness.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM plans")) == 3


def test_migration_0065_is_forward_only() -> None:
    path = ROOT / "db/migrations/versions/20261002_0065_plans.py"
    spec = importlib.util.spec_from_file_location("plans_0065", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
