"""Fictional staff refunds through HTTP, real identity locks, ledger and audit."""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.models import CapabilityRevocation
from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.http.auth import AuthenticatedTransaction
from ac_platform.http.billing import install_billing_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.application import AsyncIdentityApplication
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.payments.ports import AmbiguousPaymentOutcomeError
from tests.database.test_billing_settlement_postgresql import (
    PERIOD_SECONDS,
    TRIAL_SECONDS,
    Lab,
    World,
    caller,
    scenario,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world
from tests.database.test_conversation_postgresql import ActorFixture, seed
from tests.unit.http.test_billing_routes import _settings

REASON = "Fictional customer requested refund through support"
HEADERS = {"Origin": "https://admin.authorityclosers.test", "Idempotency-Key": "staff-refund"}


async def staff(lab: Lab, *, granted: bool = True):
    actor = await seed(lab.engine, tenant_id=lab.world.operations_tenant_id, role="support")
    grant = None
    if granted:
        async with lab.sessions() as database, database.begin():
            grant = await CapabilityApplication(
                database, operations_tenant_id=lab.world.operations_tenant_id
            )._insert_grant(
                actor.person_id,
                actor.session_id,
                uuid4(),
                actor.person_id,
                "platform_billing_manage",
                CapabilityScope("platform"),
                "Fictional billing staff assignment",
            )
    return actor, grant


async def client(lab: Lab, actor: ActorFixture) -> httpx.AsyncClient:
    settings = _settings().model_copy(
        update={"operations_tenant_id": lab.world.operations_tenant_id}
    )
    token = uuid4().hex * 2
    pepper = settings.session_token_pepper.get_secret_value()
    async with lab.sessions() as database, database.begin():
        await database.execute(
            update(IdentitySession)
            .where(IdentitySession.id == actor.session_id)
            .values(token_hash=hmac.new(pepper.encode(), token.encode(), hashlib.sha256).digest())
        )

    async def require_actor(request: Request):
        async with lab.sessions() as database, database.begin():
            identity = AsyncIdentityApplication(database, token_pepper=pepper)
            resolved = await identity.resolve_actor(token)
            yield AuthenticatedTransaction(database, identity, resolved, token)

    app = FastAPI()
    register_problem_handlers(app)
    install_billing_http(app, settings=settings, require_actor=require_actor, commands=lab.app)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://admin.authorityclosers.test"
    )


@pytest.mark.parametrize("ambiguous", [False, True], ids=["processed", "lost-response"])
def test_staff_refunds_another_person_with_one_provider_call_and_durable_audit(
    postgres_harness, world: World, monkeypatch, ambiguous
):
    async def exercise(lab: Lab):
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, "staff-success")
        operator, _ = await staff(lab)
        calls = 0
        original_refund = world.fake.refund

        async def lost_answer(**kwargs):
            nonlocal calls
            calls += 1
            events = await lab.refund_events(paid.order_id)
            assert events[0].actor_person_id == operator.person_id
            assert events[0].reason == REASON
            assert events[0].actor_type == "person"
            if ambiguous:
                raise AmbiguousPaymentOutcomeError("Fictional timeout after refund acceptance")
            return await original_refund(**kwargs)

        monkeypatch.setattr(world.fake, "refund", lost_answer)
        path = f"/v1/platform/billing/payments/{paid.payment_ref}/refund"
        async with await client(lab, operator) as http:
            denied = await http.post(
                f"/v1/payments/{paid.payment_ref}/refund", json={"reason": REASON}, headers=HEADERS
            )
            assert denied.status_code == 404
            first = await http.post(path, json={"reason": REASON}, headers=HEADERS)
            assert first.status_code == 202, first.text
            replay = await http.post(path, json={"reason": REASON}, headers=HEADERS)
            assert replay.json() == first.json()
            other_key = await http.post(
                path, json={"reason": REASON}, headers=HEADERS | {"Idempotency-Key": "another"}
            )
            assert other_key.json()["refund"]["state"] == ("pending" if ambiguous else "refunded")
            conflict = await http.post(path, json={"reason": "Different"}, headers=HEADERS)
            assert conflict.status_code == 409
        assert calls == 1
        assert all(
            event.actor_person_id == operator.person_id and event.reason == REASON
            for event in await lab.refund_events(paid.order_id)
        )
        assert (await lab.lots(learner))[f"order:{paid.order_id}"].capacity == 0
        async with lab.sessions() as database, database.begin():
            rows = list(
                await database.scalars(
                    select(AuditEvent).where(
                        AuditEvent.actor_person_id == operator.person_id,
                        AuditEvent.action == "billing.staff_refund_requested",
                    )
                )
            )
            assert len(rows) == 1
            audit = rows[0]
            assert audit.session_id == operator.session_id
            assert audit.reason == REASON
            assert audit.payload["payment_id"] == paid.payment_ref
            assert audit.payload["order_id"] == str(paid.order_id)
            holds = [e for e in await lab.entries(learner) if e.kind == "refund_hold"]
            assert len(holds) == 1
            assert audit.payload["account_id"] == str(holds[0].account_id)
            assert holds[0].audit_event_id == audit.id
            assert (await AuditRepository(database).verify(learner.tenant_id)).valid

    scenario(postgres_harness, world, exercise)


