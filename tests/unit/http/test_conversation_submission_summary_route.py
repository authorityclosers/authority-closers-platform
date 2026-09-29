"""The fixed summary path uses the saved-call account boundary, not UUID parsing."""

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
async def test_summary_route_and_account_guards(tmp_path, monkeypatch, host):
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    signed_in = True

    async def require_actor(request):
        if not signed_in:
            raise AuthenticationRequired("Account required")
        yield AuthenticatedTransaction(
            _Database(), SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    counts = {"total": 25, "processing": 2, "completed": 3, "needs_attention": 1}
    summary = AsyncMock(return_value=counts)
    monkeypatch.setattr(
        "ac_platform.http.conversation_submissions.account_library_summary", summary
    )
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
    path = "/v1/conversation/acquisition/submissions"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"https://{host}.example.test"
    ) as client:
        response = await client.get(path + "/summary")
        assert response.status_code == 200 and response.json() == counts
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
        assert summary.call_args.args[1] == actor
        assert summary.call_args.kwargs == {"shared_identity_locks": True}
        ignored = await client.get(path + "/summary?before=00000000-0000-0000-0000-000000000001")
        assert ignored.status_code == 200 and ignored.json() == counts
        for route in (path, path + "/summary"):
            assert (await client.get(route + "?unexpected=1")).status_code == 422
        signed_in = False
        denied, library = await client.get(path + "/summary"), await client.get(path)
        assert denied.status_code == library.status_code == 401
        assert denied.json() == library.json()
        assert summary.await_count == 2
