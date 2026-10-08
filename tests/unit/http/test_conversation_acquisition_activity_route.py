"""The dashboard activity path uses the saved-call account boundary and no parameters."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ac_platform.conversation_intelligence.application import ConversationDenied
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


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["salesxray", "learner"])
@pytest.mark.parametrize("organisation", [False, True])
async def test_activity_route_and_account_guards(tmp_path, monkeypatch, host, organisation):
    selected = uuid4() if organisation else PUBLIC_TENANT
    actor = ActorContext(PERSON_ID, SESSION_ID, selected)
    signed_in = True
    read_count = 0

    async def require_actor(request):
        if not signed_in:
            raise AuthenticationRequired("Account required")
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    body = {
        "timezone": "Asia/Kolkata",
        "days": [{"date": "2026-09-29", "analysed": 2, "analysed_seconds": 150}],
        "analysed_last_30_days": 2,
        "analysed_previous_30_days": 1,
    }
    if organisation:
        body["people"] = [
            dict(
                person_id=str(PERSON_ID),
                name="Fictional Person",
                analysed_last_30_days=2,
                analysed_seconds_last_30_days=150,
                analysed_previous_30_days=1,
            )
        ]
    activity = AsyncMock(return_value=body)
    name = "organisation_acquisition_activity" if organisation else "account_activity"
    monkeypatch.setattr("ac_platform.http.conversation_submissions." + name, activity)
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    app, runtime = FastAPI(), _runtime(tmp_path)
    runtime = replace(
        runtime,
        intake=replace(
            runtime.intake,
            policy=replace(runtime.intake.policy, tenant_ids=frozenset({PUBLIC_TENANT, selected})),
        ),
    )

    async def read_auth(request):
        nonlocal read_count
        read_count += 1
        async for auth in require_actor(request):
            yield auth

    require_actor.read_only = read_auth
    install_submission_http(
        app,
        settings=_settings(),
        sessions=None,
        require_actor=require_actor,
        factory=_Service,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
    prefix = "/v1/conversation/acquisition"
    path = prefix + ("/organisation/activity" if organisation else "/activity")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"https://{host}.example.test"
    ) as client:
        response = await client.get(path)
        assert response.status_code == 200 and response.json() == body
        assert set(response.json()) == {
            "timezone",
            "days",
            "analysed_last_30_days",
            "analysed_previous_30_days",
        } | ({"people"} if organisation else set())
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
        assert activity.call_args.args[1] == actor
        assert activity.call_args.args[0].tenant_id == selected
        assert activity.call_args.args[0].database is activity.call_args.args[0].sessions.database
        assert activity.call_args.kwargs == {"shared_identity_locks": True}
        assert read_count == 1
        for query in (
            "?before=00000000-0000-0000-0000-000000000001",
            "?days=7",
            "?tenant_id=" + str(uuid4()),
        ):
            assert (await client.get(path + query)).status_code == 422
        assert (await client.post(path)).status_code == 405
        if organisation:
            activity.side_effect = ConversationDenied(
                "An active organisation owner or admin is required."
            )
            forbidden = await client.get(path)
            assert forbidden.status_code == 403
            assert forbidden.headers["cache-control"] == "private, no-store"
            assert forbidden.headers["vary"] == "Cookie"
        signed_in = False
        denied = await client.get(path)
        library = await client.get(prefix + "/submissions")
        assert denied.status_code == library.status_code == 401
        assert denied.json() == library.json()
        assert activity.await_count == (2 if organisation else 1)
