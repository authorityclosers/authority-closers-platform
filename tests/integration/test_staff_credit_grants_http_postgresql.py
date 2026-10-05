"""Fictional Admin HTTP grants commit or roll back against disposable PostgreSQL."""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select, update

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.billing import credits
from ac_platform.billing.credit_grants import CreditGrantService
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CREDIT_APPEND_ACTION, CreditsLedger
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import BillingOrder, BillingPaymentEvent, BillingSubscription
from ac_platform.http.auth import install_identity_http
from ac_platform.http.platform import install_platform_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.http.staff_billing import install_staff_billing_http
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Tenant
from tests.database.test_conversation_postgresql import run
from tests.database.test_credit_grants_postgresql import lab as grant_lab
from tests.database.test_credit_grants_postgresql import postgres_harness as postgres_harness
from tests.database.test_credit_grants_postgresql import staff

ORIGIN = "https://admin.authorityclosers.test"
BODY = {"quantity": "1.25", "reason": "Fictional HTTP support grant"}


@asynccontextmanager
async def lab(postgres_harness):
    async with grant_lab(postgres_harness) as state:
        state.settings = Settings(
            _env_file=None,
            environment="test",
            admin_app_url=ORIGIN,
            operations_tenant_id=state.operations.tenant_id,
            public_learner_tenant_id=state.owner.tenant_id,
        )
        state.token = await cookie(state, state.operator)
        state.app = FastAPI()
        register_problem_handlers(state.app)
        actor = install_identity_http(
            state.app, settings=state.settings, sessions=cast(Any, state.sessions)
        )
        install_platform_http(state.app, settings=state.settings, require_actor=actor)
        install_staff_billing_http(state.app, settings=state.settings, require_actor=actor)
        yield state


async def cookie(state, operator):
    token = uuid4().hex + "c" * 11
    pepper = state.settings.session_token_pepper.get_secret_value().encode()
    async with state.sessions() as database, database.begin():
        await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == operator.session_id)
            .values(token_hash=digest(pepper, token.encode(), sha256), selected_tenant_id=None)
        )
    return token


async def send(
    state, *, account=None, tenant=None, body=None, key="fictional-http-operation", token=None
):
    account = account or state.personal
    path = f"/v1/platform/billing/accounts/{tenant or account.tenant_id}/{account.id}/credit-grants"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=state.app, raise_app_exceptions=False), base_url=ORIGIN
    ) as client:
        return await client.post(
            path,
            json=BODY if body is None else body,
            headers={
                "cookie": f"ac_session={token or state.token}",
                "origin": ORIGIN,
                "Idempotency-Key": key,
            },
        )


async def counts(state):
    async with state.sessions() as database:
        return (
            await database.scalar(select(func.count()).select_from(BillingCreditEntry)),
            await database.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == CREDIT_APPEND_ACTION)
            ),
            await database.scalar(select(func.count()).select_from(BillingAccount)),
        )


