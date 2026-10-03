"""Admin → Billing staff read: capability admission and strict shape (AUT-879, SQLite).

Fictional people, tenants and orders only.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from ac_platform.authorization.models import PLATFORM_CAPABILITIES
from ac_platform.billing.models import BillingAccount
from ac_platform.billing.order_models import BillingOrder, BillingOrderEvent
from ac_platform.http import staff_billing
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform import install_platform_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.staff_billing import install_staff_billing_http
from ac_platform.http.surfaces import CoachSurfaceMiddleware
from tests.unit.http.test_platform_access import grant, read
from tests.unit.http.test_workspaces import OTHER_TOKEN, HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state

PATH = "/v1/platform/billing"


@pytest.fixture
def billing_state(workspace_state):
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={"operations_tenant_id": state.tenants["Other"]}
    )

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    require_actor = install_identity_http(
        state.app, settings=state.settings, sessions=cast(Any, sessions)
    )
    install_platform_http(state.app, settings=state.settings, require_actor=require_actor)
    install_staff_billing_http(state.app, settings=state.settings, require_actor=require_actor)
    state.app.add_middleware(CoachSurfaceMiddleware, settings=state.settings)
    return state


@pytest.fixture
def billing_staff(billing_state, monkeypatch):
    """The capability as #203 registers it; the real grant is covered below once it lands."""

    real = staff_billing.platform_projection

    async def projection(*args: Any, **kwargs: Any) -> frozenset[str]:
        return (await real(*args, **kwargs)) | {"platform_billing_manage"}

    monkeypatch.setattr(staff_billing, "platform_projection", projection)
    return billing_state


def add_order(state) -> tuple[str, str]:
    now = datetime.now(UTC)
    account, order = uuid4(), uuid4()
    with Session(state.engine) as db, db.begin():
        db.add(
            BillingAccount(
                id=account,
                tenant_id=state.tenants["Alpha"],
                person_id=None,
                kind="organisation",
                created_at=now,
            )
        )
        db.flush()
        db.add(
            BillingOrder(
                id=order,
                account_id=account,
                kind="subscription",
                mode="test",
                provider="fake",
                order_ref="ord_fictional_0001",
                provider_order_ref=None,
                subscription_id=None,
                plan_key="team",
                plan_name="Team (fictional)",
                plan_revision=1,
                interval="month",
                seats=3,
                pack_key=None,
                minutes=90,
                amount_minor=749_700,
                currency="INR",
                gst_inclusive=True,
                created_by_person_id=None,
                created_at=now,
                expires_at=now + timedelta(minutes=30),
            )
        )
        db.flush()
        db.add(
            BillingOrderEvent(
                id=uuid4(),
                order_id=order,
                status="paid",
                payment_event_id=None,
                detail=None,
                actor_type="provider",
                created_at=now,
            )
        )
    return str(account), str(order)


async def test_person_without_billing_capability_gets_403(billing_state):
    response = await read(billing_state, PATH)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"
    assert "orders" not in response.json()


async def test_other_platform_capability_is_not_billing(billing_state):
    await grant(billing_state, "platform_tenants_read")
    assert (await read(billing_state, PATH)).status_code == 403


async def test_tenant_owner_is_not_billing_staff(billing_state):
    assert (await read(billing_state, PATH, token=OTHER_TOKEN)).status_code == 403


@pytest.mark.parametrize("host", ["coach", "learner", "internal"])
async def test_other_surfaces_are_refused(billing_staff, host):
    response = await read(billing_staff, PATH, host=host)
    assert response.status_code == 403
    assert "orders" not in response.json()


@pytest.mark.parametrize("token", [None, "bad"])
async def test_signed_out_gets_401(billing_state, token):
    response = await read(billing_state, PATH, token=token)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "private, no-store"


async def test_query_parameters_are_refused(billing_staff):
    response = await read(billing_staff, PATH, params={"limit": "5"})
    assert response.status_code in (400, 422)
    assert "orders" not in response.json()


async def test_empty_overview_is_honest(billing_staff):
    response = await read(billing_staff, PATH)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "generated_at",
        "page_limit",
        "orders",
        "payments",
        "refunds",
        "subscriptions",
    }
    assert (body["orders"], body["payments"], body["refunds"], body["subscriptions"]) == (
        [],
        [],
        [],
        [],
    )
    assert body["page_limit"] == 100
    assert response.headers["cache-control"] == "private, no-store"


async def test_billing_staff_see_orders_with_customer_plan_seats_and_gst(billing_staff):
    account, order = add_order(billing_staff)
    response = await read(billing_staff, PATH)
    assert response.status_code == 200
    (row,) = response.json()["orders"]
    assert row["order_id"] == order
    assert row["customer"] == {
        "account_id": account,
        "kind": "organisation",
        "name": "Alpha",
        "email": None,
    }
    assert (row["plan_name"], row["seats"], row["amount_minor"], row["currency"]) == (
        "Team (fictional)",
        3,
        749_700,
        "INR",
    )
    assert (row["gst_inclusive"], row["status"], row["interval"]) == (True, "paid", "month")


@pytest.mark.skipif(
    "platform_billing_manage" not in PLATFORM_CAPABILITIES,
    reason="The capability is registered by AUT-869 (#203).",
)
async def test_real_billing_grant_admits(billing_state):
    await grant(billing_state, "platform_billing_manage")
    assert (await read(billing_state, PATH)).status_code == 200
