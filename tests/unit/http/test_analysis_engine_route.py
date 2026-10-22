"""Analysis engine route (22 Oct 2026): admin surface, production and 7 days by default,
bounded filters, the operations workspace only, private and never cached."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext, analysis_engine
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

OPS, OTHER = UUID(int=1), UUID(int=2)


@asynccontextmanager
async def _client(
    *, tenant: UUID = OPS, operations: UUID | None = OPS, store: str | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    actor = ActorContext(uuid4(), uuid4(), tenant, frozenset({"admin_surface"}))
    resolved = ResolvedActorContext(
        actor=actor, membership_role="admin", person_revision=1, session_revision=1
    )

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, object()),
            identity=cast(Any, object()),
            resolved=resolved,
            token=str(uuid4()),
        )

    settings = Settings(
        _env_file=None,
        environment="test",
        admin_app_url="https://admin.test",
        operations_tenant_id=operations,
        metrics_store_root=store,
    )
    app = FastAPI()
    register_problem_handlers(app)
    analysis_engine.install(
        app,
        RouteContext(settings=settings, require_actor=require_actor, sessions=cast(Any, None)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        yield client


async def test_engine_route_bounds_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def read_engine(service, actor, *, environment, days):
        seen.update(environment=environment, days=days, root=service.store_root)
        return {"environment": environment, "modules": []}

    monkeypatch.setattr(analysis_engine, "read_engine", read_engine)
    async with _client() as client:
        response = await client.get("/v1/admin/conversation/engine")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert seen == {"environment": "production", "days": 7, "root": None}
        response = await client.get(
            "/v1/admin/conversation/engine", params={"env": "development", "days": "30"}
        )
        assert response.status_code == 200 and seen["environment"] == "development"
        assert seen["days"] == 30
        for params in ({"env": "all"}, {"days": "0"}, {"days": "31"}, {"fx": "daily"}):
            response = await client.get("/v1/admin/conversation/engine", params=params)
            assert response.status_code == 422, params
        response = await client.get("/v1/admin/conversation/engine?days=7&days=8")
        assert response.status_code == 422
    async with _client(operations=None) as client:
        assert (await client.get("/v1/admin/conversation/engine")).status_code == 503


def _export(now: datetime) -> dict[str, Any]:
    at = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": "ac.sales-xray.usage-metrics/1",
        "environment": "development",
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": 14,
        "calls": [{"id": "call-1", "company": "c1", "at": at, "kind": "real", "facts": "facts-v2"}],
        "steps": [
            {
                "call": "call-1",
                "company": "c1",
                "stage": "C2",
                "status": "succeeded",
                "attempts": 1,
                "provider": "elevenlabs",
                "model": "scribe_v2",
                "usage": {},
                "audio_ms": 600_000,
                "at": at,
            }
        ],
    }


async def test_engine_reads_the_store_for_the_operations_workspace_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def admit(_service: Any, _actor: Any) -> None:
        return None

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    (tmp_path / "development").mkdir()
    (tmp_path / "development" / "usage.json").write_text(
        json.dumps(_export(datetime.now(UTC))), encoding="utf-8"
    )
    async with _client(store=str(tmp_path)) as client:
        response = await client.get("/v1/admin/conversation/engine", params={"env": "development"})
        assert response.status_code == 200
        body = response.json()
        assert body["registry"]["digest"] == registry.digest() and body["available"]
        assert body["window"]["calls"] == 1 and body["window"]["audio_minutes"] == 10.0
        [scribe] = body["modules"]
        assert scribe["id"] == "c2.scribe" and scribe["ratio"] == pytest.approx(1.0, abs=0.01)
        response = await client.get("/v1/admin/conversation/engine")
        assert response.status_code == 200 and response.json()["available"] is False
    async with _client(tenant=OTHER, store=str(tmp_path)) as client:
        assert (await client.get("/v1/admin/conversation/engine")).status_code == 403