@pytest.mark.parametrize("failure", ["outside_window", "minutes_used"])
def test_staff_and_customer_have_the_same_refusal(postgres_harness, world: World, failure):
    async def exercise(lab: Lab):
        learner = await lab.learner()
        await lab.subscribe_and_pay(learner)
        paid = await lab.top_up_and_pay(learner, failure)
        operator, _ = await staff(lab)
        if failure == "outside_window":
            world.clock.now = paid.paid_at + timedelta(days=7, seconds=1)
        else:
            await lab.reserve(learner, TRIAL_SECONDS)
            await lab.reserve(learner, PERIOD_SECONDS + 1)
        async with await client(lab, learner) as customer, await client(lab, operator) as admin:
            customer_result = await customer.post(
                f"/v1/payments/{paid.payment_ref}/refund", json={"reason": REASON}, headers=HEADERS
            )
            staff_result = await admin.post(
                f"/v1/platform/billing/payments/{paid.payment_ref}/refund",
                json={"reason": REASON},
                headers=HEADERS,
            )
            expected = 422 if failure == "outside_window" else 409
            assert staff_result.status_code == customer_result.status_code == expected
            assert staff_result.json()["code"] == customer_result.json()["code"]
        assert await lab.refund_events(paid.order_id) == []
        assert lab.provider_refunds(paid.order_ref) == []

    scenario(postgres_harness, world, exercise)


def test_missing_and_revoked_capability_denied_before_payment_lookup(
    postgres_harness, world: World
):
    async def exercise(lab: Lab):
        operator, _ = await staff(lab, granted=False)
        path = "/v1/platform/billing/payments/unknown/refund"
        async with lab.sessions() as database, database.begin():
            with pytest.raises(CapabilityDenied):
                await lab.app.staff_refund_payment(
                    database,
                    caller(operator),
                    "unknown",
                    reason=REASON,
                    idempotency_key="direct-command",
                )
        async with await client(lab, operator) as http:
            assert (
                await http.post(path, json={"reason": REASON}, headers=HEADERS)
            ).status_code == 403
        operator, grant = await staff(lab)
        async with await client(lab, operator) as http:
            assert (
                await http.post(path, json={"reason": REASON}, headers=HEADERS)
            ).status_code == 404
            async with lab.sessions() as database, database.begin():
                audit = await AuditRepository(database).append(
                    tenant_id=world.operations_tenant_id,
                    actor_person_id=operator.person_id,
                    action="authorization.capability_revoked",
                    resource_type="capability_grant",
                    resource_id=grant.id,
                    reason="Fictional revocation",
                    now=world.clock(),
                )
                database.add(
                    CapabilityRevocation(
                        id=uuid4(),
                        grant_id=grant.id,
                        revoked_by_person_id=operator.person_id,
                        audit_event_id=audit.id,
                        reason="Fictional revocation",
                        created_at=world.clock(),
                    )
                )
            assert (
                await http.post(path, json={"reason": REASON}, headers=HEADERS)
            ).status_code == 403

    scenario(postgres_harness, world, exercise)
