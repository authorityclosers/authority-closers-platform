"""Economics route (23 Oct 2026): admin surface, operations workspace, bounded filters,
private and never cached; prices from the plans table, costs from the store and registry."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.economics import service
from ac_platform.economics.model import PlanTerms
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext, economics
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

OPS, OTHER = UUID(int=1), UUID(int=2)
PERSONAL = PlanTerms(
    key="personal",
    name="Personal",
    per_seat=False,
    prices_include_gst=True,
    monthly_paise=249_900,
    yearly_paise=None,
    minutes=800,
)


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
    economics.install(
        app,
        RouteContext(settings=settings, require_actor=require_actor, sessions=cast(Any, None)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def _admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def admit(_service: Any, _actor: Any) -> None:
        return None

    async def active_plans(_db: Any) -> list[PlanTerms]:
        return [PERSONAL]

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    monkeypatch.setattr(service, "active_plans", active_plans)


async def test_economics_reads_plans_and_bounds_filters(tmp_path: Path) -> None:
    async with _client(store=str(tmp_path)) as client:
        response = await client.get("/v1/admin/economics")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert body["environment"] == "production" and body["days"] == 30
        assert body["settings"] == {"revision": None, "config": body["settings"]["config"]}
        # No export yet: the measured route is left out, the registry's routes remain.
        assert [row["id"] for row in body["routes"]] == [
            "today-brain4-read",
            "today-brain4-read-flex",
            "v2-flex-report-on-demand",
        ]
        assert [row["id"] for row in body["offers"]] == [
            "personal.monthly.web",
            "personal.monthly.play",
        ]
        assert body["offers"][0]["net"] == pytest.approx(2058.82, abs=0.01)
        response = await client.get("/v1/admin/economics", params={"env": "staging", "days": "7"})
        assert response.status_code == 200 and response.json()["environment"] == "staging"
        for params in ({"env": "all"}, {"days": "5"}, {"fx": "daily"}):
            response = await client.get("/v1/admin/economics", params=params)
            assert response.status_code == 422, params
    async with _client(tenant=OTHER, store=str(tmp_path)) as client:
        assert (await client.get("/v1/admin/economics")).status_code == 403
    async with _client(operations=None, store=str(tmp_path)) as client:
        assert (await client.get("/v1/admin/economics")).status_code == 403
