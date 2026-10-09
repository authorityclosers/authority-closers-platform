"""Fictional relational evidence for the bootstrap's identity and read-only boundary."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.orm import Session

from ac_platform.http.auth import install_identity_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.sales_xray_bootstrap import install_sales_xray_bootstrap_http
from ac_platform.identity.models import Session as IdentitySession
from tests.unit.http.test_sales_xray_workspaces import state  # noqa: F401, F811
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase, workspace_state  # noqa: F401


@pytest.mark.parametrize("selected", [None, "Beta", "Alpha", "Other"])
async def test_bootstrap_uses_existing_directory_without_writes(state, selected, monkeypatch):  # noqa: F811
    selected_id = state.tenants[selected] if selected else None
    with Session(state.engine) as db, db.begin():
        db.get(IdentitySession, state.session).selected_tenant_id = selected_id
    profile = AsyncMock(
        return_value=SimpleNamespace(
            name="Fictional Person",
            email="fictional@example.test",
            phone_number_e164=None,
            phone_verified=False,
            profile_complete=False,
            revision=0,
            given_name=None,
            family_name=None,
            locale=None,
            hosted_domain=None,
            photo_url=None,
        )
    )
    monkeypatch.setattr("ac_platform.http.sales_xray_bootstrap.get_sales_xray_profile", profile)

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    app = FastAPI()
    register_problem_handlers(app)
    actor = install_identity_http(app, settings=state.settings, sessions=cast(Any, sessions))
    install_sales_xray_bootstrap_http(
        app, settings=state.settings, require_actor=actor, intake=state.intake
    )
    writes = []

    @event.listens_for(state.engine, "before_cursor_execute")
    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://learner.authorityclosers.test"
    ) as client:
        path = "/v1/me/sales-xray-bootstrap"
        response = await client.get(path, headers={"cookie": f"ac_session={TOKEN}"})
        assert response.status_code == 200
        body = response.json()
        assert body["identity"]["person_id"] == str(state.person)
        assert body["identity"]["session_id"] == str(state.session)
        assert body["directory"]["selected_tenant_id"] == (
            str(selected_id) if selected in {"Beta", "Alpha"} else None
        )
        assert [w["kind"] for w in body["directory"]["workspaces"]] == ["personal", "organisation"]
        assert (
            body["profile"] is not None
            if selected in {"Beta", "Alpha"}
            else body["profile"] is None
        )
        assert profile.await_count == (1 if selected in {"Beta", "Alpha"} else 0)
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie" and "set-cookie" not in response.headers
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers={"cookie": "ac_session=invalid"})).status_code == 401
        assert (
            await client.get(path + "?person_id=other", headers={"cookie": f"ac_session={TOKEN}"})
        ).status_code == 404
        assert (await client.post(path)).status_code == 405
    assert writes == []
    with Session(state.engine) as db:
        session = db.get(IdentitySession, state.session)
        assert session.selected_tenant_id == selected_id
        assert session.last_seen_at is None and session.revision == 0
