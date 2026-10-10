"""Verified-person organisation creation through canonical cookie transactions."""

from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.http.auth import install_identity_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401

ORIGIN = "https://learner.authorityclosers.test"


class CreationDatabase(HttpDatabase):
    def add_all(self, rows):
        self.database.add_all(rows)


@pytest.fixture
def state(workspace_state):  # noqa: F811
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={
            "public_learner_tenant_id": state.tenants["Beta"],
            "operations_tenant_id": state.tenants["Other"],
        }
    )

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield CreationDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    install_organisation_http(state.app, settings=state.settings, require_actor=actor)
    return state


async def create(state, *, name="Fictional Team", key=None, token=TOKEN, origin=ORIGIN, body=None):
    headers = {"Origin": origin, "Idempotency-Key": str(key or uuid4())}
    if token is not None:
        headers["Cookie"] = f"ac_session={token}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=ORIGIN
    ) as client:
        return await client.post(
            "/v1/organisation", headers=headers, json={"name": name} if body is None else body
        )


async def test_create_from_personal_replays_and_lists_the_new_owned_workspace(state):
    with Session(state.engine) as db, db.begin():
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenants["Beta"]
    key = uuid4()
    first = await create(state, name="  मराठी टीम  ", key=key)
    assert first.status_code == 201, first.text
    tenant_id = UUID(first.json()["tenant_id"])
    assert first.json() == {
        "tenant_id": str(tenant_id),
        "name": "मराठी टीम",
        "handle": f"organisation-{tenant_id.hex}",
        "your_role": "owner",
    }
    assert first.headers["cache-control"] == "private, no-store"
    assert first.headers["vary"] == "Cookie"
    assert (await create(state, name="मराठी टीम", key=key)).json() == first.json()
    assert (await create(state, name="Changed intent", key=key)).status_code == 409
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 1
        member = db.get(Membership, (tenant_id, state.person))
        assert (member.role, member.status, member.ended_at) == ("owner", "active", None)
        audit = db.scalar(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id))
        assert audit.action == "organisation.created"
        assert audit.actor_type == "person" and audit.actor_person_id == state.person
        assert audit.request_id == str(key)
        assert verify_audit_chain_sync(db, tenant_id).valid
        assert db.get(IdentitySession, state.session).selected_tenant_id == state.tenants["Beta"]
        assert db.scalar(select(func.count()).select_from(BillingAccount)) == 0
        assert db.scalar(select(func.count()).select_from(BillingLedgerEntry)) == 0
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=ORIGIN
    ) as client:
        listing = await client.get("/v1/me/workspaces", headers={"Cookie": f"ac_session={TOKEN}"})
    assert listing.status_code == 200
    assert any(row["tenant_id"] == str(tenant_id) for row in listing.json()["workspaces"])


async def test_create_without_selected_workspace_is_allowed_and_slugs_are_bounded(state):
    first = await create(state, name="A" * 80)
    second = await create(state, name="A" * 80)
    assert first.status_code == second.status_code == 201
    assert len(first.json()["handle"]) == 63
    assert first.json()["handle"] != second.json()["handle"]


@pytest.mark.parametrize("token", [None, "bad"])
async def test_create_requires_signed_in_identity_without_registry_writes(state, token):
    assert (await create(state, token=token)).status_code == 401
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def test_unverified_person_and_unsafe_origin_cannot_create(state):
    assert (await create(state, origin="https://wrong.example.test")).status_code == 403
    with Session(state.engine) as db, db.begin():
        db.get(Person, state.person).email_verified_at = None
    assert (await create(state)).status_code == 401
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 0
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == 0


@pytest.mark.parametrize("name", ["x", " " * 4, "a" * 81])
async def test_invalid_name_cannot_create(state, name):
    assert (await create(state, name=name)).status_code == 422
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 0


async def test_owner_identifier_cannot_be_supplied_in_body(state):
    response = await create(
        state, body={"name": "Fictional team", "owner_person_id": str(state.other)}
    )
    assert response.status_code == 422
    with Session(state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Organisation)) == 0
