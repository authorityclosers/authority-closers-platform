"""Minutes reads (owner, 18 Nov 2026): members see their own, owners/admins see everyone."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ac_platform.conversation_intelligence import sales_xray_tenants
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.conversation_minutes import DENIED, NOT_A_MEMBER, install_minutes_routes
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_conversation_learner_acquisition import (
    PERSON_ID,
    SESSION_ID,
    _Database,
    _settings,
)

PREFIX = "/v1/conversation/acquisition"
MODULE = "ac_platform.http.conversation_minutes"


@pytest.mark.asyncio
async def test_minutes_reads_admit_members_and_owners_on_the_sales_xray_host(monkeypatch):
    selected = uuid4()
    actor = ActorContext(PERSON_ID, SESSION_ID, selected)
    state: dict[str, Any] = {"signed_in": True, "member": True, "reader": True, "writes": 0}

    async def require_actor(request):
        state["writes"] += 1
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    async def read_auth(request):
        if not state["signed_in"]:
            raise AuthenticationRequired("Account required")
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    require_actor.read_only = read_auth

    async def member(database, who, settings):
        assert who == actor
        return state["member"]

    async def reader(database, who, operations):
        assert who == actor and operations == _settings().operations_tenant_id
        return state["reader"]

    async def served(database, settings, tenant_id):
        return tenant_id == selected

    monkeypatch.setattr(f"{MODULE}.current_member", member)
    monkeypatch.setattr(f"{MODULE}.organisation_reader", reader)
    monkeypatch.setattr(sales_xray_tenants, "sales_xray_workspace_served", served, raising=False)
    mine = {"scope": "organisation", "granted_seconds": 10_800, "left_seconds": 9_000}
    everyone = {"scope": "organisation", "members": [], "others_used_seconds": 0}
    seller = AsyncMock(return_value=mine)
    workspace = AsyncMock(return_value=everyone)
    monkeypatch.setattr(f"{MODULE}.minutes_summary.seller_minutes", seller)
    monkeypatch.setattr(f"{MODULE}.minutes_summary.workspace_minutes", workspace)

    app = FastAPI()
    install_minutes_routes(app, settings=_settings(), require_actor=require_actor, intake=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as client:
        response = await client.get(PREFIX + "/minutes")
        assert response.status_code == 200 and response.json() == mine
        assert response.headers["cache-control"] == "private, no-store"
        kwargs = seller.call_args.kwargs
        assert kwargs["tenant_id"] == selected and kwargs["person_id"] == PERSON_ID

        response = await client.get(PREFIX + "/minutes/workspace")
        assert response.status_code == 200 and response.json() == everyone
        assert workspace.call_args.kwargs["tenant_id"] == selected
        # Reads only: the write transaction is never opened.
        assert state["writes"] == 0

        assert (await client.get(PREFIX + "/minutes?seller=x")).status_code == 422

        state["reader"] = False
        refused = await client.get(PREFIX + "/minutes/workspace")
        assert refused.status_code == 403 and refused.json()["detail"] == DENIED
        assert (await client.get(PREFIX + "/minutes")).status_code == 200

        state["member"] = False
        refused = await client.get(PREFIX + "/minutes")
        assert refused.status_code == 403 and refused.json()["detail"] == NOT_A_MEMBER

        state["signed_in"] = False
        assert (await client.get(PREFIX + "/minutes")).status_code == 401

    # Another workspace that Sales Xray doesn't serve: 403; another host: 404.
    state.update(signed_in=True, member=True, reader=True)
    actor = ActorContext(PERSON_ID, SESSION_ID, uuid4())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as client:
        assert (await client.get(PREFIX + "/minutes")).status_code == 403
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://academy.example.test"
    ) as client:
        assert (await client.get(PREFIX + "/minutes")).status_code == 404
