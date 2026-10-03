"""C3: approved inactive values, exact seed preconditions and transactional rollback."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, MetaData, Table, create_engine, inspect, or_, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).parents[2]
PREVIOUS = "20261002_0067"
REVISION = "20261003_0068"
ERROR = "inactive catalogue seed changed; review required"


@dataclass(frozen=True)
class CatalogueProof:
    engine: Engine
    environment: dict[str, str] = field(repr=False)

    def migrate(self, target: str, *, rejected: bool = False) -> None:
        result = subprocess.run(  # noqa: S603 - fixed local command, disposable schema only
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
            cwd=ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        # Never echo environment, driver output or credentials on failure.
        exit_code = result.returncode
        assert exit_code == (1 if rejected else 0), "unexpected migration exit code"
        if rejected:
            matched = ERROR in result.stderr
            assert matched, "missing seed review error"


@contextmanager
def catalogue_schema(target: str = PREVIOUS) -> Iterator[CatalogueProof]:
    raw = os.getenv("AC_CONVERSATION_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.fail("an explicit disposable loopback PostgreSQL URL is required", pytrace=False)
    try:
        url = make_url(raw)
    except Exception:
        pytest.fail("invalid disposable PostgreSQL URL; value hidden", pytrace=False)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("catalogue proof refuses non-loopback PostgreSQL", pytrace=False)
    if any(key.lower() in {"host", "hostaddr", "service", "servicefile"} for key in url.query):
        pytest.fail("alternate database routing is forbidden", pytrace=False)
    url = url.set(drivername="postgresql+psycopg")
    schema = "catalogue_proof_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    scoped = None
    created = False
    try:
        with admin.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        options = f"-csearch_path={schema} -clock_timeout=10000 -cstatement_timeout=30000"
        scoped = create_engine(
            url.set(query={**url.query, "options": options}), hide_parameters=True
        )
        proof = CatalogueProof(
            scoped,
            {
                **os.environ,
                "AC_DATABASE_URL": url.render_as_string(hide_password=False),
                "AC_DATABASE_MIGRATOR_URL": url.render_as_string(hide_password=False),
                "AC_ENVIRONMENT": "test",
                "PGOPTIONS": options,
                "PYTHONPATH": str(ROOT / "packages/python"),
            },
        )
        proof.migrate(target)
        yield proof
    finally:
        if scoped is not None:
            scoped.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin.dispose()


def _rows(engine: Engine) -> list[dict]:
    plans = Table("plans", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        return [
            dict(row) for row in connection.execute(select(plans).order_by(plans.c.key)).mappings()
        ]


@pytest.fixture(scope="module")
def prior_catalogue() -> Iterator[CatalogueProof]:
    with catalogue_schema() as proof:
        yield proof


def test_confirmed_values_preserve_inactivity_identity_and_unrelated_rows() -> None:
    with catalogue_schema() as proof:
        before = _rows(proof.engine)
        assert {row["revision"] for row in before} == {1}
        plans = Table("plans", MetaData(), autoload_with=proof.engine)
        with proof.engine.begin() as connection:
            connection.execute(
                plans.insert().values(
                    id=uuid4(),
                    key="fictional_draft",
                    name="Fictional",
                    audience="Fixture",
                    status="draft",
                    feature_keys=[],
                    top_up_packs=[],
                    sort_order=99,
                    revision=1,
                )
            )
        unrelated = next(row for row in _rows(proof.engine) if row["key"] == "fictional_draft")
        proof.migrate(REVISION)
        after = {row["key"]: row for row in _rows(proof.engine)}
        expected = {
            "personal": (249900, 2699000, True, 800, 1, 1, False, 90, [], "topup_100", 100, 29900),
            "organisation": (
                1000000,
                10800000,
                False,
                1000,
                2,
                49,
                True,
                90,
                [],
                "topup_500",
                500,
                129900,
            ),
            "enterprise": (
                1000000,
                10800000,
                False,
                1000,
                50,
                None,
                True,
                120,
                ["long_calls_120", "priority_support", "onboarding_session"],
                "topup_500",
                500,
                129900,
            ),
        }
        fields = (
            "monthly_price_paise",
            "yearly_price_paise",
            "prices_include_gst",
            "included_minutes",
            "seat_min",
            "seat_max",
            "per_seat",
            "longest_call_minutes",
            "feature_keys",
        )
        for old in before:
            row = after[old["key"]]
            values = expected[old["key"]]
            assert tuple(row[field] for field in fields) == values[:9]
            assert (row["status"], row["revision"]) == ("coming_soon", 2)
            for field in (
                "id",
                "key",
                "name",
                "audience",
                "sort_order",
                "created_at",
                "retention_days",
                "rollover_months",
                "monthly_price_cents",
                "yearly_price_cents",
            ):
                assert row[field] == old[field]
            assert row["updated_at"] >= old["updated_at"]
            assert row["top_up_packs"] == [
                {
                    "key": values[9],
                    "minutes": values[10],
                    "price_paise": values[11],
                    "price_cents": None,
                    "validity_rule": "billing_year_end",
                }
            ]
        assert after["fictional_draft"] == {**unrelated, "prices_include_gst": False}
        with proof.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
        column = next(
            col
            for col in inspect(proof.engine).get_columns("plans")
            if col["name"] == "prices_include_gst"
        )
        assert column["nullable"] is False and column["default"] == "false"


@pytest.mark.parametrize(
    "change",
    [
        {"revision": 2},
        {"status": "active"},
        {"name": "Edited"},
        {"audience": "Edited"},
        {"sort_order": 11},
        {"per_seat": True},
        {"monthly_price_paise": 1},
        {"yearly_price_paise": 1},
        {"monthly_price_cents": 1},
        {"yearly_price_cents": 1},
        {"included_minutes": 1},
        {"seat_min": 1},
        {"seat_max": 1},
        {"longest_call_minutes": 1},
        {"retention_days": 1},
        {"rollover_months": 1},
        {"feature_keys": ["edited"]},
        {"top_up_packs": [{"edited": True}]},
        {"key": "edited"},
        {"id": uuid4()},
        None,
    ],
)
def test_changed_or_missing_seed_rejects_and_rolls_back(
    prior_catalogue: CatalogueProof, change: dict | None
) -> None:
    proof = prior_catalogue
    plans = Table("plans", MetaData(), autoload_with=proof.engine)
    seed = next(row for row in _rows(proof.engine) if row["key"] == "enterprise")
    try:
        with proof.engine.begin() as connection:
            statement = plans.delete() if change is None else plans.update().values(**change)
            # Last seed: a bad Enterprise row must leave Personal/Organisation untouched.
            connection.execute(statement.where(plans.c.key == "enterprise"))
        before = _rows(proof.engine)
        proof.migrate(REVISION, rejected=True)
        assert _rows(proof.engine) == before
        assert "prices_include_gst" not in {
            col["name"] for col in inspect(proof.engine).get_columns("plans")
        }
        with proof.engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PREVIOUS
    finally:
        # Restore only this fictional seed so rejection vectors share one migrated schema.
        with proof.engine.begin() as connection:
            connection.execute(
                plans.delete().where(or_(plans.c.id == seed["id"], plans.c.key == "enterprise"))
            )
            connection.execute(plans.insert().values(**seed))


def test_c3_migration_is_forward_only() -> None:
    spec = importlib.util.spec_from_file_location(
        "inactive_plan_values",
        ROOT / "db/migrations/versions/20261003_0068_inactive_plan_values.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS
    with pytest.raises(RuntimeError, match="forward-only"):
        module.downgrade()
