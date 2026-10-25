"""Migration 0135, each member's profile (user id, title, team, own photo), two new tables:
passes the schema gate, reversible while unused, matches the models, its constraints hold
(one person per user id, lengths, photo type and size), and history in use requires
forward recovery."""

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
from ac_platform.identity.models import Person
from ac_platform.identity.sales_xray_profile_models import PersonPhoto, PersonProfileDetails
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261025_0135_profile_details.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("profile_details_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261025_0135", "20261025_0134")
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
            tables = set(inspect(connection).get_table_names())
            assert not {"person_photos", "person_profile_details"} & tables
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _person(connection: Any) -> Any:
    person_id = uuid4()
    connection.execute(
        Person.__table__.insert().values(
            id=person_id,
            email=f"seller-{person_id.hex}@example.test",
            display_name="Fictional Seller",
            email_verified_at=datetime.now(UTC),
        )
    )
    return person_id


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    details: Any = PersonProfileDetails.__table__
    photos: Any = PersonPhoto.__table__
    now = datetime.now(UTC)
    with postgres_harness.begin() as connection:
        first, second = _person(connection), _person(connection)
        mine = {"handle": "rahul.e", "handle_changed_at": now, "revision": 1, "updated_at": now}
        connection.execute(details.insert().values(person_id=first, **mine))
    # One person per user id.
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(details.insert().values(person_id=second, **mine))
    for wrong in (
        {"handle": "ab"},
        {"handle_changed_at": None},
        {"title": ""},
        {"team": ""},
        {"revision": 0},
    ):
        row = {**mine, "handle": "priya.s", **wrong}
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(details.insert().values(person_id=second, **row))
    photo = {
        "person_id": first,
        "source": "upload",
        "content_type": "image/webp",
        "photo": b"RIFF....WEBP",
        "byte_size": 12,
        "sha256": "a" * 64,
        "revision": 1,
        "updated_at": datetime.now(UTC),
    }
    for wrong in (
        {"source": "google"},
        {"content_type": "image/gif"},
        {"byte_size": 2097153},
        {"sha256": "short"},
    ):
        with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
            connection.execute(photos.insert().values(**{**photo, **wrong}))
    with postgres_harness.begin() as connection:
        connection.execute(photos.insert().values(**photo))
    with (
        postgres_harness.begin() as connection,
        Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        ),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
