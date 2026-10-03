"""Disposable PostgreSQL 0065→0066→head proof for the explicit platform billing capability.

Existing grants and revocations survive the widening; only a platform-scope
``platform_billing_manage`` grant becomes valid; other scopes and unknown names stay
refused; history stays immutable; model and installed checks agree; forward-only.
"""

from __future__ import annotations

import os
import re
import runpy
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from ac_platform.authorization.models import (
    PLATFORM_CAPABILITIES,
    SUPPORTED_CAPABILITIES,
    CapabilityGrant,
    CapabilityRevocation,
)
from ac_platform.db.models import model_metadata
from tests.database.test_capability_grants import Scope, audit, grant, seed_scope
from tests.database.test_conversation_postgresql import _migration_head

ROOT = Path(__file__).parents[2]
MIGRATION = ROOT / "db/migrations/versions/20261002_0066_platform_billing_manage.py"
PRIOR, REVISION, BILLING = "20261002_0065", "20261002_0066", "platform_billing_manage"
HEAD = _migration_head()
# PostgreSQL reports whichever permission check it evaluates first.
PERMISSION_CHECK = "ck_capability_grants_permission_(supported|scope)"


def _platform(database: Session, scope: Scope, permission: str) -> CapabilityGrant:
    return grant(
        database,
        scope,
        permission=permission,
        scope_kind="platform",
        tenant_id=None,
        program_id=None,
    )


@pytest.fixture(scope="module")
def upgraded() -> Iterator[tuple[Engine, Scope, dict, UUID]]:
    raw = os.getenv("AC_CAPABILITY_POSTGRES_TEST_URL") or os.getenv("AC_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("disposable capability PostgreSQL URL is not configured")
    url = make_url(raw).set(drivername="postgresql+psycopg")
    if url.host not in {None, "127.0.0.1", "localhost", "::1"}:
        pytest.skip("refusing to mutate a non-local PostgreSQL database")
    schema = f"billing_capability_{uuid4().hex}"
    engine = create_engine(url.set(query={**url.query, "options": f"-csearch_path={schema}"}))
    with engine.begin() as connection:
        connection.execute(CreateSchema(schema))
    environment = os.environ | {
        "AC_DATABASE_URL": url.render_as_string(hide_password=False),
        "AC_DATABASE_MIGRATOR_URL": url.render_as_string(hide_password=False),
        "AC_ENVIRONMENT": "test",
        "PGOPTIONS": f"-csearch_path={schema}",
        "PYTHONPATH": str(ROOT / "packages/python"),
    }

    def migrate(target: str) -> None:
        result = subprocess.run(  # noqa: S603 - fixed local Alembic invocation
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", target],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, f"isolated PostgreSQL migration to {target} failed"

    try:
        migrate(PRIOR)
        with Session(engine) as database:
            scope = seed_scope(database)
            rows = [_platform(database, scope, "platform_release_manage"), grant(database, scope)]
            database.add_all(rows)
            database.flush()
            revocation = CapabilityRevocation(
                id=uuid4(),
                grant_id=rows[1].id,
                revoked_by_person_id=scope.actor,
                audit_event_id=audit(database, scope),
                reason="Fictional earlier removal",
            )
            database.add(revocation)
            database.commit()
            revocation_id = revocation.id
            snapshot = {row.id: (row.permission, row.scope_kind, row.tenant_id) for row in rows}
            database.add(_platform(database, scope, BILLING))
            with pytest.raises(IntegrityError, match=PERMISSION_CHECK):
                database.flush()
        migrate("head")
        yield engine, scope, snapshot, revocation_id
    finally:
        # Only this test-created, random exact schema is removed.
        with engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_0066_applies_under_the_head_and_preserves_grants_and_revocations(upgraded) -> None:
    engine, scope, snapshot, revocation_id = upgraded
    with Session(engine) as database:
        assert database.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        rows = database.scalars(
            select(CapabilityGrant).where(CapabilityGrant.subject_person_id == scope.subject)
        ).all()
        assert {row.id: (row.permission, row.scope_kind, row.tenant_id) for row in rows} == snapshot
        revocation = database.get(CapabilityRevocation, revocation_id)
        assert revocation is not None and revocation.grant_id in snapshot


def test_exact_platform_billing_grant_is_accepted(upgraded) -> None:
    engine, scope, *_ = upgraded
    with Session(engine) as database:
        row = _platform(database, scope, BILLING)
        database.add(row)
        database.commit()
        assert database.get(CapabilityGrant, row.id).scope_kind == "platform"


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"permission": BILLING}, "ck_capability_grants_permission_scope"),
        (
            {"permission": BILLING, "scope_kind": "tenant", "program_id": None},
            "ck_capability_grants_permission_scope",
        ),
        ({"permission": "platform_billing_read", "scope_kind": "platform"}, PERMISSION_CHECK),
        ({"permission": "billing_manage"}, PERMISSION_CHECK),
    ],
)
def test_other_scopes_and_unknown_names_are_refused(upgraded, changes, constraint) -> None:
    engine, scope, *_ = upgraded
    with Session(engine) as database:
        if changes.get("scope_kind") == "platform":
            changes = changes | {"tenant_id": None, "program_id": None}
        database.add(grant(database, scope, **changes))
        with pytest.raises(IntegrityError, match=constraint):
            database.flush()


def test_history_stays_immutable_after_widening(upgraded) -> None:
    engine, _scope, snapshot, _revocation = upgraded
    table = model_metadata().tables["capability_grants"]
    with pytest.raises(DBAPIError, match="capability history is immutable"), engine.begin() as db:
        db.execute(update(table).where(table.c.id == next(iter(snapshot))).values(reason="x"))


def test_installed_checks_match_the_model_registry(upgraded) -> None:
    with upgraded[0].connect() as connection:
        drift = compare_metadata(MigrationContext.configure(connection), model_metadata())
        checks = dict(
            connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'capability_grants'::regclass AND contype = 'c'"
                )
            ).all()
        )
    assert [entry for entry in drift if "capability_" in repr(entry)] == []
    names = re.compile(r"'([a-z_]+)'::")
    assert set(names.findall(checks["ck_capability_grants_permission_supported"])) == (
        SUPPORTED_CAPABILITIES
    )
    platform = checks["ck_capability_grants_permission_scope"].split("'platform'::", 1)[1]
    assert set(names.findall(platform.split("'tenant'::", 1)[0])) == PLATFORM_CAPABILITIES


def test_migration_0066_is_linked_and_forward_only() -> None:
    migration = runpy.run_path(str(MIGRATION))
    assert (migration["revision"], migration["down_revision"]) == (REVISION, PRIOR)
    with pytest.raises(RuntimeError, match="forward-only"):
        migration["downgrade"]()
    assert "INSERT" not in MIGRATION.read_text(encoding="utf-8").upper()