@pytest.mark.parametrize("kind", ["personal", "organisation"])
def test_http_commits_exact_entry_and_original_staff_session_audit(postgres_harness, kind):
    async def exercise():
        async with lab(postgres_harness) as state:
            account = state.personal if kind == "personal" else state.pooled
            quantity = "123456789012345678901234567890.12345678901234567890123456789"
            models = (BillingLedgerEntry, BillingOrder, BillingPaymentEvent, BillingSubscription)
            async with state.sessions() as database, database.begin():
                before = [
                    await database.scalar(select(func.count()).select_from(m)) for m in models
                ]
                projection = await BillingLedger(database).project_person(
                    tenant_id=state.owner.tenant_id,
                    person_id=state.owner.person_id,
                    now=state.owner.now,
                )
            response = await send(state, account=account, body=BODY | {"quantity": quantity})
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            body = response.json()
            assert set(body) == {
                "entry_id",
                "account_id",
                "quantity",
                "source_ref",
                "audit_event_id",
                "created_at",
            }
            assert all(isinstance(value, str) for value in body.values())
            assert body["quantity"] == quantity and body["account_id"] == str(account.id)
            async with state.sessions() as database, database.begin():
                entry = await database.get(BillingCreditEntry, UUID(body["entry_id"]))
                audit = await database.get(AuditEvent, UUID(body["audit_event_id"]))
                assert entry.quantity == Decimal(quantity)
                assert entry.audit_event_id == audit.id
                assert entry.actor_person_id == audit.actor_person_id == state.operator.person_id
                assert entry.tenant_id == audit.tenant_id == account.tenant_id
                assert audit.session_id == state.operator.session_id
                assert audit.reason == entry.reason == BODY["reason"]
                assert audit.payload["source_ref"] == body["source_ref"]
                assert audit.payload["quantity"] == quantity
                assert (await AuditRepository(database).verify(account.tenant_id)).valid
                assert await CreditsLedger(database).balance(
                    tenant_id=account.tenant_id, account_id=account.id
                ) == Decimal(quantity)
                assert before == [
                    await database.scalar(select(func.count()).select_from(m)) for m in models
                ]
                after = await BillingLedger(database).project_person(
                    tenant_id=state.owner.tenant_id,
                    person_id=state.owner.person_id,
                    now=state.owner.now,
                )
                assert (after.available_seconds, after.plan_key, after.per_call_seconds) == (
                    projection.available_seconds,
                    projection.plan_key,
                    projection.per_call_seconds,
                )

    run(exercise())


@pytest.mark.parametrize(
    "failure", ["missing", "billing_permission", "revoked", "expired_session", "revoked_session"]
)
def test_http_rechecks_authority_and_never_returns_or_writes_credit(postgres_harness, failure):
    async def exercise():
        async with lab(postgres_harness) as state:
            token = state.token
            async with state.sessions() as database, database.begin():
                if failure == "revoked":
                    await CapabilityApplication(
                        database, operations_tenant_id=state.operations.tenant_id
                    ).revoke(
                        state.operator.actor,
                        command_id=uuid4(),
                        grant_id=state.capability.id,
                        reason="Fictional revoked authority",
                    )
                elif failure in {"expired_session", "revoked_session"}:
                    await database.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == state.operator.session_id)
                        .values(
                            **(
                                {
                                    "created_at": state.operator.now - timedelta(days=2),
                                    "expires_at": state.operator.now - timedelta(seconds=1),
                                }
                                if failure == "expired_session"
                                else {"revoked_at": state.operator.now}
                            )
                        )
                    )
            if failure in {"missing", "billing_permission"}:
                operator, _ = await staff(
                    state,
                    permission="platform_billing_manage"
                    if failure == "billing_permission"
                    else None,
                )
                token = await cookie(state, operator)
            before = await counts(state)
            response = await send(state, token=token)
            assert response.status_code == (
                401 if failure in {"expired_session", "revoked_session"} else 403
            ), response.text
            assert "quantity" not in response.json() and "account_id" not in response.json()
            assert await counts(state) == before

    run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "own_personal",
        "own_wrong_tenant",
        "mismatch",
        "missing",
        "inactive_learner",
        "suspended_org",
    ],
)
def test_http_target_refusals_create_no_account_entry_or_audit(postgres_harness, failure):
    async def exercise():
        async with lab(postgres_harness) as state:
            account, tenant = state.personal, None
            async with state.sessions() as database, database.begin():
                if failure.startswith("own_"):
                    database.add(
                        Membership(
                            tenant_id=state.owner.tenant_id,
                            person_id=state.operator.person_id,
                            role="learner",
                        )
                    )
                    await database.flush()
                    account = await BillingLedger(database).personal_account(
                        tenant_id=state.owner.tenant_id,
                        person_id=state.operator.person_id,
                        create=True,
                    )
                    if failure == "own_wrong_tenant":
                        tenant = state.pooled.tenant_id
                elif failure == "mismatch":
                    tenant = state.pooled.tenant_id
                elif failure == "missing":
                    account = BillingAccount(id=uuid4(), tenant_id=state.owner.tenant_id)
                elif failure == "inactive_learner":
                    await database.execute(
                        update(Person)
                        .where(Person.id == state.owner.person_id)
                        .values(status="suspended")
                    )
                elif failure == "suspended_org":
                    account = state.pooled
                    await database.execute(
                        update(Tenant)
                        .where(Tenant.id == account.tenant_id)
                        .values(status="suspended")
                    )
            before = await counts(state)
            response = await send(state, account=account, tenant=tenant)
            assert response.status_code == 403, response.text
            assert "quantity" not in response.json()
            assert await counts(state) == before

    run(exercise())


