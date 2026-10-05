"""Processing identities never appear as people or accept member-management writes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.identity.models import Person
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_organisation import call as organisation_call
from tests.unit.http.test_organisation import state as organisation_state  # noqa: F401
from tests.unit.http.test_organisation_domains import call as domains_call
from tests.unit.http.test_organisation_domains import state as domains_state  # noqa: F401
from tests.unit.http.test_platform_organisations import MANAGE, READ, grant
from tests.unit.http.test_platform_organisations import call as platform_call
from tests.unit.http.test_platform_organisations import state as platform_state  # noqa: F401
from tests.unit.http.test_workspaces import (
    HttpDatabase,
    workspace_state,  # noqa: F401
)


@pytest.fixture
def selected_state(request, surface):
    return request.getfixturevalue(f"{surface}_state")


def add_processing_identity(state):
    person_id = uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(
            Person(
                id=person_id,
                email="processing@example.test",
                email_verified_at=datetime.now(UTC),
            )
        )
        db.flush()
        db.add(Membership(tenant_id=state.tenant, person_id=person_id, role="processing"))
    return person_id


async def test_service_directory_excludes_processing_identity(organisation_state):  # noqa: F811
    state = organisation_state
    processing = add_processing_identity(state)
    with Session(state.engine) as db:
        service = OrganisationService(
            HttpDatabase(db),
            operations_tenant_id=state.settings.operations_tenant_id,
            public_learner_tenant_id=state.settings.public_learner_tenant_id,
        )
        members = await service.list_members(state.tenant)
    assert {member.person_id for member in members} == {state.person, state.other, state.member}
    assert processing not in {member.person_id for member in members}


@pytest.mark.parametrize("surface", ["organisation", "domains", "platform"])
async def test_directory_and_counts_exclude_processing_identity(selected_state, surface):
    state = selected_state
    processing = add_processing_identity(state)
    if surface == "platform":
        await grant(state, READ)
        response = await platform_call(state)
        assert response.status_code == 200
        organisation = next(
            row for row in response.json()["organisations"] if row["tenant_id"] == str(state.tenant)
        )
        directory = await platform_call(state, path=f"/{state.tenant}/members")
        humans = {state.owner, state.admin, state.member}
    else:
        if surface == "domains":
            response = await domains_call(
                state,
                "PUT",
                "/domains",
                body={"verified_domains": [], "auto_join": False},
                key=uuid4(),
            )
        else:
            response = await organisation_call(state)
        assert response.status_code == 200
        organisation = response.json()
        directory = await organisation_call(state, path="/members")
        humans = {state.person, state.other, state.member}
    assert organisation["member_count"] == 3
    assert directory.status_code == 200
    assert {row["person_id"] for row in directory.json()["members"]} == {
        str(person) for person in humans
    }
    assert str(processing) not in {row["person_id"] for row in directory.json()["members"]}


def membership_snapshot(state):
    with Session(state.engine) as db:
        memberships = {
            row.person_id: (row.role, row.status, row.ended_at, row.revision)
            for row in db.scalars(select(Membership).where(Membership.tenant_id == state.tenant))
        }
        audits = db.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == state.tenant)
        )
        return memberships, audits


@pytest.mark.parametrize("surface", ["organisation", "platform"])
@pytest.mark.parametrize("action", ["role", "remove", "transfer"])
async def test_processing_identity_refuses_member_management(selected_state, surface, action):
    state = selected_state
    processing = add_processing_identity(state)
    if surface == "platform":
        await grant(state, READ, MANAGE)
    before = membership_snapshot(state)
    method = {"role": "PATCH", "remove": "DELETE", "transfer": "POST"}[action]
    path = "/owner" if action == "transfer" else f"/members/{processing}"
    body = {"role": "admin"} if action == "role" else {}
    if action == "transfer":
        body["person_id"] = str(processing)
    if surface == "platform":
        body["reason"] = "Fictional processing identity protection test"
        response = await platform_call(
            state, method, f"/{state.tenant}{path}", body=body, key=uuid4()
        )
    else:
        response = await organisation_call(state, method, path, body=body or None, key=uuid4())
    assert response.status_code == 404
    assert response.json()["detail"] == "Member not found."
    assert membership_snapshot(state) == before
