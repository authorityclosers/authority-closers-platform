"""Fresh PostgreSQL proof for the additive username-account schema only."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ac_platform.identity.models import Person
from tests.integration.test_password_identity_http_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


def test_migration_defaults_preserve_legacy_email_and_enforce_new_bindings(postgres_harness):
    from sqlalchemy import inspect
    from sqlalchemy.exc import IntegrityError

    columns = {row["name"]: row for row in inspect(postgres_harness.engine).get_columns("persons")}
    for field in (
        "username",
        "username_verified_at",
        "password_change_required",
        "temporary_password_expires_at",
    ):
        assert field in columns
    assert not columns["password_change_required"]["nullable"]
    with Session(postgres_harness.engine) as db, db.begin():
        original_email, original_proof = uuid4().hex + "@legacy.test", datetime.now(UTC)
        legacy = Person(id=uuid4(), email=original_email, email_verified_at=original_proof)
        db.add(legacy)
        db.flush()
        db.refresh(legacy)
        assert legacy.username is None and not legacy.password_change_required
        assert legacy.email == original_email and legacy.email_verified_at == original_proof
        username = "migration." + uuid4().hex
        db.add(Person(id=uuid4(), username=username))
        db.flush()
        for fields in (
            {"username": username},
            {"username_verified_at": original_proof},
            {"username": "pending." + uuid4().hex, "password_change_required": True},
        ):
            with pytest.raises(IntegrityError), db.begin_nested():
                db.add(Person(id=uuid4(), **fields))
                db.flush()


def test_username_migration_is_classified_additive_without_runtime_helpers():
    import runpy

    root = Path(__file__).parents[2]
    classifier = runpy.run_path(str(root / "scripts/ops/migration_safety.py"))
    path = root / "db/migrations/versions/20261010_0081_username_accounts.py"
    assert classifier["classify_source"](path.read_text(), str(path)).verdict == "additive"
