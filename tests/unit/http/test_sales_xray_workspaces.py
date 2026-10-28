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

from ac_platform.conversation_intelligence.sales_xray_tenants import (
    sales_xray_served_tenant_ids,
    sales_xray_workspace_served,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_workspaces import (
    SalesXrayWorkspacesResponse,
    install_sales_xray_workspaces_http,
)
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.unit.http.test_workspaces import (  # noqa: F401
    OTHER_TOKEN,
    TOKEN,
    HttpDatabase,
    workspace_state,
)


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
                "sales_xray_enabled": True,
                "logo_url": None,
            },
            {
                "tenant_id": str(state.tenants["Alpha"]),
                "kind": "organisation",
                "name": "Alpha",
                "role": "admin",
                "sales_xray_enabled": True,
                "logo_url": None,
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
async def test_role_mapping_for_organisation_without_an_explicit_policy(state, role):
    state.intake.policy.tenant_ids = frozenset({state.tenants["Other"]})
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenants["Alpha"], state.person)).role = role
    choice = (await get(state)).json()["workspaces"][1]
    assert choice["role"] == (role if role in {"owner", "admin"} else "member")
    assert choice["sales_xray_enabled"] is True


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


async def test_live_registry_is_the_served_set_and_new_organisations_need_no_restart(state):
    with Session(state.engine) as db:
        served = await sales_xray_served_tenant_ids(state.settings, None, HttpDatabase(db))
        assert served == frozenset(state.tenants[n] for n in ("Beta", "Alpha", "Inactive"))
        for name in ("Other", "Suspended", "Deleted"):
            assert not await sales_xray_workspace_served(
                HttpDatabase(db), state.settings, state.tenants[name]
            )
    new_id = uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(Tenant(id=new_id, name="Created after API startup", slug=new_id.hex))
        db.flush()
        db.add(
            Organisation(
                tenant_id=new_id, creation_command_id=uuid4(), domain_verification_token="f" * 43
            )
        )
        db.add(Membership(tenant_id=new_id, person_id=state.person, role="owner"))
    body = (await get(state)).json()
    assert (
        next(w for w in body["workspaces"] if w["tenant_id"] == str(new_id))["sales_xray_enabled"]
        is True
    )
    with Session(state.engine) as db, db.begin():
        db.get(Tenant, new_id).status = "suspended"
    assert str(new_id) not in {w["tenant_id"] for w in (await get(state)).json()["workspaces"]}


def test_legacy_two_argument_installation_remains_synchronous(state):
    assert sales_xray_served_tenant_ids(state.settings, state.intake) == frozenset(
        state.tenants[n] for n in ("Beta", "Alpha")
    )
    assert sales_xray_served_tenant_ids(state.settings, None) == frozenset({state.tenants["Beta"]})


async def test_directory_logos_are_member_scoped_and_do_not_select_workspace(state):
    from ac_platform.media.local_avatar_runtime import LocalAvatarRuntime
    from ac_platform.organisations.settings import logo_key

    logo, other_logo = uuid4(), uuid4()
    with Session(state.engine) as db, db.begin():
        db.get(Organisation, state.tenants["Alpha"]).logo_id = logo
        db.get(Organisation, state.tenants["Suspended"]).logo_id = other_logo
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenants["Beta"]
    body = (await get(state)).json()
    assert body["workspaces"][0]["logo_url"] is None
    url = body["workspaces"][1]["logo_url"]
    assert url == f"/v1/me/sales-xray-workspaces/{state.tenants['Alpha']}/logo/{logo}"
    read = []
    # Only byte delivery is stubbed; canonical cookie auth and membership queries run.
    runtime = object.__new__(LocalAvatarRuntime)
    object.__setattr__(
        runtime, "storage", SimpleNamespace(read=lambda key: read.append(key) or b"webp")
    )
    state.app.state.organisation_avatar_runtime = runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app),
        base_url="https://learner.authorityclosers.test",
    ) as client:
        headers = {"cookie": f"ac_session={TOKEN}"}
        response = await client.get(url, headers=headers)
        assert response.status_code == 200 and response.content == b"webp"
        assert response.headers["content-type"] == "image/webp"
        assert "no-store" in response.headers["cache-control"]
        assert response.headers["vary"] == "Cookie"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert (await client.get(url)).status_code == 401
        assert (
            await client.get(url, headers={"cookie": f"ac_session={OTHER_TOKEN}"})
        ).status_code == 404
        assert all(
            item["logo_url"] is None
            for item in (await get(state, token=OTHER_TOKEN)).json()["workspaces"]
        )
        other = f"/v1/me/sales-xray-workspaces/{state.tenants['Suspended']}/logo/{other_logo}"
        assert (await client.get(other, headers=headers)).status_code == 404
        assert (
            await client.get(url.replace(str(logo), str(uuid4())), headers=headers)
        ).status_code == 404
        with Session(state.engine) as db, db.begin():
            membership = db.get(Membership, (state.tenants["Alpha"], state.person))
            membership.status = "inactive"
            membership.ended_at = datetime.now(UTC)
        assert (await client.get(url, headers=headers)).status_code == 404
    assert read == [logo_key(state.tenants["Alpha"], logo)]
    with Session(state.engine) as db:
        assert db.get(IdentitySession, state.session).selected_tenant_id == state.tenants["Beta"]
