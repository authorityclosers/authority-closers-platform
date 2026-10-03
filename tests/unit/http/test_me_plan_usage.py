"""Plan and usage reads keep the canonical read-only account boundary."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.conversation_acquisition import install_acquisition_http
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_conversation_learner_acquisition import (
    OTHER_TENANT,
    PERSON_ID,
    PUBLIC_TENANT,
    SESSION_ID,
    _Database,
    _runtime,
    _Service,
    _settings,
)


@pytest.mark.parametrize("host", ["salesxray", "learner"])
async def test_me_reads_share_allowance_and_refuse_guest_or_foreign_workspace(
    tmp_path, monkeypatch, host
):
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    signed_in = True
    database = _Database()
    service = _Service(database)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    service.clock = lambda: now

    async def read_actor(request):
        if not signed_in:
            raise AuthenticationRequired("Account required")
        yield AuthenticatedTransaction(
            database, SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    async def require_actor(request):
        raise AssertionError("GET must use the read-only actor")
        yield  # pragma: no cover

    require_actor.read_only = read_actor
    usage = AsyncMock(return_value={"calls": [], "earlier_seconds": 17, "truncated": False})
    monkeypatch.setattr("ac_platform.http.conversation_acquisition.account_usage", usage)
    app = FastAPI()
    install_acquisition_http(
        app,
        settings=_settings(),
        sessions=None,
        require_actor=require_actor,
        factory=lambda _database, _tenant_id: service,
        challenge=_runtime(tmp_path).challenge,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=f"https://{host}.example.test"
    ) as client:
        session = await client.get("/v1/conversation/acquisition/session")
        # On the Sales Xray host the session route selects the account via its cookie.
        if host == "salesxray":
            client.cookies.set(_settings().session_cookie_name, "s" * 43)
            session = await client.get("/v1/conversation/acquisition/session")
        allowance = session.json()["allowance"]
        for path in ("/v1/me/plan", "/v1/me/usage"):
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json()["allowance"] == allowance
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["vary"] == "Cookie"
            if path.endswith("plan"):
                assert response.json() == {
                    "plan": {"key": "trial", "name": "Trial"},
                    "allowance": allowance,
                    "longest_call_seconds": 6000,
                }
            else:
                assert response.json() == {"allowance": allowance, **usage.return_value}
            assert (await client.get(path + "?person_id=other")).status_code == 422
            assert (await client.post(path)).status_code == 405
            actor = ActorContext(PERSON_ID, SESSION_ID, OTHER_TENANT)
            assert (await client.get(path)).status_code == 403
            actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
            signed_in = False
            client.cookies.set("ac_xray_guest", "g" * 43)
            denied = await client.get(path)
            assert denied.status_code == 401
            assert denied.headers["cache-control"] == "private, no-store"
            signed_in = True
        assert all(service.allowance_lock_modes)
        assert all(value == actor for value in service.allowance_actors)
        usage.assert_awaited_once_with(
            database, tenant_id=PUBLIC_TENANT, person_id=PERSON_ID, now=now
        )
        assert (await client.get("https://admin.example.test/v1/me/plan")).status_code == 404
