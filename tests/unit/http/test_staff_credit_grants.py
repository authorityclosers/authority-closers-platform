"""Admin credit grant boundary with real cookie/capability reads and fictional targets."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session

from ac_platform.billing.credit_grants import CreditGrantReceipt
from ac_platform.billing.errors import BillingForbidden
from ac_platform.billing.ledger import BillingConflict, BillingError
from ac_platform.billing.models import BillingAccount
from ac_platform.http import staff_billing
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform import install_platform_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.staff_billing import install_staff_billing_http
from tests.unit.http.test_platform_access import grant
from tests.unit.http.test_workspaces import TOKEN, HttpDatabase
from tests.unit.http.test_workspaces import workspace_state as workspace_state

ORIGIN = "https://admin.authorityclosers.test"
BODY = {"quantity": "1.25", "reason": "Fictional support grant"}


@pytest.fixture
def credit_http_state(workspace_state, monkeypatch):
    state = workspace_state
    state.settings = state.settings.model_copy(
        update={
            "operations_tenant_id": state.tenants["Other"],
            "public_learner_tenant_id": state.tenants["Alpha"],
        }
    )
    state.account, state.own = uuid4(), uuid4()
    with Session(state.engine) as db, db.begin():
        db.add_all(
            [
                BillingAccount(
                    id=state.account,
                    tenant_id=state.tenants["Beta"],
                    kind="organisation",
                    person_id=None,
                    created_at=datetime.now(UTC),
                ),
                BillingAccount(
                    id=state.own,
                    tenant_id=state.tenants["Alpha"],
                    kind="personal",
                    person_id=state.person,
                    created_at=datetime.now(UTC),
                ),
            ]
        )

    @asynccontextmanager
    async def sessions():
        with Session(state.engine) as db:
            yield HttpDatabase(db)

    state.app = FastAPI()
    register_problem_handlers(state.app)
    actor = install_identity_http(state.app, settings=state.settings, sessions=cast(Any, sessions))
    install_platform_http(state.app, settings=state.settings, require_actor=actor)
    install_staff_billing_http(state.app, settings=state.settings, require_actor=actor)
    state.receipt = CreditGrantReceipt(
        uuid4(), state.account, Decimal("1.25"), "fictional:receipt", uuid4(), datetime.now(UTC)
    )
    state.command = AsyncMock(return_value=state.receipt)
    monkeypatch.setattr(staff_billing.CreditGrantService, "grant", state.command)
    return state


async def send(
    state,
    *,
    body=None,
    key="fictional-operation",
    token=TOKEN,
    origin=ORIGIN,
    host=ORIGIN,
    tenant=None,
    account=None,
    query="",
):
    headers = {}
    if token is not None:
        headers["cookie"] = f"ac_session={token}"
    if key is not None:
        headers["Idempotency-Key"] = key
    if origin is not None:
        headers["origin"] = origin
    target_tenant = tenant or state.tenants["Beta"]
    target_account = account or state.account
    path = f"/v1/platform/billing/accounts/{target_tenant}/{target_account}/credit-grants"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app), base_url=host
    ) as client:
        return await client.post(path + query, json=BODY if body is None else body, headers=headers)


async def test_authorised_http_call_uses_server_actor_exact_quantity_and_original_receipt(
    credit_http_state,
):
    state = credit_http_state
    await grant(state, "platform_access_manage")
    response = await send(state)
    assert response.status_code == 200, response.text
    assert response.json() == state.receipt.to_dict()
    assert response.headers["cache-control"] == "private, no-store"
    kwargs = state.command.await_args.kwargs
    assert kwargs["actor"].person_id == state.person
    assert kwargs["actor"].session_id == state.session
    assert kwargs["tenant_id"] == state.tenants["Beta"]
    assert kwargs["account_id"] == state.account
    assert kwargs["quantity"] == Decimal("1.25")
    assert kwargs["operation_id"] == "fictional-operation"
    assert kwargs["reason"] == BODY["reason"]


@pytest.mark.parametrize("permission", [None, "platform_billing_manage", "platform_tenants_read"])
async def test_other_authority_has_no_receipt_or_service_call(credit_http_state, permission):
    state = credit_http_state
    if permission:
        await grant(state, permission)
    response = await send(state)
    assert response.status_code == 403
    assert "account_id" not in response.json() and "quantity" not in response.json()
    state.command.assert_not_awaited()


@pytest.mark.parametrize("token", [None, "bad"])
async def test_unsigned_requests_are_refused(credit_http_state, token):
    response = await send(credit_http_state, token=token)
    assert response.status_code == 401
    credit_http_state.command.assert_not_awaited()


@pytest.mark.parametrize(
    "change",
    [
        {"host": "https://coach.authorityclosers.test"},
        {"host": "https://learner.authorityclosers.test"},
        {"host": "http://localhost"},
        {"origin": None},
        {"origin": "https://attacker.example.test"},
    ],
)
async def test_admin_surface_and_write_origin_are_required(credit_http_state, change):
    await grant(credit_http_state, "platform_access_manage")
    assert (await send(credit_http_state, **change)).status_code == 403
    credit_http_state.command.assert_not_awaited()


@pytest.mark.parametrize(
    "quantity",
    [
        1,
        1.25,
        True,
        None,
        "",
        "0",
        "-0",
        "-1",
        "NaN",
        "sNaN",
        "Infinity",
        "-Infinity",
        "1E+131072",
        "1E-16384",
        " 1",
        "1_0",
    ],
)
async def test_only_positive_finite_exact_strings_enter_service(credit_http_state, quantity):
    await grant(credit_http_state, "platform_access_manage")
    response = await send(credit_http_state, body=BODY | {"quantity": quantity})
    assert response.status_code == 422
    credit_http_state.command.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": "1.25"},
        BODY | {"reason": "  "},
        BODY | {"reason": "x" * 501},
        BODY | {"person_id": str(uuid4())},
        BODY | {"tenant_id": str(uuid4())},
        BODY | {"account_id": str(uuid4())},
        BODY | {"permissions": ["platform_access_manage"]},
        BODY | {"account_kind": "organisation"},
    ],
)
async def test_invalid_reason_and_client_authority_fields_are_refused(credit_http_state, body):
    await grant(credit_http_state, "platform_access_manage")
    assert (await send(credit_http_state, body=body)).status_code == 422
    credit_http_state.command.assert_not_awaited()


@pytest.mark.parametrize("key,status", [(None, 428), ("  ", 428), ("x" * 129, 422)])
async def test_stable_operation_header_is_required(credit_http_state, key, status):
    await grant(credit_http_state, "platform_access_manage")
    assert (await send(credit_http_state, key=key)).status_code == status
    credit_http_state.command.assert_not_awaited()


async def test_query_hints_and_mismatched_target_cannot_bypass_own_personal_refusal(
    credit_http_state,
):
    state = credit_http_state
    await grant(state, "platform_access_manage")
    for tenant in (state.tenants["Alpha"], state.tenants["Beta"]):
        assert (await send(state, account=state.own, tenant=tenant)).status_code == 403
    assert (await send(state, query="?account_kind=organisation")).status_code == 422
    state.command.assert_not_awaited()


@pytest.mark.parametrize(
    "error,status,code",
    [
        (BillingConflict("Different facts."), 409, "idempotency_conflict"),
        (BillingError("Invalid evidence."), 422, "validation_failed"),
        (BillingForbidden("Unavailable account."), 403, "billing_forbidden"),
    ],
)
async def test_service_errors_use_existing_problem_contract(credit_http_state, error, status, code):
    await grant(credit_http_state, "platform_access_manage")
    credit_http_state.command.side_effect = error
    response = await send(credit_http_state)
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "quantity" not in response.json()
