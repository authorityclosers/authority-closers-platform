"""Prepared isolation checks; use only the launcher's disposable lane database."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.schema import CreateSchema

from tests.database import postgres_templates as TEMPLATES


@pytest.mark.parametrize(
    "raw",
    [
        "invalid",
        "sqlite://",
        "postgresql://example.com/test",
        "postgresql://localhost/test?host=example.com",
        "postgresql://localhost/test?hostaddr=203.0.113.1",
        "postgresql://localhost/test?service=production",
        "postgresql://localhost/test?servicefile=/tmp/service",
        "postgresql://localhost",
    ],
)
def test_remote_or_implicit_database_routes_are_rejected(raw: str) -> None:
    with pytest.raises(TEMPLATES.TemplateError):
        TEMPLATES.disposable_url(raw)


@pytest.mark.parametrize(
    "name", ["production", 'ac_pytest_x"; DROP DATABASE production', "ac_pytest_"]
)
def test_cleanup_identifiers_cannot_escape_owned_namespace(name: str) -> None:
    with pytest.raises(TEMPLATES.TemplateError):
        TEMPLATES.quoted_database(name)


def test_migration_content_changes_invalidate_same_revision(tmp_path: Path) -> None:
    root = tmp_path
    (root / "alembic.ini").write_text("[alembic]\n")
    versions = root / "db/migrations/versions"
    versions.mkdir(parents=True)
    migration = versions / "same_head.py"
    migration.write_text("revision = 'head'\n")
    initial = TEMPLATES.migration_fingerprint(root)
    assert TEMPLATES.migration_fingerprint(root) == initial
    migration.write_text("revision = 'head'\n# schema repair\n")
    assert TEMPLATES.migration_fingerprint(root) != initial


def test_database_clones_preserve_seed_and_functions_without_sharing_mutations() -> None:
    raw = os.environ.get("AC_TEST_DATABASE_URL")
    assert raw, "The disposable lane database URL is required"
    calls = []

    def initialize(url, schema):
        calls.append(schema)
        engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
        try:
            with engine.begin() as connection:
                connection.execute(CreateSchema(schema))
                connection.exec_driver_sql(f'SET LOCAL search_path = "{schema}"')
                connection.exec_driver_sql(
                    "CREATE TABLE clone_probe (id integer PRIMARY KEY, value text)"
                )
                connection.exec_driver_sql("INSERT INTO clone_probe VALUES (1, 'original')")
                connection.exec_driver_sql(
                    f"CREATE FUNCTION read_probe() RETURNS text LANGUAGE sql AS "  # noqa: S608 - UUID schema owned by test
                    f"'SELECT value FROM \"{schema}\".clone_probe WHERE id = 1'"
                )
        finally:
            engine.dispose()

    pool = TEMPLATES.PostgresTemplatePool(raw, initialize)
    names = []
    try:
        for value in ("first mutation", "second mutation"):
            with pool.clone("a" * 64) as engine:
                names.append(engine.url.database)
                with engine.begin() as connection:
                    assert connection.scalar(text("SELECT read_probe()")) == "original"
                    connection.execute(
                        text("UPDATE clone_probe SET value = :value"), {"value": value}
                    )
                    assert connection.scalar(text("SELECT read_probe()")) == value
            assert len(pool.owned) == 1  # only the unused template survives
        assert len(calls) == 1
        assert len(set(names)) == 2
        assert pool.url.database not in pool.owned
        with pytest.raises(TEMPLATES.TemplateError, match="unowned"):
            pool._drop(pool.url.database)
        pool.template("b" * 64)
        assert len(calls) == 2
        names.extend(pool.owned)
    finally:
        pool.close()
    assert pool.closed and not pool.owned
    pool.close()
    admin = create_engine(TEMPLATES.disposable_url(raw), poolclass=NullPool, hide_parameters=True)
    try:
        with admin.connect() as connection:
            for name in names:
                assert (
                    connection.scalar(
                        text("SELECT count(*) FROM pg_database WHERE datname = :name"),
                        {"name": name},
                    )
                    == 0
                )
    finally:
        admin.dispose()


@pytest.mark.parametrize("failure", [RuntimeError, pytest.fail.Exception, KeyboardInterrupt])
def test_failed_initializer_drops_only_its_new_template(failure) -> None:
    raw = os.environ.get("AC_TEST_DATABASE_URL")
    assert raw, "The disposable lane database URL is required"

    def initialize(url, schema):
        raise failure("synthetic initialization failure")

    pool = TEMPLATES.PostgresTemplatePool(raw, initialize)
    try:
        with pytest.raises(failure, match="synthetic initialization failure"):
            pool.template("a" * 64)
        assert not pool.owned and not pool.templates
    finally:
        pool.close()
