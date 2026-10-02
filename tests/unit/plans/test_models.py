"""SQLite proof for the plans catalogue model and the forward-only 0065 migration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.plans import (
    Plan,
    PlanValidationError,
    validate_plan_key,
    validate_top_up_packs,
)

MIGRATION = Path(__file__).parents[3] / "db/migrations/versions/20261002_0065_plans.py"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    model_metadata()
    Plan.__table__.create(engine)
    return Session(engine)


def _plan(**overrides: Any) -> Plan:
    fields: dict[str, Any] = {
        "key": "personal",
        "name": "Personal",
        "audience": "For one salesperson",
        "status": "coming_soon",
        "sort_order": 10,
    }
    fields.update(overrides)
    return Plan(**fields)


def _pack(**overrides: Any) -> dict[str, Any]:
    pack: dict[str, Any] = {
        "key": "pack_100",
        "minutes": 100,
        "validity_rule": "billing_year_end",
        "price_paise": None,
        "price_cents": None,
    }
    pack.update(overrides)
    return pack


def test_coming_soon_row_round_trips_with_unset_values_as_null(session: Session) -> None:
    with session.begin():
        session.add(_plan())
    stored = session.query(Plan).one()
    assert stored.status == "coming_soon"
    assert stored.per_seat is False
    assert stored.revision == 1
    assert (stored.feature_keys, stored.top_up_packs) == ([], [])
    assert stored.monthly_price_paise is None and stored.included_minutes is None
    assert stored.seat_min is None and stored.seat_max is None
    assert stored.created_at is not None and stored.updated_at is not None


@pytest.mark.parametrize("key", ["Personal", "1plan", "p", "a" * 41, "plan-a", "", None])
def test_plan_key_must_match_the_contract(key: object) -> None:
    with pytest.raises(PlanValidationError, match="plan key"):
        validate_plan_key(key)


def test_plan_key_contract_accepts_lowercase_slugs() -> None:
    assert validate_plan_key("org_2") == "org_2"
    assert validate_plan_key("a" * 40) == "a" * 40
    with pytest.raises(PlanValidationError):
        _plan(key="Bad Key")


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"status": "trial"}, "status_supported"),
        ({"monthly_price_paise": -1}, "monthly_price_paise_not_negative"),
        ({"yearly_price_cents": -1}, "yearly_price_cents_not_negative"),
        ({"included_minutes": -1}, "included_minutes_not_negative"),
        ({"seat_min": 0}, "seat_min_positive"),
        ({"seat_min": 5, "seat_max": 4}, "seat_max_not_below_seat_min"),
        ({"longest_call_minutes": 0}, "longest_call_minutes_positive"),
        ({"retention_days": 0}, "retention_days_positive"),
        ({"rollover_months": -1}, "rollover_months_not_negative"),
        ({"revision": 0}, "revision_positive"),
        ({"key": "ab", "name": "Duplicate"}, "uq_plans_key|UNIQUE"),
    ],
)
def test_database_checks_refuse_bad_rows(
    session: Session, overrides: dict[str, Any], constraint: str
) -> None:
    with session.begin():
        session.add(_plan(key="ab"))
    with pytest.raises(IntegrityError, match=constraint), session.begin():
        session.add(_plan(**{"key": "cd", **overrides}))


def test_seat_bounds_and_prices_accept_null_and_confirmed_values(session: Session) -> None:
    with session.begin():
        session.add(_plan(key="org", seat_min=2, seat_max=None, monthly_price_paise=0))
        session.add(_plan(key="ent", seat_min=None, seat_max=50, per_seat=True))
    assert session.query(Plan).count() == 2


def test_raw_insert_cannot_bypass_the_scalar_checks(session: Session) -> None:
    with pytest.raises(IntegrityError, match="key_shape"), session.begin():
        session.execute(
            insert(Plan.__table__).values(
                key="x",
                name="X",
                audience="X",
                status="draft",
                feature_keys=[],
                top_up_packs=[],
                sort_order=0,
                revision=1,
            )
        )


def test_top_up_packs_accept_only_the_contract_shape() -> None:
    assert validate_top_up_packs([_pack(price_paise=0)]) == [_pack(price_paise=0)]
    assert validate_top_up_packs([]) == []
    for bad, message in (
        ([_pack(), _pack()], "repeated"),
        ([_pack(minutes=0)], "minutes"),
        ([_pack(minutes=True)], "minutes"),
        ([_pack(minutes=10.5)], "minutes"),
        ([_pack(validity_rule="calendar_year")], "validity_rule"),
        ([{**_pack(), "validity_days": 30}], "exactly"),
        ([_pack(price_paise=-1)], "price_paise"),
        ([_pack(price_cents=True)], "price_cents"),
        ([_pack(key="Pack")], "plan key"),
        (["pack_100"], "exactly"),
        ("pack_100", "must be a list"),
    ):
        with pytest.raises(PlanValidationError, match=message):
            validate_top_up_packs(bad)


def test_feature_keys_must_be_a_list_of_strings() -> None:
    assert _plan(feature_keys=["coaching"]).feature_keys == ["coaching"]
    with pytest.raises(PlanValidationError, match="feature_keys"):
        _plan(feature_keys=["coaching", 1])
    with pytest.raises(PlanValidationError, match="feature_keys"):
        _plan(feature_keys="coaching")


def test_migration_0065_seeds_three_coming_soon_rows_and_is_forward_only() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "20261002_0065"' in migration
    assert 'down_revision = "20261001_0064"' in migration
    for key in ("personal", "organisation", "enterprise"):
        assert f'"{key}"' in migration
    for absent in ("company", "trial", "credit_unit", "offline"):
        assert absent not in migration.lower()
    assert "key ~ '^[a-z][a-z0-9_]{1,39}$'" in migration
    downgrade = migration.split("def downgrade() -> None:", 1)[1]
    assert 'raise RuntimeError("forward-only")' in downgrade
    assert "drop_table" not in downgrade
