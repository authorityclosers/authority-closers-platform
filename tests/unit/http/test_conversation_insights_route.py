"""The company view's routes (AUT-1798): owners and admins only, on the Sales Xray host."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.conversation_submissions import install_submission_http
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_conversation_learner_acquisition import (
    PERSON_ID,
    PUBLIC_TENANT,
    SESSION_ID,
    _Database,
    _runtime,
    _Service,
    _settings,
)

PREFIX = "/v1/conversation/acquisition"


@pytest.mark.asyncio
async def test_company_view_admits_only_current_owners_and_admins(tmp_path, monkeypatch):
    selected = uuid4()
    actor = ActorContext(PERSON_ID, SESSION_ID, selected)
    state: dict[str, Any] = {"signed_in": True, "reader": True, "reads": 0, "writes": 0}

    async def require_actor(request):
        if not state["signed_in"]:
            raise AuthenticationRequired("Account required")
        state["writes"] += 1
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    async def read_auth(request):
        if not state["signed_in"]:
            raise AuthenticationRequired("Account required")
        state["reads"] += 1
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    require_actor.read_only = read_auth

    async def reader(self, who):
        assert who == actor and self.tenant_id == selected
        return state["reader"]

    monkeypatch.setattr(GuestOwnership, "organisation_call_reader", reader)
    insights = SimpleNamespace(
        overview=AsyncMock(return_value={"source": "call", "totals": {"calls": 3}}),
        calls=AsyncMock(return_value={"items": [], "total": 0}),
        refresh=AsyncMock(return_value={"projected": 2, "pending": 0}),
    )
    built: list[ActorContext] = []

    def library(database, who):
        built.append(who)
        return insights

    monkeypatch.setattr("ac_platform.http.conversation_insights.library_insights", library)
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    app, runtime = FastAPI(), _runtime(tmp_path)
    runtime = replace(
        runtime,
        intake=replace(
            runtime.intake,
            policy=replace(runtime.intake.policy, tenant_ids=frozenset({PUBLIC_TENANT, selected})),
        ),
    )
    install_submission_http(
        app,
        settings=_settings(),
        sessions=None,
        require_actor=require_actor,
        factory=_Service,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
    origin = {"Origin": "https://salesxray.example.test"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as client:
        response = await client.get(PREFIX + "/insights?range=12m&outcome=won")
        assert response.status_code == 200
        assert response.json() == {"source": "call", "totals": {"calls": 3}}
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
        filters = insights.overview.call_args.args[0]
        assert filters.outcome == "won" and filters.since is not None
        assert built == [actor] and state["reads"] == 1 and state["writes"] == 0

        calls = await client.get(PREFIX + "/insights/calls?offset=50&person=someone")
        assert calls.status_code == 200
        assert insights.calls.call_args.kwargs == {"offset": 50}
        assert insights.calls.call_args.args[0].person == "someone"

        refreshed = await client.post(PREFIX + "/insights/refresh", headers=origin)
        assert refreshed.status_code == 200 and refreshed.json()["projected"] == 2
        assert state["writes"] == 1
        foreign = await client.post(
            PREFIX + "/insights/refresh", headers={"Origin": "https://evil.example.test"}
        )
        assert foreign.status_code == 403
        assert (
            await client.post(PREFIX + "/insights/refresh?force=1", headers=origin)
        ).status_code == 422

        for query in ("?days=7", "?range=5y", "?outcome=maybe", "?range=30d&range=90d"):
            assert (await client.get(PREFIX + "/insights" + query)).status_code == 422

        # A member (or a former admin) is refused on every route.
        state["reader"] = False
        for method, path in (
            ("GET", "/insights"),
            ("GET", "/insights/calls"),
            ("POST", "/insights/refresh"),
        ):
            denied = await client.request(method, PREFIX + path, headers=origin)
            assert denied.status_code == 403
            assert "owners and admins" in denied.json()["detail"]

        state["signed_in"] = False
        assert (await client.get(PREFIX + "/insights")).status_code == 401
        assert insights.overview.await_count == 1 and insights.refresh.await_count == 1

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.example.test"
    ) as learner:
        state.update(signed_in=True, reader=True)
        assert (await learner.get(PREFIX + "/insights")).status_code == 404
