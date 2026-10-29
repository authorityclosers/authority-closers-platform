"""Admin plan prices (owner, 29 Oct 2026: "Admin price editor"): admin surface, operations
workspace, private and never cached; only the owner changes a price, from this Admin page,
against the revision read, with a reason, and each change is audited with old and new."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.routes import RouteContext, plan_prices
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.plans import admin_http

OPS, OTHER = UUID(int=1), UUID(int=2)
WRITE = {"Origin": "https://admin.test"}
SEAT_PRICE = {
    "expected_revision": 3,
    "monthly_price_paise": 199_900,
    "yearly_price_paise": 1_999_000,
    "reason": "Owner approved ₹1,999 per seat",
}


@asynccontextmanager
async def _client(
    *, tenant: UUID = OPS, operations: UUID | None = OPS
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
    )
    app = FastAPI()
    register_problem_handlers(app)
    plan_prices.install(
        app,
        RouteContext(settings=settings, require_actor=require_actor, sessions=cast(Any, None)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.test"
    ) as client:
        yield client


STATE: dict[str, Any] = {}
CHANGED: list[dict[str, Any]] = []
AUDITED: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _admitted(monkeypatch: pytest.MonkeyPatch) -> None:
    STATE.clear()
    STATE.update(owner=True, revision=3)
    CHANGED.clear()
    AUDITED.clear()

    async def admit(_service: Any, _actor: Any) -> None:
        return None

    async def is_price_owner(_db: Any, _person_id: Any) -> bool:
        return bool(STATE["owner"])

    async def price_view(_db: Any, *, environment: str, can_change: bool) -> dict[str, Any]:
        return {"environment": environment, "can_change": can_change, "plans": [], "history": []}

    async def change_price(
        _db: Any, *, key: str, command: Any, person_id: Any, now: Any
    ) -> tuple[Any, dict[str, Any], dict[str, Any]]:
        if key != "organisation":
            raise admin_http.PriceRefused(404, "There is no plan with that key.")
        if command.expected_revision != STATE["revision"]:
            raise admin_http.PriceRefused(409, "This plan changed. Refresh and try again.")
        STATE["revision"] += 1
        CHANGED.append({"key": key, "reason": command.reason})
        plan = type("Plan", (), {"key": key, "revision": STATE["revision"]})()
        before = {"monthly_price_paise": 1_000_000, "yearly_price_paise": 10_800_000}
        after = {
            "monthly_price_paise": command.monthly_price_paise,
            "yearly_price_paise": command.yearly_price_paise,
        }
        return plan, before, after

    async def append_for_actor(_repo: Any, _actor: Any, **event: Any) -> None:
        AUDITED.append(event)

    monkeypatch.setattr(ConversationProviderAdmin, "admit", admit)
    monkeypatch.setattr(admin_http, "is_price_owner", is_price_owner)
    monkeypatch.setattr(admin_http, "price_view", price_view)
    monkeypatch.setattr(admin_http, "change_price", change_price)
    monkeypatch.setattr(AuditRepository, "__init__", lambda self, _db: None)
    monkeypatch.setattr(AuditRepository, "append_for_actor", append_for_actor)


async def test_admins_read_prices_privately_in_the_operations_workspace() -> None:
    async with _client() as client:
        response = await client.get("/v1/admin/plan-prices")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json() == {
            "environment": "test",
            "can_change": True,
            "plans": [],
            "history": [],
        }
        assert (await client.get("/v1/admin/plan-prices", params={"x": "1"})).status_code == 422
        STATE["owner"] = False
        assert (await client.get("/v1/admin/plan-prices")).json()["can_change"] is False
    async with _client(tenant=OTHER) as client:
        assert (await client.get("/v1/admin/plan-prices")).status_code == 403
    async with _client(operations=None) as client:
        assert (await client.get("/v1/admin/plan-prices")).status_code == 403


async def test_the_owner_changes_a_price_once_audited_with_old_and_new() -> None:
    async with _client() as client:
        response = await client.put(
            "/v1/admin/plan-prices/organisation", json=SEAT_PRICE, headers=WRITE
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert [{"key": "organisation", "reason": SEAT_PRICE["reason"]}] == CHANGED
        assert [
            {
                "action": "plans.price_changed",
                "resource_type": "plan",
                "resource_id": "organisation",
                "payload": {
                    "plan_key": "organisation",
                    "from_revision": 3,
                    "to_revision": 4,
                    "old": {"monthly_price_paise": 1_000_000, "yearly_price_paise": 10_800_000},
                    "new": {"monthly_price_paise": 199_900, "yearly_price_paise": 1_999_000},
                },
                "reason": SEAT_PRICE["reason"],
            }
        ] == AUDITED
        # The same request again is stale: the plan moved to revision 4.
        stale = await client.put(
            "/v1/admin/plan-prices/organisation", json=SEAT_PRICE, headers=WRITE
        )
        assert stale.status_code == 409
        missing = await client.put(
            "/v1/admin/plan-prices/nowhere",
            json={**SEAT_PRICE, "expected_revision": 4},
            headers=WRITE,
        )
        assert missing.status_code == 404
    assert len(CHANGED) == 1 and len(AUDITED) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"monthly_price_paise": 0},
        {"yearly_price_paise": -1},
        {"monthly_price_paise": 100_000_001},
        {"monthly_price_paise": "199900"},
        {"monthly_price_paise": 1999.5},
        {"expected_revision": 0},
        {"reason": ""},
        {"reason": "   "},
        {"reason": "x" * 301},
        {"currency": "INR"},
    ],
)
async def test_bad_prices_and_reasons_are_refused(change: dict[str, Any]) -> None:
    async with _client() as client:
        response = await client.put(
            "/v1/admin/plan-prices/organisation", json={**SEAT_PRICE, **change}, headers=WRITE
        )
        assert response.status_code == 422, change
    assert CHANGED == [] and AUDITED == []


async def test_only_the_owner_changes_prices_and_only_from_this_admin_page() -> None:
    async with _client() as client:
        foreign = await client.put("/v1/admin/plan-prices/organisation", json=SEAT_PRICE)
        assert foreign.status_code == 403
        STATE["owner"] = False
        refused = await client.put(
            "/v1/admin/plan-prices/organisation", json=SEAT_PRICE, headers=WRITE
        )
        assert refused.status_code == 403
        assert "Only the owner" in refused.json()["detail"]
    async with _client(tenant=OTHER) as client:
        STATE["owner"] = True
        other = await client.put(
            "/v1/admin/plan-prices/organisation", json=SEAT_PRICE, headers=WRITE
        )
        assert other.status_code == 403
    assert CHANGED == [] and AUDITED == []
