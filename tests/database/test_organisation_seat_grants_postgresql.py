"""Complimentary organisation seats on PostgreSQL (owner, 30 Oct 2026: founding clients get
seats without paying).

Migration 0144 passes the schema gate and rolls back only while no grant was recorded. A grant
counts toward the organisation's seats until the end of its last IST day; a change or an end
supersedes it once; the database refuses a zero grant that ends nothing, a second supersession
and a blank reason even past the ORM. Disposable loopback PostgreSQL, fictional people.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.identity.models import Person
from ac_platform.organisations.seat_grants import (
    GrantCommand,
    complimentary_seats,
    grant_history,
    is_seat_owner,
    record_grant,
    seat_day,
)
from ac_platform.organisations.usage import organisation_seats
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from ac_platform.tenancy.seat_grant_models import OrganisationSeatGrant, SeatGrantHistoryError
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run

ROOT = Path(__file__).resolve().parents[2]
REVISION, DOWN = "20261030_0144", "20261029_0143"
FILE = "20261030_0144_organisation_seat_grants.py"


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def migration() -> Any:
    path = ROOT / "db/migrations/versions" / FILE
    spec = importlib.util.spec_from_file_location("organisation_seat_grants_migration", path)
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
    calls: list[str] = []
    module.op = SimpleNamespace(
        execute=lambda statement: calls.append("lock"),
        get_bind=lambda: SimpleNamespace(scalar=lambda statement: True),
        drop_index=lambda name, table_name: calls.append(f"drop {name}"),
        drop_table=lambda name: calls.append(f"drop {name}"),
    )
    with pytest.raises(RuntimeError, match="history requires forward recovery"):
        module.downgrade()
    assert calls == ["lock"]
    calls.clear()
    module.op.get_bind = lambda: SimpleNamespace(scalar=lambda statement: False)
    module.downgrade()
    assert calls == [
        "lock",
        "drop ix_organisation_seat_grants_tenant_id",
        "drop organisation_seat_grants",
    ]


def test_grants_count_supersede_once_and_stay_append_only(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            now = datetime.now(UTC)
            # Plain ids: a committed session expires its objects.
            owner_id, tenant_id = uuid4(), uuid4()
            owner = Person(id=owner_id, email="suyash@authorityclosers.com", email_verified_at=now)
            org_owner = Person(
                id=uuid4(), email=f"org-{uuid4().hex[:8]}@example.test", email_verified_at=now
            )
            async with AsyncSession(engine) as db, db.begin():
                db.add_all([owner, org_owner])
                db.add(Tenant(id=tenant_id, slug=f"seats-{tenant_id.hex}", name="Seat Fixture"))
                await db.flush()
                db.add(
                    Organisation(
                        tenant_id=tenant_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="f" * 43,
                    )
                )
                db.add(Membership(tenant_id=tenant_id, person_id=org_owner.id, role="owner"))
                await db.flush()
                assert await is_seat_owner(db, owner.id) is True
                assert await is_seat_owner(db, org_owner.id) is False

                last = seat_day(now) + timedelta(days=90)
                first, _ = await record_grant(
                    db,
                    tenant_id=tenant_id,
                    command=GrantCommand(seats=4, until=last, reason="Founding client"),
                    person_id=owner.id,
                    now=now,
                )
                seats = await organisation_seats(db, tenant_id)
                assert (seats["complimentary_seats"], seats["seats_available"]) == (4, 3)
                later = now + timedelta(seconds=1)
                changed, replaced = await record_grant(
                    db,
                    tenant_id=tenant_id,
                    command=GrantCommand(
                        seats=6, until=last, reason="Two more", supersedes_grant_id=first.id
                    ),
                    person_id=owner.id,
                    now=later,
                )
                assert replaced is not None and replaced.id == first.id
                assert await complimentary_seats(db, tenant_id, later) == 6
                assert await complimentary_seats(db, tenant_id, now) == 4
                history = await grant_history(db, tenant_id)
                assert [row["kind"] for row in history] == ["change", "grant"]
                assert history[0]["until"] == last.isoformat()
                first_id, changed_id = first.id, changed.id

            # The database itself refuses rows the ORM rules also refuse.
            refused = [
                dict(seats=0, supersedes_grant_id=None, reason="Ends nothing"),
                dict(seats=2, supersedes_grant_id=first_id, reason="Second change"),
                dict(seats=2, supersedes_grant_id=None, reason="  "),
                dict(seats=501, supersedes_grant_id=None, reason="Too many"),
            ]
            for values in refused:
                async with AsyncSession(engine) as db:
                    with pytest.raises(IntegrityError):
                        await db.execute(
                            insert(OrganisationSeatGrant).values(
                                id=uuid4(),
                                tenant_id=tenant_id,
                                valid_from=now,
                                valid_until=now + timedelta(days=1),
                                granted_by_person_id=owner_id,
                                created_at=now,
                                **values,
                            )
                        )
                    await db.rollback()

            async with AsyncSession(engine) as db:
                saved = await db.get(OrganisationSeatGrant, changed_id)
                assert saved is not None
                saved.seats = 60
                with pytest.raises(SeatGrantHistoryError):
                    await db.flush()
                await db.rollback()
                saved = await db.get(OrganisationSeatGrant, changed_id)
                assert saved is not None
                await db.delete(saved)
                with pytest.raises(SeatGrantHistoryError):
                    await db.flush()
        finally:
            await engine.dispose()

    run(exercise())