@pytest.mark.parametrize(
    "body",
    [
        BODY | {"quantity": "0"},
        BODY | {"quantity": "NaN"},
        BODY | {"quantity": "1E+2"},
        BODY | {"quantity": 1.25},
        BODY | {"reason": " "},
        BODY | {"actor": str(uuid4())},
    ],
)
def test_invalid_http_input_commits_neither_entry_nor_audit(postgres_harness, body):
    async def exercise():
        async with lab(postgres_harness) as state:
            before = await counts(state)
            assert (await send(state, body=body)).status_code == 422
            assert await counts(state) == before

    run(exercise())


def test_http_replay_conflict_and_separate_session_concurrent_duplicates(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            token = uuid4().hex + "d" * 11
            session_id = uuid4()
            async with state.sessions() as database, database.begin():
                database.add(
                    IdentitySession(
                        id=session_id,
                        person_id=state.operator.person_id,
                        token_hash=digest(
                            state.settings.session_token_pepper.get_secret_value().encode(),
                            token.encode(),
                            sha256,
                        ),
                        created_at=state.operator.now,
                        expires_at=state.operator.now + timedelta(days=1),
                    )
                )
            before = await counts(state)
            first = await send(state)
            assert first.status_code == 200, first.text
            assert (await send(state, token=token)).json() == first.json()
            for change in ({"quantity": "2.5"}, {"reason": "Changed evidence"}):
                conflict = await send(state, body=BODY | change)
                assert (
                    conflict.status_code == 409
                    and conflict.json()["code"] == "idempotency_conflict"
                )
            # Separate authenticated sessions reach the account serialisation fence.
            pair = await asyncio.wait_for(
                asyncio.gather(
                    send(state, key="concurrent-operation"),
                    send(state, token=token, key="concurrent-operation"),
                ),
                timeout=15,
            )
            assert all(response.status_code == 200 for response in pair), [r.text for r in pair]
            assert pair[0].json() == pair[1].json()
            after = await counts(state)
            assert after == (before[0] + 2, before[1] + 2, before[2])
            async with state.sessions() as database:
                audit = await database.get(AuditEvent, UUID(first.json()["audit_event_id"]))
                assert audit.session_id == state.operator.session_id
                assert audit.actor_person_id == state.operator.person_id

    run(exercise())


@pytest.mark.parametrize("failure", ["audit", "after_append"])
def test_failed_http_transaction_rolls_back_credit_and_audit(
    postgres_harness, monkeypatch, failure
):
    async def fail_audit(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")

    original = CreditGrantService.grant

    async def fail_after_append(self, **kwargs):
        await original(self, **kwargs)
        raise RuntimeError("Synthetic caller failure after append")

    async def exercise():
        async with lab(postgres_harness) as state:
            before = await counts(state)
            with monkeypatch.context() as patch:
                if failure == "audit":
                    patch.setattr(credits, "append_audit_event", fail_audit)
                else:
                    patch.setattr(CreditGrantService, "grant", fail_after_append)
                assert (await send(state)).status_code == 500
            assert await counts(state) == before
            # Retrying the failed operation succeeds once, without a dangling marker.
            assert (await send(state)).status_code == 200
            assert await counts(state) == (before[0] + 1, before[1] + 1, before[2])

    run(exercise())
