"""Fresh PostgreSQL proof for the additive username-account schema only."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ac_platform.identity.models import Person
from tests.integration.test_password_identity_http_postgresql import _postgres_url
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


def test_upgrade_preserves_existing_identity_credentials_and_sessions():
    """Exercise the real predecessor, rather than inserting legacy rows after upgrade."""
    import os
    import runpy
    import subprocess
    import sys
    from datetime import timedelta

    from sqlalchemy import MetaData, Table, create_engine, insert, select
    from sqlalchemy.schema import CreateSchema, DropSchema

    from ac_platform.identity.password_auth import hash_password

    root = Path(__file__).parents[2]
    migration = runpy.run_path(
        str(root / "db/migrations/versions/20261010_0081_username_accounts.py")
    )
    base_url = _postgres_url()
    schema = f"username_upgrade_{uuid4().hex}"
    admin_engine = create_engine(base_url)
    engine = create_engine(
        base_url.set(query={**base_url.query, "options": f"-csearch_path={schema}"})
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.casefold().startswith(("ac_", "pg"))
    }
    environment.update(
        AC_DATABASE_URL=base_url.render_as_string(hide_password=False),
        AC_DATABASE_MIGRATOR_URL=base_url.render_as_string(hide_password=False),
        AC_ENVIRONMENT="test",
        PGOPTIONS=f"-csearch_path={schema}",
        PYTHONPATH=str(root / "packages/python"),
    )

    def upgrade(target):
        result = subprocess.run(  # noqa: S603 - fixed local migration in a disposable schema
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
            cwd=root,
            env=environment,
            capture_output=True,
            timeout=180,
            check=False,
        )
        assert result.returncode == 0, "isolated username migration failed"

    created = False
    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        created = True
        upgrade(migration["down_revision"])
        metadata = MetaData()
        tables = {
            name: Table(name, metadata, autoload_with=engine)
            for name in ("persons", "password_credentials", "provider_identities", "sessions")
        }
        now = datetime.now(UTC)
        person_id = uuid4()
        with engine.begin() as connection:
            connection.execute(
                insert(tables["persons"]),
                {
                    "id": person_id,
                    "email": "legacy-upgrade@example.test",
                    "email_verified_at": now,
                    "consent_version": "legacy-reviewed-consent",
                    "consented_at": now,
                    "revision": 7,
                },
            )
            connection.execute(
                insert(tables["password_credentials"]),
                {
                    "id": uuid4(),
                    "person_id": person_id,
                    "password_hash": hash_password("fictional legacy migration password"),
                    "revision": 3,
                },
            )
            connection.execute(
                insert(tables["provider_identities"]),
                {
                    "id": uuid4(),
                    "person_id": person_id,
                    "issuer": "https://provider.test",
                    "subject": "legacy",
                },
            )
            connection.execute(
                insert(tables["sessions"]),
                {
                    "id": uuid4(),
                    "person_id": person_id,
                    "token_hash": b"m" * 32,
                    "created_at": now,
                    "expires_at": now + timedelta(days=1),
                    "revision": 5,
                },
            )
            before = {
                name: connection.execute(select(table)).mappings().all()
                for name, table in tables.items()
            }
        upgrade(migration["revision"])
        with engine.connect() as connection:
            for name, table in tables.items():
                assert connection.execute(select(table)).mappings().all() == before[name]
        with Session(engine) as database:
            person = database.get(Person, person_id)
            assert person.username is None and person.username_verified_at is None
            assert person.password_change_required is False
            assert person.temporary_password_expires_at is None
    finally:
        engine.dispose()
        if created:
            with admin_engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
        admin_engine.dispose()
