"""The Admin company view (AUT-1798): served organisations only, operations accounts only."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

import ac_platform.http.conversation_insights as routes
from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext

OPS, PERSONAL, ORGANISATION = (UUID(int=index) for index in range(1, 4))


@pytest.fixture
async def admin_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, Any]]]:
    actor = ActorContext(uuid4(), uuid4(), OPS, frozenset({"admin_surface"}))
    resolved = ResolvedActorContext(
        actor=actor, membership_role="admin", person_revision=1, session_revision=1
    )
    seen: dict[str, Any] = {"admitted": 0}

    async def require_actor(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        yield AuthenticatedTransaction(
            database=cast(Any, object()),
            identity=cast(Any, object()),
            resolved=resolved,
            token=str(uuid4()),
        )

    async def admit(_service: Any, who: Any) -> None:
        assert who == actor
        seen["admitted"] += 1

    async def listed(database: Any, tenant_ids: Any) -> list[dict[str, Any]]:
        seen["served"] = set(tenant_ids)
        return [
            {"id": str(ORGANISATION), "name": "Fictional Org", "sandbox": False},
            {"id": str(PERSONAL), "name": "Personal", "sandbox": False},
        ]

    class Insights:
        def __init__(self, tenant_id: UUID) -> None:
            self.tenant_id = tenant_id

        async def overview(self, filters: Any, *, now: Any) -> dict[str, Any]:
            seen.update(tenant=self.tenant_id, filters=filters)
            return {"totals": {"calls": 1}}

        async def calls(self, filters: Any, *, offset: int) -> dict[str, Any]:
            seen.update(offset=offset)
            return {"items": []}

        async def refresh(self, *, now: Any) -> dict[str, Any]:
            return {"projected": 0, "pending": 0}

    def insights(database: Any, who: ActorContext, tenant_id: UUID) -> Insights:
        assert who.tenant_id == OPS
        return Insights(tenant_id)

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    monkeypatch.setattr(routes, "insight_organisations", listed)
    monkeypatch.setattr(routes, "tenant_insights", insights)
    storage = PrivateLocalRecordingStorage(tmp_path / "storage")
    intake = ConversationIntakeRuntime(
        policy=IntakePolicy(
            budget_scope_id=uuid4(),
            tenant_ids=frozenset({ORGANISATION, OPS}),
            authorization_ref="ref:fictional/intake",
            retention_ref="ref:fictional/retention",
        ),
        storage=storage,
        scratch=PrivateLocalRecordingStorage(tmp_path / "scratch"),
    )
    settings = Settings(
        _env_file=None,
        environment="test",
        admin_app_url="https://admin.test",
        operations_tenant_id=OPS,
        public_learner_tenant_id=PERSONAL,
    )
    app = FastAPI()
    register_problem_handlers(app)
    routes.install_insights_routes(
        app,
        settings=settings,
        require_actor=require_actor,
        intake=intake,
        acquisition_intake=None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        yield client, seen


async def test_company_view_opens_only_served_organisations(admin_client) -> None:
    client, seen = admin_client
    path = "/v1/admin/conversation/insights"
    first = await client.get(path)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["organisation"]["id"] == str(ORGANISATION)
    assert body["overview"] == {"totals": {"calls": 1}}
    # The operations workspace is never served; Personal and approved organisations are.
    assert seen["tenant"] == ORGANISATION and seen["served"] == {PERSONAL, ORGANISATION}
    assert seen["admitted"] == 1
    chosen = await client.get(path, params={"organisation": str(PERSONAL), "range": "30d"})
    assert chosen.status_code == 200 and seen["tenant"] == PERSONAL
    assert (await client.get(path, params={"organisation": str(uuid4())})).status_code == 404
    assert (await client.get(path, params={"days": "7"})).status_code == 422
    calls = await client.get(
        path + "/calls", params={"organisation": str(ORGANISATION), "offset": "50"}
    )
    assert calls.status_code == 200 and seen["offset"] == 50
    assert (await client.get(path + "/calls")).status_code == 422
    refresh = path + "/refresh?organisation=" + str(ORGANISATION)
    assert (await client.post(refresh)).status_code == 403
    origin = {"Origin": "https://admin.test"}
    assert (await client.post(refresh, headers=origin)).status_code == 200
    assert (await client.post(refresh + "&force=1", headers=origin)).status_code == 422


async def test_company_view_is_admin_host_only(admin_client) -> None:
    client, _seen = admin_client
    response = await client.get(
        "/v1/admin/conversation/insights", headers={"host": "salesxray.example.test"}
    )
    assert response.status_code in {403, 404}


async def test_admin_scope_follows_the_live_registry(admin_client, monkeypatch) -> None:
    """With the live registry (AUT-1694), Admin lists what it serves on each request."""
    from ac_platform.conversation_intelligence import sales_xray_tenants

    client, seen = admin_client
    later = uuid4()
    live = {PERSONAL, ORGANISATION}

    async def active(settings: Any, database: Any) -> set[UUID]:
        return set(live)

    monkeypatch.setattr(sales_xray_tenants, "sales_xray_active_tenant_ids", active, raising=False)
    await client.get("/v1/admin/conversation/insights")
    assert seen["served"] == {PERSONAL, ORGANISATION}
    live.add(later)
    await client.get("/v1/admin/conversation/insights")
    assert seen["served"] == {PERSONAL, ORGANISATION, later}
