"""Selected-organisation purchase proof with fictional signed TEST payments."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import digest
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.models import BillingLedgerEntry
from ac_platform.billing.order_models import BillingOrder, BillingPeriod, BillingSubscription
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement as Settlement,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.http.auth import install_identity_http
from ac_platform.http.billing import install_billing_http, install_billing_webhook_http
from ac_platform.http.organisation import install_organisation_http
from ac_platform.http.problem import register_problem_handlers
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from ac_platform.organisations.usage import paid_seats
from ac_platform.payments.ports import Money
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.database.test_billing_checkout_postgresql import (
    ENTERPRISE,
    ORGANISATION,
    PERSONAL,
    build_world,
    engine_for,
    postgres_harness,  # noqa: F401
)
from tests.database.test_conversation_postgresql import run, seed


def test_two_seat_purchase_invites_pool_and_renewal(postgres_harness):  # noqa: F811
    async def exercise():
        world = await build_world(postgres_harness)
        engine = engine_for(postgres_harness)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(UTC).replace(microsecond=0) - timedelta(seconds=1)
        world.clock.now = now
        world.app.service.catalogue = StaticCatalogue(
            (
                PERSONAL,
                replace(ORGANISATION, seat_min=2, included_minutes=1000),
                replace(
                    ENTERPRISE, status="active", monthly_price_paise=10000, included_minutes=1000
                ),
            )
        )
        settings = Settings(
            _env_file=None,
            environment="test",
            public_app_url="https://learner.authorityclosers.test",
            public_learner_tenant_id=world.public_tenant_id,
            operations_tenant_id=world.operations_tenant_id,
        )
        owner = world.learner
        owner_token, member_token = "o" * 43, "m" * 43

        def service(db):
            return OrganisationService(
                db,
                operations_tenant_id=world.operations_tenant_id,
                public_learner_tenant_id=world.public_tenant_id,
            )

        try:
            async with sessions() as db, db.begin():
                org = await service(db).create(
                    "Fictional paid team", owner.person_id, uuid4(), "AUT-881 test fixture"
                )
                identity = await db.get(IdentitySession, owner.session_id)
                identity.selected_tenant_id = org.tenant_id
                identity.token_hash = digest(
                    settings.session_token_pepper.get_secret_value().encode(),
                    owner_token.encode(),
                    sha256,
                )
            app = FastAPI()
            register_problem_handlers(app)
            actor = install_identity_http(app, settings=settings, sessions=cast(Any, sessions))
            install_organisation_http(app, settings=settings, require_actor=actor)
            install_billing_http(app, settings=settings, require_actor=actor, commands=world.app)
            install_billing_webhook_http(app, sessions=sessions, commands=world.app)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url=str(settings.public_app_url),
            ) as client:
                headers = {
                    "cookie": f"ac_session={owner_token}",
                    "Origin": str(settings.public_app_url).rstrip("/"),
                }

                async def add(email, key=None):
                    return await client.post(
                        "/v1/organisation/members",
                        json={"email": email, "role": "member"},
                        headers=dict(headers, **{"Idempotency-Key": str(key or uuid4())}),
                    )

                assert (await client.get("/v1/organisation/usage", headers=headers)).json()[
                    "available_seconds"
                ] == 0
                assert (await client.get("/v1/organisation/billing", headers=headers)).json() == {
                    "paid_seats": 0,
                    "active_members": 1,
                    "pending_invites": 0,
                    "seats_available": 0,
                }
                refused = await add("unpaid@example.test")
                assert refused.status_code == 409 and refused.json()["code"] == "seats_full"
                # A catalogue with a lower legacy minimum cannot authorise <50 Enterprise seats.
                quote = dict(
                    kind="subscription",
                    account="organisation",
                    plan_key="enterprise",
                    interval="month",
                    seats=49,
                )
                response = await client.post(
                    "/v1/checkout",
                    json=quote,
                    headers=dict(headers, **{"Idempotency-Key": str(uuid4())}),
                )
                assert (
                    response.status_code == 422 and response.json()["code"] == "seats_out_of_range"
                )
                assert not world.provider.subscriptions
                quote.update(plan_key="organisation", seats=2)
                response = await client.post(
                    "/v1/checkout",
                    json=quote,
                    headers=dict(headers, **{"Idempotency-Key": str(uuid4())}),
                )
                assert response.status_code == 201
                order_id = UUID(response.json()["order"]["order_id"])
                async with sessions() as db:
                    order = await db.get(BillingOrder, order_id)
                    subscription = await db.get(BillingSubscription, order.subscription_id)
                callback_headers, body = world.provider.charge(
                    subscription.provider_subscription_ref,
                    event_id="org-first-charge",
                    order_reference=order.order_ref,
                    money=Money(order.amount_minor, "INR"),
                    period_start=now,
                    period_end=now + timedelta(days=30),
                )
                # Provider ACTIVE and an unverified browser return do not grant seats or minutes.
                assert (await client.get("/v1/organisation/billing", headers=headers)).json()[
                    "paid_seats"
                ] == 0
                assert (await add("still-unpaid@example.test")).json()["code"] == "seats_full"
                assert (
                    await client.post(
                        "/v1/payments/webhooks/fake",
                        content=body,
                        headers=callback_headers,
                    )
                ).json()["outcome"] == "paid"
                assert (
                    await client.post(
                        "/v1/payments/webhooks/fake",
                        content=body,
                        headers=callback_headers,
                    )
                ).json()["replayed"] is True
                assert (await client.get("/v1/organisation/usage", headers=headers)).json()[
                    "available_seconds"
                ] == 120000
                assert (await client.get("/v1/organisation/billing", headers=headers)).json()[
                    "paid_seats"
                ] == 2
                # Competing distinct invites cannot both take the last seat.
                keys = [uuid4(), uuid4()]
                responses = await asyncio.wait_for(
                    asyncio.gather(
                        add("first@example.test", keys[0]),
                        add("second@example.test", keys[1]),
                    ),
                    timeout=15,
                )
                assert sorted(r.status_code for r in responses) == [200, 409]
                winner = next(i for i, result in enumerate(responses) if result.status_code == 200)
                email = ["first@example.test", "second@example.test"][winner]
                assert (await add(email, keys[winner])).json() == responses[winner].json()
                assert (await add("third@example.test")).json()["code"] == "seats_full"
                # Explicit acceptance replaces the pending seat, not an extra seat.
                member = await seed(engine, tenant_id=world.public_tenant_id)
                async with sessions() as db, db.begin():
                    (await db.get(Person, member.person_id)).email = email
                    identity = await db.get(IdentitySession, member.session_id)
                    identity.selected_tenant_id = None
                    identity.token_hash = digest(
                        settings.session_token_pepper.get_secret_value().encode(),
                        member_token.encode(),
                        sha256,
                    )
                accepted = await client.post(
                    f"/v1/organisation/invites/{responses[winner].json()['invite_id']}/accept",
                    headers={
                        "Cookie": f"ac_session={member_token}",
                        "Origin": str(settings.public_app_url).rstrip("/"),
                        "Idempotency-Key": str(uuid4()),
                    },
                )
                assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
                async with sessions() as db, db.begin():
                    identity = await db.get(IdentitySession, member.session_id)
                    identity.selected_tenant_id = org.tenant_id
                    identity.token_hash = digest(
                        settings.session_token_pepper.get_secret_value().encode(),
                        member_token.encode(),
                        sha256,
                    )
                    usages = [
                        Usage(
                            id=uuid4(),
                            tenant_id=tenant,
                            person_id=member.person_id,
                            submission_id=uuid4(),
                            source_sha256="a" * 64,
                            duration_evidence_sha256="b" * 64,
                            reserved_seconds=seconds,
                            policy_revision="fictional",
                            created_at=now,
                        )
                        for tenant, seconds in [(org.tenant_id, 120), (world.public_tenant_id, 600)]
                    ]
                    db.add_all(usages)
                    await db.flush()
                    db.add(
                        Settlement(
                            usage_id=usages[0].id,
                            charged_seconds=60,
                            kind="completed",
                            receipt_sha256="c" * 64,
                            created_at=now,
                        )
                    )
                member_headers = {"cookie": f"ac_session={member_token}"}
                for actor_headers in [headers, member_headers]:
                    response = await client.get("/v1/organisation/usage", headers=actor_headers)
                    assert (
                        response.status_code == 200
                        and "no-store" in response.headers["cache-control"]
                    )
                    usage = response.json()
                    assert (usage["available_seconds"], usage["used_seconds"]) == (119940, 60)
                    row = next(
                        r for r in usage["members"] if r["person_id"] == str(member.person_id)
                    )
                    assert row["minutes_used_30d"] == 1.0
                assert len(usage["members"]) == 1  # A member sees only their own detail.
                assert (
                    await client.get("/v1/organisation/billing", headers=member_headers)
                ).status_code == 403
                assert (await client.get("/v1/organisation/billing", headers=headers)).json() == {
                    "paid_seats": 2,
                    "active_members": 2,
                    "pending_invites": 0,
                    "seats_available": 0,
                }
                # Renewal writes the next monthly lot exactly once; it is future capacity today.
                start, end = now + timedelta(days=30), now + timedelta(days=60)
                world.clock.now = start
                callback_headers, body = world.provider.charge(
                    subscription.provider_subscription_ref,
                    event_id="org-renewal",
                    order_reference=order.order_ref,
                    money=Money(order.amount_minor, "INR"),
                    period_start=start,
                    period_end=end,
                )
                assert (
                    await client.post(
                        "/v1/payments/webhooks/fake",
                        content=body,
                        headers=callback_headers,
                    )
                ).json()["outcome"] == "paid"
                assert (
                    await client.post(
                        "/v1/payments/webhooks/fake",
                        content=body,
                        headers=callback_headers,
                    )
                ).json()["replayed"] is True
                async with sessions() as db:
                    lots = list(
                        await db.scalars(
                            select(BillingLedgerEntry)
                            .where(
                                BillingLedgerEntry.account_id == subscription.account_id,
                                BillingLedgerEntry.kind == "period_grant",
                            )
                            .order_by(BillingLedgerEntry.valid_from)
                        )
                    )
                    assert [lot.seconds for lot in lots] == [120000, 120000]
                    assert [lot.valid_from for lot in lots] == [now, start]
                    assert await paid_seats(db, org.tenant_id, start) == 2
                    assert await paid_seats(db, org.tenant_id, end) == 0
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(BillingPeriod)
                            .where(
                                BillingPeriod.subscription_id == subscription.id,
                            )
                        )
                        == 2
                    )
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(Membership)
                            .where(
                                Membership.tenant_id == org.tenant_id,
                                Membership.status == "active",
                            )
                        )
                        == 2
                    )
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(OrganisationInvite)
                            .where(
                                OrganisationInvite.tenant_id == org.tenant_id,
                                OrganisationInvite.status == "pending",
                            )
                        )
                        == 0
                    )
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(AuditEvent)
                            .where(
                                AuditEvent.tenant_id == org.tenant_id,
                                AuditEvent.action == "organisation.member_invited",
                            )
                        )
                        == 1
                    )
                    assert (
                        await db.run_sync(lambda sync: verify_audit_chain_sync(sync, org.tenant_id))
                    ).valid
        finally:
            await engine.dispose()

    run(exercise())
