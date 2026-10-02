"""Fictional relational HTTP evidence; the directory never mutates identity."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_workspaces import (
    SalesXrayWorkspacesResponse,
    install_sales_xray_workspaces_http,
)
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401


@pytest.fixture
def state(request):
    state = request.getfixturevalue("workspace_state")
    state.configured = getattr(request, "param", True)
    state.settings = state.settings.model_copy(
        update={
            "public_learner_tenant_id": state.tenants["Beta"],
            "operations_tenant_id": state.tenants["Other"],
        }
    )
    with Session(state.engine) as db, db.begin():
        for name in ("Alpha", "Other", "Suspended", "Deleted", "Inactive"):
            db.add(
                Organisation(
                    tenant_id=state.tenants[name],
                    creation_command_id=uuid4(),
                    domain_verification_token="f" * 43,
                )
            )
        db.add(Membership(tenant_id=state.tenants["Other"], person_id=state.person, role="owner"))
        db.get(Membership, (state.tenants["Alpha"], state.person)).role = "admin"

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    tenant_ids = frozenset(state.tenants[name] for name in ("Alpha", "Other"))
    state.intake = SimpleNamespace(policy=SimpleNamespace(tenant_ids=tenant_ids))
    install_sales_xray_workspaces_http(
        state.app,
        settings=state.settings,
        require_actor=actor,
        intake=cast(Any, state.intake) if state.configured else None,
    )
    return state


async def get(state, token=TOKEN, query=""):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        return await client.get(
            "/v1/me/sales-xray-workspaces" + query,
            headers={} if token is None else {"cookie": f"ac_session={token}"},
        )


@pytest.mark.parametrize("selected", [None, "Beta", "Alpha", "Other"])
@pytest.mark.parametrize("state", [True, False], indirect=True)
async def test_exact_directory_is_read_only_and_hides_operations(state, selected):
    selected_id = None if selected is None else state.tenants[selected]
    with Session(state.engine) as db, db.begin():
        db.get(IdentitySession, state.session).selected_tenant_id = selected_id
    writes = []

    @event.listens_for(state.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    response = await get(state)
    assert response.status_code == 200
    assert response.json() == {
        "selected_tenant_id": str(selected_id) if selected in {"Beta", "Alpha"} else None,
        "workspaces": [
            {
                "tenant_id": str(state.tenants["Beta"]),
                "kind": "personal",
                "name": "Personal",
                "role": None,
                "sales_xray_enabled": state.configured,
            },
            {
                "tenant_id": str(state.tenants["Alpha"]),
                "kind": "organisation",
                "name": "Alpha",
                "role": "admin",
                "sales_xray_enabled": state.configured,
            },
        ],
    }
    assert "no-store" in response.headers["cache-control"]
    assert "set-cookie" not in response.headers and writes == []
    with Session(state.engine) as db:
        identity = db.get(IdentitySession, state.session)
        assert identity.selected_tenant_id == selected_id
        assert identity.last_seen_at is None and identity.revision == 0


@pytest.mark.parametrize("role", ["owner", "admin", "member", "learner", "support"])
async def test_approved_role_mapping_and_unapproved_organisation(state, role):
    state.intake.policy.tenant_ids = frozenset({state.tenants["Other"]})
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenants["Alpha"], state.person)).role = role
    choice = (await get(state)).json()["workspaces"][1]
    assert choice["role"] == (role if role in {"owner", "admin"} else "member")
    assert choice["sales_xray_enabled"] is False


@pytest.mark.parametrize("excluded", ["inactive", "ended", "processing", "unregistered", "tenant"])
async def test_ineligible_organisation_is_omitted(state, excluded):
    with Session(state.engine) as db, db.begin():
        membership = db.get(Membership, (state.tenants["Alpha"], state.person))
        if excluded in {"inactive", "ended"}:
            membership.status, membership.ended_at = "inactive", datetime.now(UTC)
        elif excluded == "processing":
            membership.role = "processing"
        elif excluded == "unregistered":
            db.delete(db.get(Organisation, state.tenants["Alpha"]))
        else:
            db.get(Tenant, state.tenants["Alpha"]).status = "suspended"
    response = await get(state)
    assert response.status_code == 200
    assert [w["kind"] for w in response.json()["workspaces"]] == ["personal"]


@pytest.mark.parametrize("token", [None, "bad"])
async def test_session_required(state, token):
    assert (await get(state, token)).status_code == 401


async def test_caller_cannot_supply_a_subject(state):
    assert (await get(state, query="?person_id=other")).status_code == 422


async def test_strict_response(state):
    body = (await get(state)).json()
    for target in (body, body["workspaces"][0]):
        target["extra"] = "forbidden"
        with pytest.raises(ValidationError):
            SalesXrayWorkspacesResponse.model_validate_json(json.dumps(body))
        del target["extra"]
