from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.db.models import model_metadata
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.organisations.service import (
    OrganisationCommandConflict,
    OrganisationCommandError,
    OrganisationService,
)
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    Tenant,
)


class AsyncSessionAdapter:
    """Run the async service against real SQLite expressions and transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_bind(self) -> Any:
        return self.session.get_bind()

    def add(self, row: Any) -> None:
        self.session.add(row)

    def add_all(self, rows: Any) -> None:
        self.session.add_all(rows)

    async def get(self, model: Any, key: Any) -> Any:
        return self.session.get(model, key)

    async def scalar(self, statement: Any) -> Any:
        return self.session.scalar(statement)

    async def scalars(self, statement: Any) -> Any:
        return self.session.scalars(statement)

    async def execute(self, statement: Any) -> Any:
        return self.session.execute(statement)

    async def flush(self) -> None:
        self.session.flush()


@pytest.fixture
def state() -> Iterator[SimpleNamespace]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection: Any, _record: Any) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    model_metadata().create_all(engine)
    with Session(engine, expire_on_commit=False) as session, session.begin():
        operations_id, public_id = uuid4(), uuid4()
        owner_id, worker_id, unverified_id, inactive_id = (uuid4() for _ in range(4))
        session.add_all(
            [
                Tenant(id=operations_id, slug="ops-test", name="Operations"),
                Tenant(id=public_id, slug="public-test", name="Public"),
                Person(
                    id=owner_id,
                    email="owner@example.test",
                    status=PersonStatus.ACTIVE.value,
                    email_verified_at=datetime.now(UTC),
                ),
                Person(
                    id=worker_id,
                    email="worker@example.test",
                    status=PersonStatus.ACTIVE.value,
                    email_verified_at=datetime.now(UTC),
                ),
                Person(
                    id=unverified_id,
                    email="unverified@example.test",
                    status=PersonStatus.ACTIVE.value,
                ),
                Person(
                    id=inactive_id,
                    email="inactive@example.test",
                    status=PersonStatus.SUSPENDED.value,
                    email_verified_at=datetime.now(UTC),
                ),
            ]
        )
        session.flush()
        adapter = cast(Any, AsyncSessionAdapter(session))
        service = OrganisationService(
            cast(Any, adapter),
            operations_tenant_id=operations_id,
            public_learner_tenant_id=public_id,
        )
        yield SimpleNamespace(
            session=session,
            service=service,
            operations_id=operations_id,
            public_id=public_id,
            owner_id=owner_id,
            worker_id=worker_id,
            unverified_id=unverified_id,
            inactive_id=inactive_id,
            adapter=adapter,
        )
    engine.dispose()


async def create_org(state: SimpleNamespace, *, name: str = "Example Group"):
    return await state.service.create(
        name, state.owner_id, uuid4(), "AUT-438", reason="reviewed setup"
    )


@pytest.mark.asyncio
async def test_create_replay_returns_same_organisation_and_rejects_changed_intent(
    state: SimpleNamespace,
) -> None:
    command_id = uuid4()
    first = await state.service.create(
        "Authority Closers Team", state.owner_id, command_id, "AUT-438", reason="reviewed setup"
    )
    replay = await state.service.create(
        "Authority Closers Team", state.owner_id, command_id, "AUT-438", reason="reviewed setup"
    )
    assert replay.replayed is True
    assert replay.tenant_id == first.tenant_id
    assert replay.slug == first.slug
    organisation = state.session.get(Organisation, first.tenant_id)
    assert organisation is not None
    assert len(organisation.domain_verification_token) >= 43
    assert all(char.isalnum() or char in "_-" for char in organisation.domain_verification_token)
    with pytest.raises(OrganisationCommandConflict, match="different create intent"):
        await state.service.create(
            "Changed Group Name", state.owner_id, command_id, "AUT-438", reason="changed"
        )
    owners = state.session.scalars(
        select(Membership).where(
            Membership.tenant_id == first.tenant_id,
            Membership.role == "owner",
            Membership.status == "active",
        )
    ).all()
    assert len(owners) == 1
    assert (
        state.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == first.tenant_id,
                AuditEvent.request_id == str(command_id),
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_add_member_is_idempotent_verified_and_reactivates_explicitly(
    state: SimpleNamespace,
) -> None:
    organisation = await create_org(state)
    command_id = uuid4()
    added = await state.service.add_member(
        organisation.tenant_id,
        state.worker_id,
        "member",
        command_id,
        operator_reference="AUT-438",
        reason="approved member add",
    )
    replay = await state.service.add_member(
        organisation.tenant_id,
        state.worker_id,
        "member",
        command_id,
        operator_reference="AUT-438",
        reason="approved member add",
    )
    assert added.role == "member" and replay.replayed is True
    with pytest.raises(OrganisationCommandConflict, match="different member intent"):
        await state.service.add_member(
            organisation.tenant_id,
            state.worker_id,
            "admin",
            command_id,
            operator_reference="AUT-438",
        )
    with pytest.raises(OrganisationCommandError, match="verified email"):
        await state.service.add_member(
            organisation.tenant_id, state.unverified_id, "member", uuid4()
        )
    with pytest.raises(OrganisationCommandError, match="active and have a verified email"):
        await state.service.add_member(organisation.tenant_id, state.inactive_id, "member", uuid4())
    with pytest.raises(OrganisationCommandError, match="role must be admin or member"):
        await state.service.add_member(organisation.tenant_id, state.worker_id, "owner", uuid4())
    removed = state.session.get(Membership, (organisation.tenant_id, state.worker_id))
    assert removed is not None
    removed.status = "inactive"
    removed.ended_at = datetime.now(UTC)
    await state.adapter.flush()
    reactivated = await state.service.add_member(
        organisation.tenant_id, state.worker_id, "admin", uuid4()
    )
    assert reactivated.status == "active" and reactivated.role == "admin"
    assert (
        state.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == organisation.tenant_id,
                AuditEvent.request_id == str(command_id),
            )
        )
        == 1
    )


@pytest.mark.asyncio
async def test_domain_settings_are_versioned_audited_and_replay_exactly(
    state: SimpleNamespace,
) -> None:
    organisation = await create_org(state)
    command_id = uuid4()
    first = await state.service.set_domains_attested(
        organisation.tenant_id,
        ["Example.Test", "example.test"],
        True,
        "AUT-438",
        command_id,
        reason="domain attested",
    )
    replay = await state.service.set_domains_attested(
        organisation.tenant_id,
        ["example.test"],
        True,
        "AUT-438",
        command_id,
        reason="domain attested",
    )
    assert first.version == replay.version == 1
    assert replay.replayed is True
    assert first.verified_domains == ("example.test",)
    assert first.proof["example.test"]["method"] == "operator_attested"
    assert (
        state.session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.tenant_id == organisation.tenant_id,
                AuditEvent.request_id == str(command_id),
            )
        )
        == 1
    )
    with pytest.raises(OrganisationCommandConflict, match="different domain intent"):
        await state.service.set_domains_attested(
            organisation.tenant_id, ["example.test"], False, "AUT-438", command_id
        )
    with pytest.raises(OrganisationCommandError, match="freemail"):
        await state.service.set_domains_attested(
            organisation.tenant_id, ["gmail.com"], True, "AUT-438", uuid4()
        )
    latest = await state.service.set_domains_attested(
        organisation.tenant_id, ["example.test"], False, "AUT-438", uuid4()
    )
    assert latest.version == 2 and latest.auto_join is False
    with pytest.raises(RuntimeError, match="append-only"), state.session.begin_nested():
        setting = (
            state.session.query(OrganisationDomainSetting)
            .filter_by(tenant_id=organisation.tenant_id, version=1)
            .one()
        )
        setting.auto_join = False
        state.session.flush()


@pytest.mark.asyncio
async def test_domains_cannot_be_claimed_by_another_organisation_and_protected_tenants_refuse(
    state: SimpleNamespace,
) -> None:
    first = await create_org(state, name="First Group")
    second = await create_org(state, name="Second Group")
    await state.service.set_domains_attested(
        first.tenant_id, ["company.example"], False, "AUT-438", uuid4()
    )
    with pytest.raises(OrganisationCommandError, match="another organisation"):
        await state.service.set_domains_attested(
            second.tenant_id, ["company.example"], False, "AUT-438", uuid4()
        )
    for protected_id in (state.operations_id, state.public_id):
        with pytest.raises(OrganisationCommandError, match="cannot be managed"):
            await state.service.list_members(protected_id)
        with pytest.raises(OrganisationCommandError, match="protected"):
            await state.service.set_domains_attested(protected_id, [], False, "AUT-438", uuid4())
