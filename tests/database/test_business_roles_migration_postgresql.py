"""Migration 0136, business roles (Sales manager, Viewer, Finance): passes the schema gate,
reversible while unused and back to the exact 0054 checks, the widened checks take the new
roles and still refuse unknown ones, and history in use requires forward recovery."""

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
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
FILE = "20261025_0136_business_roles.py"


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("business_roles_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checks(connection: Any) -> dict[str, str]:
    rows = connection.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname IN ('ck_memberships_role_supported',"
            " 'ck_organisation_invites_role_supported')"
        )
    )
    return dict(rows.all())


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    module = migration()
    assert (module.revision, module.down_revision) == ("20261025_0136", "20261025_0135")
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
            before = _checks(connection)
            assert "'viewer'" not in before["ck_memberships_role_supported"]
            assert "'member'" in before["ck_organisation_invites_role_supported"]
            module.upgrade()
            after = _checks(connection)
            for role in ("manager", "viewer", "finance"):
                assert all(f"'{role}'" in check for check in after.values())
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def test_new_roles_are_taken_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    memberships: Any = Membership.__table__
    with postgres_harness.begin() as connection:
        tenant, person = uuid4(), uuid4()
        connection.execute(
            Tenant.__table__.insert().values(
                id=tenant, name="Fictional Homes", slug=f"fictional-{tenant.hex[:8]}"
            )
        )
        connection.execute(
            Person.__table__.insert().values(
                id=person,
                email=f"viewer-{person.hex}@example.test",
                email_verified_at=datetime.now(UTC),
            )
        )
        connection.execute(
            memberships.insert().values(tenant_id=tenant, person_id=person, role="viewer")
        )
    with pytest.raises(IntegrityError), postgres_harness.begin() as connection:
        connection.execute(
            memberships.update().where(memberships.c.person_id == person).values(role="auditor")
        )
    with (
        postgres_harness.begin() as connection,
        Operations.context(
            MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        ),
        pytest.raises(RuntimeError, match="forward recovery"),
    ):
        migration().downgrade()
