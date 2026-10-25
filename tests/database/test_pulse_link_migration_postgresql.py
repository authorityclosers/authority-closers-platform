"""Migration 0139 (Pulse: profiles, org links and directory, recordings from apps): it
passes the schema gate, is reversible while unused, matches the models, its constraints
hold (one open link per organisation, one organisation per Pulse org, a pending attempt
carries its sealed verifier, an imported upload names its call), and history in use
requires forward recovery."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person
from ac_platform.pulse.models import AppCallUpload, PulseOrgLink
from ac_platform.tenancy.models import Tenant
from tests.database.conversation_harness import conversation_harness

ROOT = Path(__file__).resolve().parents[2]
PULSE = ("20261026_0139", "20261025_0137", "20261026_0139_pulse_link.py")
TABLES = ("person_pulse_profiles", "pulse_org_links", "pulse_org_members", "app_call_uploads")


@pytest.fixture(scope="module")
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def migration(file: str) -> Any:
    path = ROOT / "db/migrations/versions" / file
    spec = importlib.util.spec_from_file_location(file.removesuffix(".py"), path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_chain_and_schema_gate_rules() -> None:
    from scripts.ci.migration_schema_gate import check_operations
    from scripts.ops.migration_safety import classify_source

    revision, down, file = PULSE
    module = migration(file)
    assert (module.revision, module.down_revision) == (revision, down)
    path = Path(module.__file__)
    check_operations([classify_source(path.read_text(), str(path))], set())


def test_unused_migration_downgrades_reupgrades_and_matches_the_models(
    postgres_harness: Engine,
) -> None:
    module = migration(PULSE[2])
    with postgres_harness.begin() as connection:
        context = MigrationContext.configure(connection, opts={"target_metadata": model_metadata()})
        with Operations.context(context):
            module.downgrade()
            assert not set(TABLES) & set(inspect(connection).get_table_names())
            module.upgrade()
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []


def _link(tenant_id: Any, person_id: Any, **over: Any) -> PulseOrgLink:
    now = datetime.now(UTC)
    values: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "issuer": "https://pulse.example.test",
        "status": "active",
        "pulse_org_id": "org-1",
        "scopes": ["openid", "pulse.org.read"],
        "sharing": {},
        "seal_key_id": "0123456789abcdef",
        "sealed_refresh_token": "v1.sealed",
        "started_by_person_id": person_id,
        "started_at": now,
        "linked_at": now,
        "last_sync": {},
    }
    values.update(over)
    return PulseOrgLink(**values)


def test_constraints_hold_and_history_requires_forward_recovery(
    postgres_harness: Engine,
) -> None:
    tenant_id, other_tenant, person_id = uuid4(), uuid4(), uuid4()
    with Session(postgres_harness) as db, db.begin():
        db.add_all(
            [
                Tenant(id=tenant_id, slug=tenant_id.hex, name="Fictional Realty"),
                Tenant(id=other_tenant, slug=other_tenant.hex, name="Fictional Other"),
                Person(
                    id=person_id,
                    email=f"owner-{person_id.hex}@example.test",
                    display_name="Fictional Owner",
                    email_verified_at=datetime.now(UTC),
                ),
            ]
        )
        db.flush()
        db.add(_link(tenant_id, person_id))
    wrong_rows = (
        # A second open link for the same organisation.
        {"pulse_org_id": "org-2"},
        # The same Pulse org linked to another organisation.
        {"tenant_id": other_tenant},
        # Active without its keys.
        {"tenant_id": other_tenant, "pulse_org_id": "org-3", "sealed_refresh_token": None},
        # A pending attempt without its sealed verifier.
        {
            "tenant_id": other_tenant,
            "status": "pending",
            "pulse_org_id": None,
            "state_sha256": "a" * 64,
            "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        },
        {"tenant_id": other_tenant, "pulse_org_id": "org-4", "status": "linked"},
    )
    for wrong in wrong_rows:
        with pytest.raises(IntegrityError), Session(postgres_harness) as db, db.begin():
            db.add(_link(wrong.pop("tenant_id", tenant_id), person_id, **wrong))
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError), Session(postgres_harness) as db, db.begin():
        db.add(
            AppCallUpload(
                id=uuid4(),
                tenant_id=tenant_id,
                person_id=person_id,
                grant_id=uuid4(),
                app_label="Pulse",
                external_id="call-1",
                source_sha256="b" * 64,
                byte_size=10,
                media_type="audio/mpeg",
                file_name="call.mp3",
                consent="participants-informed",
                state="imported",  # an imported upload must name its call
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
    module = migration(PULSE[2])
    with (
        pytest.raises(RuntimeError, match="forward recovery"),
        postgres_harness.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        module.downgrade()
