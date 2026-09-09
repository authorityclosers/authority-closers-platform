"""Real identity, relational grant/revoke and HTTP surface admission (SQLite)."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityScope
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform import install_platform_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.http.test_workspaces import OTHER_TOKEN, TOKEN, HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state


@pytest.fixture
def platform_state(workspace_state):
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={"operations_tenant_id": state.tenants["Other"]}
    )

    @asynccontextmanager
    async def sessions():
        state.opened += 1
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    require_actor = install_identity_http(
        state.app, settings=state.settings, sessions=cast(Any, sessions)
    )
    install_platform_http(state.app, settings=state.settings, require_actor=require_actor)
    state.app.add_middleware(CoachSurfaceMiddleware, settings=state.settings)
    return state


async def grant(state, permission="platform_tenants_read"):
    with Session(state.engine) as db, db.begin():
        database = cast(Any, HttpDatabase(db))
        app = CapabilityApplication(database, operations_tenant_id=state.tenants["Other"])
        await app.bootstrap_first_manager(
            person_id=state.other, command_id=uuid4(), reason="Synthetic first manager"
        )
        actor = (
            await AsyncIdentityApplication(
                database, token_pepper=state.settings.session_token_pepper.get_secret_value()
            ).resolve_actor(OTHER_TOKEN)
        ).actor
        result = await app.grant(
            actor,
            subject_person_id=state.person,
            command_id=uuid4(),
            permission=permission,
            scope=CapabilityScope("platform"),
            reason="Synthetic platform assignment",
        )
        return result.id


async def read(state, path="/v1/me/platform-access", *, token=TOKEN, host="admin", **kwargs):
    origin = "http://localhost" if host == "internal" else f"https://{host}.authorityclosers.test"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=origin
    ) as client:
        return await client.get(
            path, headers={} if token is None else {"cookie": f"ac_session={token}"}, **kwargs
        )


async def test_platform_grant_needs_no_selected_academy_or_operations_membership(platform_state):
    state = platform_state
    await grant(state)
    response = await read(state)
    assert response.status_code == 200
    assert response.json() == {
        "person_id": str(state.person),
        "session_id": str(state.session),
        "selected_tenant_id": None,
        "platform_permissions": ["platform_tenants_read"],
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert "set-cookie" not in response.headers
    with Session(state.engine) as db:
        assert db.get(Membership, (state.tenants["Other"], state.person)) is None
        assert db.get(IdentitySession, state.session).selected_tenant_id is None
        assert set(
            db.scalars(select(Membership.role).where(Membership.person_id == state.person))
        ) == {"learner"}


async def test_legacy_tenant_owner_is_not_platform_administrator(platform_state):
    response = await read(platform_state, token=OTHER_TOKEN)
    assert response.status_code == 200
    assert response.json()["platform_permissions"] == []
    assert (
        await read(platform_state, "/v1/platform/tenants", token=OTHER_TOKEN)
    ).status_code == 403


async def test_platform_access_manager_is_not_implicit_tenant_reader(platform_state):
    await grant(platform_state, "platform_access_manage")
    assert (await read(platform_state)).json()["platform_permissions"] == ["platform_access_manage"]
    assert (await read(platform_state, "/v1/platform/tenants")).status_code == 403


@pytest.mark.parametrize("host", ["coach", "learner"])
@pytest.mark.parametrize("path", ["/v1/me/platform-access", "/v1/platform/tenants"])
async def test_other_surfaces_cannot_use_platform_endpoints(platform_state, host, path):
    await grant(platform_state)
    response = await read(platform_state, path, host=host)
    assert response.status_code == 403
    assert "no-store" in response.headers["cache-control"]
    assert "tenants" not in response.json()


async def test_internal_projection_only_has_no_inventory_route(platform_state):
    await grant(platform_state)
    assert (await read(platform_state, host="internal")).status_code == 200
    assert (await read(platform_state, "/v1/platform/tenants", host="internal")).status_code == 403


@pytest.mark.parametrize("token", [None, "bad", "x" * 44])
async def test_invalid_cookie_denies_both_endpoints_without_data(platform_state, token):
    for path in ("/v1/me/platform-access", "/v1/platform/tenants"):
        response = await read(platform_state, path, token=token)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("failure", ["expired", "revoked", "suspended", "unverified", "ops"])
async def test_fresh_lifecycle_revokes_access_after_success(platform_state, failure):
    state = platform_state
    await grant(state)
    assert (await read(state, "/v1/platform/tenants")).status_code == 200
    with Session(state.engine) as db, db.begin():
        person = db.get(Person, state.person)
        session = db.get(IdentitySession, state.session)
        if failure == "expired":
            session.expires_at = datetime.now(UTC) - timedelta(hours=1)
        elif failure == "revoked":
            session.revoked_at, session.revocation_reason = datetime.now(UTC), "test_revoke"
        elif failure == "suspended":
            person.status = "suspended"
        elif failure == "unverified":
            person.email_verified_at = None
        else:
            db.get(Tenant, state.tenants["Other"]).status = "suspended"
    for path in ("/v1/me/platform-access", "/v1/platform/tenants"):
        response = await read(state, path)
        assert response.status_code == (403 if failure == "ops" else 401)
        assert "tenants" not in response.json()


async def test_canonical_revocation_is_seen_on_next_request(platform_state):
    state = platform_state
    grant_id = await grant(state)
    assert (await read(state, "/v1/platform/tenants")).status_code == 200
    with Session(state.engine) as db, db.begin():
        database = cast(Any, HttpDatabase(db))
        actor = (
            await AsyncIdentityApplication(
                database, token_pepper=state.settings.session_token_pepper.get_secret_value()
            ).resolve_actor(OTHER_TOKEN)
        ).actor
        await CapabilityApplication(database, operations_tenant_id=state.tenants["Other"]).revoke(
            actor, command_id=uuid4(), grant_id=grant_id, reason="Synthetic removal"
        )
    assert (await read(state)).json()["platform_permissions"] == []
    assert (await read(state, "/v1/platform/tenants")).status_code == 403


async def test_inventory_is_bounded_cursor_sorted_and_has_no_people_details(platform_state):
    state = platform_state
    await grant(state)
    with Session(state.engine) as db, db.begin():
        for index in range(105):
            db.add(Tenant(id=uuid4(), slug=f"page-{index}", name=f"Academy {index}"))
    first = (await read(state, "/v1/platform/tenants")).json()
    second = (await read(state, "/v1/platform/tenants?after_id=" + first["next_after_id"])).json()
    assert len(first["tenants"]) == 100 and len(second["tenants"]) == 11
    assert second["next_after_id"] is None
    rows = first["tenants"] + second["tenants"]
    ids = [row["tenant_id"] for row in rows]
    assert ids == sorted(set(ids))
    assert all(set(row) == {"tenant_id", "name", "kind", "status"} for row in rows)
    assert first["person_id"] == str(state.person) and first["session_id"] == str(state.session)
    assert sum(row["kind"] == "platform" for row in rows) == 1


@pytest.mark.parametrize(
    "path",
    [
        "/v1/me/platform-access?person_id=other",
        "/v1/platform/tenants?tenant_id=other",
        "/v1/platform/tenants?after_id=bad",
        "/v1/platform/tenants?after_id=" + str(uuid4()) + "&after_id=" + str(uuid4()),
    ],
)
async def test_selector_and_cursor_ambiguity_rejected(platform_state, path):
    await grant(platform_state)
    response = await read(platform_state, path)
    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]
