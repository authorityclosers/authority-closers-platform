from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from ac_platform.conversation_intelligence.budget_settings_models import (
    ConversationBudgetSetting,
)
from ac_platform.conversation_intelligence.entitlements import (
    SettlementReceipt,
    mark_dispatched,
    settle,
)
from ac_platform.http import conversation_execution_control as module
from tests.unit.conversation_intelligence.test_entitlements import reserved


@pytest.mark.parametrize("case", ["available", "exhausted", "overrun", "paused", "month_used"])
async def test_public_availability_is_non_sensitive_and_follows_durable_budget(monkeypatch, case):
    budget = reserved(cap=1000, max_cost_paise=1000 if case == "exhausted" else 100).budget
    if case == "overrun":
        # Existing ledger's overrun is canonical even when its numeric cap has room.
        value = reserved(cap=1000, max_cost_paise=100)
        value = mark_dispatched(value.minutes, value.budget, "reserve-a", "attempt-a", 200)
        value = settle(
            value.minutes,
            value.budget,
            "reserve-a",
            SettlementReceipt(
                reservation_id="reserve-a",
                quote_fingerprint=value.reservation.quote.fingerprint,
                provider_id=value.reservation.quote.provider_id,
                attempt_id="attempt-a",
                actual_seconds=0,
                actual_paise=101,
                receipt_ref="ref:overrun",
            ),
        )
        budget = value.budget
    ledger = SimpleNamespace(snapshot=budget.as_dict())
    # A monthly allowance of 100 paise, used by the open hold, while the lifetime cap has room.
    setting = (
        SimpleNamespace(revision=1, ceiling_paise=1000, period="monthly", period_cap_paise=100)
        if case == "month_used"
        else None
    )

    async def scalar(query):
        entity = query.column_descriptions[0]["entity"]
        return setting if entity is ConversationBudgetSetting else ledger

    database = SimpleNamespace(scalar=scalar)

    @asynccontextmanager
    async def context():
        yield database

    database.begin = context
    settings = SimpleNamespace(
        environment="test",
        operations_tenant_id=uuid4(),
        public_app_url=SimpleNamespace(host="learner.test"),
        sales_xray_app_url=SimpleNamespace(host="xray.test"),
    )
    monkeypatch.setattr(
        module, "execution_state", AsyncMock(return_value={"paused": case == "paused"})
    )
    monkeypatch.setattr(
        module,
        "load_pinned_approval",
        lambda _: SimpleNamespace(
            environment="test",
            provider_control_tenant_id=settings.operations_tenant_id,
            budget_scope_id=uuid4(),
            budget_cap_paise=1000,
        ),
    )

    async def require_actor():
        raise HTTPException(401, "Sign in")

    app = FastAPI()
    module.install_execution_control_http(
        app, settings=settings, sessions=context, require_actor=require_actor
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://xray.test"
    ) as client:
        response = await client.get("/v1/conversation/acquisition/availability")
        assert response.status_code == 200
        assert response.json() == {"paused": case != "available"}
        assert response.headers["cache-control"] == "no-store"
        assert (
            await client.get("http://other.test/v1/conversation/acquisition/availability")
        ).status_code == 404
        assert (
            await client.get("/v1/conversation/acquisition/availability?tenant_id=other")
        ).status_code == 404
        assert (await client.get("/v1/admin/conversation/execution")).status_code == 401


async def test_public_availability_reads_the_database_once_per_window(monkeypatch):
    # Every open page polls this; a burst of polls inside the window costs one read.
    clock = [1000.0]
    monkeypatch.setattr(module, "monotonic", lambda: clock[0])
    state = AsyncMock(return_value={"paused": False})
    monkeypatch.setattr(module, "execution_state", state)

    def no_approval(_):
        raise ValueError("no pinned approval")

    monkeypatch.setattr(module, "load_pinned_approval", no_approval)

    @asynccontextmanager
    async def context():
        yield database

    database = SimpleNamespace(begin=context)
    settings = SimpleNamespace(
        environment="test",
        operations_tenant_id=uuid4(),
        public_app_url=SimpleNamespace(host="learner.test"),
        sales_xray_app_url=SimpleNamespace(host="xray.test"),
    )

    async def require_actor():
        raise HTTPException(401, "Sign in")

    app = FastAPI()
    module.install_execution_control_http(
        app, settings=settings, sessions=context, require_actor=require_actor
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://xray.test"
    ) as client:
        path = "/v1/conversation/acquisition/availability"
        for _ in range(5):
            assert (await client.get(path)).json() == {"paused": False}
        assert state.await_count == 1
        state.return_value = {"paused": True}
        clock[0] += module.AVAILABILITY_MEMO_SECONDS - 0.5
        assert (await client.get(path)).json() == {"paused": False}
        assert state.await_count == 1
        clock[0] += 1.0
        response = await client.get(path)
        assert response.json() == {"paused": True}
        assert response.headers["cache-control"] == "no-store"
        assert state.await_count == 2
        # Refusals never touch the database.
        assert (await client.get(f"{path}?tenant_id=other")).status_code == 404
        assert state.await_count == 2


@pytest.mark.parametrize(
    "intent",
    [
        {"paused": "true", "expected_revision": 0},
        {"paused": True, "expected_revision": True},
        {"paused": True, "expected_revision": 0, "tenant_id": "foreign"},
    ],
)
def test_control_intent_rejects_coercion_and_client_scope(intent):
    with pytest.raises(ValidationError):
        module.ExecutionControlIntent.model_validate(intent)
