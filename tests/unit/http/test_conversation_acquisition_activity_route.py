"""The dashboard activity path uses the saved-call account boundary and no parameters."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

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
async def test_activity_route_and_account_guards(tmp_path, monkeypatch, host):
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    signed_in = True

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
    activity = AsyncMock(return_value=body)
    monkeypatch.setattr("ac_platform.http.conversation_submissions.account_activity", activity)
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    app, runtime = FastAPI(), _runtime(tmp_path)
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"https://{host}.example.test"
    ) as client:
        response = await client.get(prefix + "/activity")
        assert response.status_code == 200 and response.json() == body
        assert set(response.json()) == {
            "timezone",
            "days",
            "analysed_last_30_days",
            "analysed_previous_30_days",
        }
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
        assert activity.call_args.args[1] == actor
        assert activity.call_args.kwargs == {"shared_identity_locks": True}
        for query in ("?before=00000000-0000-0000-0000-000000000001", "?days=7"):
            assert (await client.get(prefix + "/activity" + query)).status_code == 422
        assert (await client.post(prefix + "/activity")).status_code == 405
        signed_in = False
        denied = await client.get(prefix + "/activity")
        library = await client.get(prefix + "/submissions")
        assert denied.status_code == library.status_code == 401
        assert denied.json() == library.json()
        assert activity.await_count == 1
