"""Additive strict credit wire contract and read-only dependency selection."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ac_platform.billing.credit_reads import CreditBalance, CreditEntry, CreditHistory
from ac_platform.billing.errors import BillingForbidden, CreditEntryNotFound
from ac_platform.http.auth import AuthenticatedTransaction, AuthenticationRequired
from ac_platform.http.billing import (
    CreditBalanceResponse,
    CreditEntryResponse,
    install_billing_http,
)
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.identity.services import (
    AccountUnavailableError,
    EmailVerificationRequiredError,
    InvalidSessionTokenError,
    SessionExpiredError,
    SessionRevokedError,
    TenantScopeDeniedError,
)
from ac_platform.kernel.authz import ActorContext
from tests.unit.http.test_billing_routes import _Commands, _settings


@pytest.fixture
def state(monkeypatch):
    actor = ActorContext(uuid4(), uuid4(), uuid4())
    database = AsyncMock()
    commands = _Commands()
    reads = AsyncMock()
    reads.balance.return_value = CreditBalance("personal", uuid4(), "1.25")
    reads.history.return_value = CreditHistory(
        "personal",
        reads.balance.return_value.account_id,
        [CreditEntry(uuid4(), "-0.25", datetime(2026, 10, 5, 9, tzinfo=UTC), None)],
        None,
    )
    monkeypatch.setattr("ac_platform.http.billing.CreditReads", lambda *_a, **_k: reads)
    failure = []

    async def require_actor(_request: Request):
        raise AssertionError("Credit GETs must not use writing authentication")

    async def read_only(_request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        if failure:
            raise failure[0]
        yield AuthenticatedTransaction(
            database,
            cast(Any, object()),
            ResolvedActorContext(actor, "owner", 0, 0, 0, 0),
            "fictional-test-token",
        )

    require_actor.read_only = read_only
    app = FastAPI()
    register_problem_handlers(app)
    install_billing_http(app, settings=_settings(), require_actor=require_actor, commands=commands)
    return TestClient(app), reads, commands, actor, failure


def test_final_response_shapes_and_default_read_only_caller(state):
    client, reads, commands, actor, _ = state
    balance = client.get("/v1/billing/credits")
    assert balance.status_code == 200, balance.text
    assert balance.json() == {
        "account": "personal",
        "account_id": str(reads.balance.return_value.account_id),
        "balance": "1.25",
    }
    history = client.get("/v1/billing/credits/history")
    assert history.status_code == 200, history.text
    row = reads.history.return_value.entries[0]
    assert history.json() == {
        "account": "personal",
        "account_id": balance.json()["account_id"],
        "entries": [
            {
                "entry_id": str(row.entry_id),
                "quantity": "-0.25",
                "created_at": "2026-10-05T09:00:00Z",
                "corrected_entry_id": None,
            }
        ],
        "next_before": None,
    }
    caller = reads.balance.await_args.args[0]
    assert (caller.person_id, caller.tenant_id) == (actor.person_id, actor.tenant_id)
    assert reads.history.await_args.kwargs == {"limit": 50, "before": None}
    assert commands.calls == []
    for response in (balance, history):
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
    assert client.post("/v1/billing/credits").status_code == 405


@pytest.mark.parametrize("path", ["", "/history"])
@pytest.mark.parametrize(
    "query",
    [
        "account=other",
        "account=",
        "tenant_id=x",
        "person_id=x",
        "account_id=x",
        "quantity=1",
        "source_ref=x",
    ],
)
def test_strict_selector_and_no_extra_query_parameters(state, path, query):
    client, reads, *_ = state
    response = client.get(f"/v1/billing/credits{path}?{query}")
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    reads.balance.assert_not_awaited()
    reads.history.assert_not_awaited()


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "limit=bad", "before=bad", "before=", "limit=1&unexpected=x"]
)
def test_invalid_page_query_is_problem_json(state, query):
    client, reads, *_ = state
    response = client.get(f"/v1/billing/credits/history?{query}")
    assert response.status_code == 422 and response.json()["code"] == "validation_failed"
    assert response.headers["content-type"] == "application/problem+json"
    reads.history.assert_not_awaited()


@pytest.mark.parametrize("limit", [1, 100])
def test_valid_org_history_query_is_passed_exactly(state, limit):
    client, reads, *_ = state
    cursor = uuid4()
    reads.history.return_value = CreditHistory("organisation", uuid4(), [], None)
    response = client.get(
        f"/v1/billing/credits/history?account=organisation&limit={limit}&before={cursor}"
    )
    assert response.status_code == 200
    assert reads.history.await_args.args[1] == "organisation"
    assert reads.history.await_args.kwargs == {"limit": limit, "before": cursor}


@pytest.mark.parametrize(
    "error,status,code",
    [
        (AuthenticationRequired("Fictional missing cookie"), 401, "authentication_required"),
        (InvalidSessionTokenError(), 401, "authentication_rejected"),
        (SessionExpiredError(), 401, "authentication_rejected"),
        (SessionRevokedError(), 401, "authentication_rejected"),
        (AccountUnavailableError(), 403, "billing_forbidden"),
        (EmailVerificationRequiredError(), 403, "billing_forbidden"),
        (TenantScopeDeniedError(), 403, "billing_forbidden"),
    ],
)
def test_auth_refusals_are_private_and_expose_no_credit(state, error, status, code):
    client, reads, _, _, failure = state
    failure.append(error)
    for path in ("", "/history"):
        response = client.get(f"/v1/billing/credits{path}")
        assert response.status_code == status and response.json()["code"] == code
        assert "quantity" not in response.json() and "balance" not in response.json()
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["vary"] == "Cookie"
    reads.balance.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        BillingForbidden("Fictional forbidden"),
        CreditEntryNotFound("That credit entry does not exist."),
    ],
)
def test_domain_refusals_use_existing_problem_envelope(state, error):
    client, reads, *_ = state
    reads.history.side_effect = error
    response = client.get("/v1/billing/credits/history")
    assert response.status_code == error.status and response.json()["code"] == error.code
    assert set(response.json()) == {
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "code",
        "request_id",
    }
    assert response.headers["vary"] == "Cookie"


def test_response_models_refuse_extra_metadata_and_numeric_quantities():
    with pytest.raises(ValidationError):
        CreditBalanceResponse(account="personal", account_id=None, balance=1.25)
    with pytest.raises(ValidationError):
        CreditEntryResponse(
            entry_id=uuid4(),
            quantity="1.25",
            created_at=datetime.now(UTC),
            corrected_entry_id=None,
            source_ref="private",
        )
