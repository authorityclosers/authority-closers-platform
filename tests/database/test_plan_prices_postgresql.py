"""Admin plan prices on PostgreSQL (owner, 29 Oct 2026: "Admin price editor").

Migration 0143 passes the schema gate and rolls back only while no price change was saved. The
owner's change gives the plan a new revision that checkout and /v1/plans read at once, keeps
an append-only history row with the old and new prices, and refuses a stale revision, no
change, an unknown plan and a retired one. Disposable loopback PostgreSQL, fictional people.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.billing.catalogue import PlansTableCatalogue
from ac_platform.identity.models import Person
from ac_platform.plans.admin_http import (
    PriceCommand,
    PriceRefused,
    change_price,
    is_price_owner,
    price_view,
)
from ac_platform.plans.catalogue import read_public_catalogue
from ac_platform.plans.models import Plan, PlanPriceChange, PlanPriceHistoryError
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261029_0143", "20261027_0142"
FILE = "20261029_0143_plan_price_changes.py"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
SEAT = {"monthly_price_paise": 199_900, "yearly_price_paise": 1_999_000}


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("plan_price_changes_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_schema_gate_and_rollback_only_while_empty() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == (REVISION, DOWN)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())
    # With saved history the rollback refuses; on an empty table it drops what upgrade made.
    calls: list[str] = []
    module.op = SimpleNamespace(
        execute=lambda statement: calls.append("lock"),
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
        drop_table=lambda name: calls.append(f"drop {name}"),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()
    assert calls == ["lock"]
    calls.clear()
    module.op.get_bind = lambda: SimpleNamespace(scalar=lambda statement: False)
    module.downgrade()
    assert calls == ["lock", "drop plan_price_changes"]


def _person(email: str, *, verified: bool) -> Person:
    return Person(
        id=uuid4(),
        email=email,
        display_name="Fictional Person",
        email_verified_at=NOW if verified else None,
    )


def test_the_owner_sets_a_price_checkout_reads_it_and_history_is_append_only(
    postgres_harness: Any,
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            owner = _person("suyash@authorityclosers.com", verified=True)
            unverified = _person("admin@authorityclosers.com", verified=False)
            admin = _person(f"admin-{uuid4().hex[:8]}@example.test", verified=True)
            async with AsyncSession(engine) as db, db.begin():
                db.add_all([owner, unverified, admin])
                organisation = await db.scalar(select(Plan).where(Plan.key == "organisation"))
                assert organisation is not None
                assert (organisation.monthly_price_paise, organisation.yearly_price_paise) == (
                    1_000_000,
                    10_800_000,
                )
                organisation.status = "active"  # on sale, as on dev
                db.add(
                    Plan(
                        key="fictional_retired",
                        name="Fictional",
                        audience="Fixture",
                        status="retired",
                        monthly_price_paise=100,
                        yearly_price_paise=1_000,
                        revision=1,
                    )
                )
                await db.flush()
                start = organisation.revision
                assert await is_price_owner(db, owner.id) is True
                assert await is_price_owner(db, unverified.id) is False
                assert await is_price_owner(db, admin.id) is False

                plan, before, after = await change_price(
                    db,
                    key="organisation",
                    command=PriceCommand(
                        expected_revision=start, **SEAT, reason="Owner approved ₹1,999 a seat"
                    ),
                    person_id=owner.id,
                    now=NOW,
                )
                assert plan.revision == start + 1
                assert before == {
                    "monthly_price_paise": 1_000_000,
                    "yearly_price_paise": 10_800_000,
                }
                assert after == SEAT

                refusals = [
                    ("organisation", start, SEAT, 409),  # stale revision
                    ("organisation", start + 1, SEAT, 422),  # nothing changed
                    ("nowhere", 1, SEAT, 404),
                    ("fictional_retired", 1, SEAT, 409),
                ]
                for key, expected, prices, status in refusals:
                    with pytest.raises(PriceRefused) as refused:
                        await change_price(
                            db,
                            key=key,
                            command=PriceCommand(
                                expected_revision=expected, **prices, reason="Fictional"
                            ),
                            person_id=owner.id,
                            now=NOW,
                        )
                    assert refused.value.status == status, key

            async with AsyncSession(engine) as db, db.begin():
                # Checkout and /v1/plans read the new price under the new revision.
                copy = await PlansTableCatalogue().plan(db, "organisation")
                assert copy is not None and copy.on_sale
                assert (copy.price("month"), copy.price("year"), copy.revision) == (
                    199_900,
                    1_999_000,
                    start + 1,
                )
                public = await read_public_catalogue(db)
                listed = next(row for row in public.plans if row.key == "organisation")
                assert listed.prices is not None
                assert (listed.prices.monthly_paise, listed.prices.yearly_paise) == (
                    199_900,
                    1_999_000,
                )
                personal = await PlansTableCatalogue().plan(db, "personal")
                assert personal is not None
                assert (personal.price("month"), personal.price("year")) == (249_900, 2_699_000)

                view = await price_view(db, environment="test", can_change=True)
                assert view["environment"] == "test" and view["can_change"] is True
                row = next(item for item in view["plans"] if item["key"] == "organisation")
                assert {name: row[name] for name in SEAT} == SEAT
                assert (row["revision"], row["editable"]) == (start + 1, True)
                retired = next(item for item in view["plans"] if item["key"] == "fictional_retired")
                assert retired["editable"] is False
                assert view["history"][0] == {
                    "plan_key": "organisation",
                    "plan_revision": start + 1,
                    "monthly_price_paise": 199_900,
                    "yearly_price_paise": 1_999_000,
                    "previous_monthly_price_paise": 1_000_000,
                    "previous_yearly_price_paise": 10_800_000,
                    "reason": "Owner approved ₹1,999 a seat",
                    "changed_by": "suyash@authorityclosers.com",
                    "changed_at": NOW.isoformat(),
                }

            async with AsyncSession(engine) as db:
                saved = await db.scalar(
                    select(PlanPriceChange).where(PlanPriceChange.plan_key == "organisation")
                )
                assert saved is not None
                saved.reason = "changed"
                with pytest.raises(PlanPriceHistoryError):
                    await db.flush()
                await db.rollback()
                saved = await db.scalar(
                    select(PlanPriceChange).where(PlanPriceChange.plan_key == "organisation")
                )
                assert saved is not None
                await db.delete(saved)
                with pytest.raises(PlanPriceHistoryError):
                    await db.flush()
        finally:
            await engine.dispose()

    run(exercise())
