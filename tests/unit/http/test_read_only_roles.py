"""Viewer and Finance change nothing but their own (Roles B, 25 Oct 2026): every route
behind require_actor refuses their changes with 403, reads still work, their own profile
and workspace switch still save, Finance still pays, and a seller is unaffected."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, cast

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401

HOST = "https://learner.authorityclosers.test"


def _app(state: Any) -> FastAPI:
    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    app = FastAPI()
    register_problem_handlers(app)
    actor = install_identity_http(app, settings=state.settings, sessions=cast(Any, sessions))

    async def probe(_auth: object = Depends(actor)) -> dict[str, bool]:
        return {"ok": True}

    # A team route, the member's own profile, and paying.
    for path in ("/v1/lead-desk/probe", "/v1/me/sales-xray-profile/probe", "/v1/checkout/probe"):
        app.add_api_route(path, probe, methods=["GET", "POST"])
    return app


def _role(state: Any, role: str) -> None:
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenants["Alpha"], state.person)).role = role
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenants["Alpha"]


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("viewer", {"read": 200, "change": 403, "own": 200, "pay": 403}),
        ("finance", {"read": 200, "change": 403, "own": 200, "pay": 200}),
        ("member", {"read": 200, "change": 200, "own": 200, "pay": 200}),
        ("manager", {"read": 200, "change": 200, "own": 200, "pay": 200}),
    ],
)
async def test_read_only_roles_change_only_their_own(
    workspace_state: Any,  # noqa: F811
    role: str,
    expected: dict[str, int],
) -> None:
    _role(workspace_state, role)
    app = _app(workspace_state)
    cookie = {"cookie": f"ac_session={TOKEN}", "origin": HOST}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=HOST) as client:
        read = await client.get("/v1/lead-desk/probe", headers=cookie)
        change = await client.post("/v1/lead-desk/probe", headers=cookie)
        own = await client.post("/v1/me/sales-xray-profile/probe", headers=cookie)
        pay = await client.post("/v1/checkout/probe", headers=cookie)
    got = {
        "read": read.status_code,
        "change": change.status_code,
        "own": own.status_code,
        "pay": pay.status_code,
    }
    assert got == expected, (read.json(), change.json())
    if expected["change"] == 403:
        assert change.json()["code"] == "role_read_only"
