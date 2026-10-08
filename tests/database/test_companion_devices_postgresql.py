"""Disposable PostgreSQL proof for companion storage; no native API is activated."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from ac_platform.db.models import (
    companion_credentials as credentials,
)
from ac_platform.db.models import (
    companion_devices as devices,
)
from ac_platform.db.models import (
    companion_pairings as pairings,
)
from ac_platform.db.models import (
    companion_refresh_families as families,
)
from ac_platform.db.models import (
    model_metadata,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as postgres_harness


@pytest.fixture
def binding(postgres_harness: Engine):
    now = datetime.now(UTC)
    tenant, person, device, family = (uuid4() for _ in range(4))
    with Session(postgres_harness) as db, db.begin():
        db.add(Tenant(id=tenant, slug=tenant.hex, name="Companion proof"))
        db.add(Person(id=person, email=f"{person.hex}@example.test"))
        db.flush()
        db.add(Membership(tenant_id=tenant, person_id=person, role="member"))
        db.flush()
        db.execute(
            insert(devices).values(
                id=device,
                tenant_id=tenant,
                person_id=person,
                name="Synthetic device",
                platform="android",
                created_at=now,
            )
        )
        db.execute(
            insert(families).values(
                id=family,
                device_id=device,
                created_at=now,
                idle_expires_at=now + timedelta(days=30),
                absolute_expires_at=now + timedelta(days=90),
            )
        )
    return tenant, person, device, family, now


def test_migration_matches_registry(postgres_harness: Engine) -> None:
    with postgres_harness.connect() as db:
        assert compare_metadata(MigrationContext.configure(db), model_metadata()) == []


@pytest.mark.parametrize("column", ["code_sha256", "poll_secret_sha256"])
def test_pairing_rejects_plaintext_and_overlong_expiry(
    postgres_harness: Engine, column: str
) -> None:
    now = datetime.now(UTC)
    values = dict(
        id=uuid4(),
        name="Synthetic",
        platform="ios",
        state="pending",
        code_sha256=uuid4().hex * 2,
        poll_secret_sha256=uuid4().hex * 2,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )
    with postgres_harness.begin() as db:
        db.execute(insert(pairings).values(**values))
        for invalid, constraint in (
            ({column: "plaintext"}, "code_hash" if column == "code_sha256" else "poll_hash"),
            ({"expires_at": now + timedelta(minutes=11)}, "expiry"),
            ({"state": "approved"}, "state_binding"),
        ):
            unique = {
                "id": uuid4(),
                "code_sha256": uuid4().hex * 2,
                "poll_secret_sha256": uuid4().hex * 2,
            }
            with pytest.raises(DBAPIError) as error, db.begin_nested():
                db.execute(insert(pairings).values(**(values | unique | invalid)))
            assert error.value.orig.diag.constraint_name == "ck_companion_pairings_" + constraint


def test_device_requires_matching_membership_and_family_expiry(
    postgres_harness: Engine, binding
) -> None:
    tenant, person, device, family, now = binding
    with postgres_harness.begin() as db:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                insert(devices).values(
                    id=uuid4(),
                    tenant_id=uuid4(),
                    person_id=person,
                    name="Wrong workspace",
                    platform="android",
                    created_at=now,
                )
            )
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                update(families)
                .where(families.c.id == family)
                .values(absolute_expires_at=now + timedelta(days=91))
            )


@pytest.mark.parametrize(
    "kind,seconds", [("access", 900), ("refresh", 2592000), ("web_session", 60)]
)
def test_credentials_are_hash_only_bounded_and_preserve_spent_history(
    postgres_harness: Engine,
    binding,
    kind: str,
    seconds: int,
) -> None:
    _, _, _, family, now = binding
    first, second = uuid4(), uuid4()
    values = dict(
        id=first,
        family_id=family,
        kind=kind,
        token_sha256=first.hex * 2,
        created_at=now,
        expires_at=now + timedelta(seconds=seconds),
    )
    with postgres_harness.begin() as db:
        for invalid, constraint in (
            ({"token_sha256": "plaintext"}, "token_hash"),
            ({"token_sha256": "G" * 64}, "token_hash"),
            ({"expires_at": now + timedelta(seconds=seconds + 1)}, "kind_expiry"),
        ):
            with pytest.raises(DBAPIError) as error, db.begin_nested():
                db.execute(insert(credentials).values(**(values | invalid)))
            assert error.value.orig.diag.constraint_name == "ck_companion_credentials_" + constraint
        db.execute(insert(credentials).values(**values))
        db.execute(update(credentials).where(credentials.c.id == first).values(consumed_at=now))
        db.execute(
            insert(credentials).values(**(values | {"id": second, "token_sha256": second.hex * 2}))
        )
        for invalid in ({"token_sha256": "f" * 64}, {"consumed_at": None}, {"expires_at": now}):
            with (
                pytest.raises(DBAPIError, match="credential history is immutable"),
                db.begin_nested(),
            ):
                db.execute(update(credentials).where(credentials.c.id == first).values(**invalid))
        assert (
            len(db.execute(select(credentials).where(credentials.c.family_id == family)).all()) == 2
        )


def test_upgrade_preserves_legacy_null_and_is_forward_only(postgres_harness: Engine) -> None:
    path = Path(__file__).parents[2] / "db/migrations/versions/20261008_0078_companion_devices.py"
    spec = importlib.util.spec_from_file_location("companion_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    # Minimal predecessor tables isolate the migration's legacy-row behavior.
    with postgres_harness.connect() as db, db.begin(), db.begin_nested() as transaction:
        schema = "legacy_companion_" + uuid4().hex
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
        db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        db.execute(
            text(
                "CREATE TABLE memberships (tenant_id uuid, person_id uuid, "
                "PRIMARY KEY (tenant_id, person_id))"
            )
        )
        db.execute(text("CREATE TABLE conversation_guest_submissions (marker text)"))
        db.execute(text("INSERT INTO conversation_guest_submissions VALUES ('legacy')"))
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        assert db.execute(
            text("SELECT marker, capture_source FROM conversation_guest_submissions")
        ).one() == ("legacy", None)
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                text("UPDATE conversation_guest_submissions SET capture_source = 'inferred'")
            )
        db.execute(text("UPDATE conversation_guest_submissions SET capture_source = 'chrome_tab'"))
        transaction.rollback()
    with pytest.raises(RuntimeError, match="forward-only"):
        migration.downgrade()
