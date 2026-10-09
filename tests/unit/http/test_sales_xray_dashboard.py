"""Bounded dashboard uses existing account services and isolates a failed part."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

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


@pytest.mark.parametrize("failure", [None, "denied", "database", "timeout"])
async def test_snapshot_guards_and_partial_failure(tmp_path, monkeypatch, failure):
    actor = ActorContext(PERSON_ID, SESSION_ID, PUBLIC_TENANT)
    signed_in = True
    reads = []
    database = _Database()

    @asynccontextmanager
    async def nested():
        yield

    database.begin_nested = nested

    async def writer(request):
        raise AssertionError("A GET must not use mutating authentication")
        yield

    async def read_only(request):
        if not signed_in:
            raise AuthenticationRequired("Account required")
        reads.append(actor)
        yield AuthenticatedTransaction(
            database, SimpleNamespace(), SimpleNamespace(actor=actor), "fictional-session"
        )

    writer.read_only = read_only
    summary = AsyncMock(
        return_value={"total": 2, "completed": 1, "processing": 1, "needs_attention": 0}
    )
    activity = AsyncMock(return_value={"days": []})
    recent = AsyncMock(return_value={"submissions": [], "next_cursor": None})
    if failure:
        summary.side_effect = {
            "denied": ConversationDenied("Denied"),
            "database": SQLAlchemyError("fictional"),
            "timeout": TimeoutError(),
        }[failure]
    module = "ac_platform.http.conversation_submissions."
    monkeypatch.setattr(module + "account_library_summary", summary)
    monkeypatch.setattr(module + "account_activity", activity)
    monkeypatch.setattr(module + "account_library", recent)
    monkeypatch.setattr(_Service, "clock", None, raising=False)
    runtime = _runtime(tmp_path)
    app = FastAPI()
    install_submission_http(
        app,
        settings=_settings(),
        sessions=None,
        require_actor=writer,
        factory=_Service,
        runtime=runtime.intake,
        preflight=runtime.preflight,
    )
    path = "/v1/conversation/acquisition/dashboard"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://salesxray.example.test"
    ) as client:
        response = await client.get(path)
        assert response.status_code == 200
        parts = response.json()
        assert parts["summary"]["status"] == (
            200 if failure is None else 403 if failure == "denied" else 503
        )
        assert all(parts[key]["status"] == 200 for key in ("activity", "allowance", "recent"))
        assert len(reads) == 1
        assert (
            response.headers["cache-control"] == "private, no-store"
            and response.headers["vary"] == "Cookie"
        )
        assert "set-cookie" not in response.headers
        assert recent.call_args.kwargs == {"shared_identity_locks": True, "limit": 5}
        assert (
            recent.call_args.args[0].tenant_id == PUBLIC_TENANT
            and recent.call_args.args[1] == actor
        )
        assert (await client.get(path + "?tenant_id=other")).status_code == 422
        assert (await client.post(path)).status_code == 405
        signed_in = False
        assert (await client.get(path)).status_code == 401
        assert summary.await_count == activity.await_count == recent.await_count == 1
