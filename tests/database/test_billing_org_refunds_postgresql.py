"""AUT-954: organisation refunds use the same pool as member admission.

Disposable PostgreSQL, fictional members, and signed fake-provider payments only.
"""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ac_platform.billing.catalogue import PackCopy, StaticCatalogue
from ac_platform.billing.commands import CheckoutCommand
from ac_platform.billing.errors import PaymentUsed
from ac_platform.billing.ledger import LEGACY_GRANT_PREFIX
from ac_platform.billing.periods import add_months
from ac_platform.billing.trial import TrialPolicy
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.payments.ports import Money, PaymentEventKind
from ac_platform.tenancy.models import Organisation
from tests.database.test_billing_org_pool_postgresql import legacy_grant
from tests.database.test_billing_refund_safety_postgresql import pending_refund
from tests.database.test_billing_settlement_postgresql import (
    ORGANISATION,
    PACK_PRICE,
    PERSONAL,
    T0,
    Lab,
    World,
    scenario,
    source,
)
from tests.database.test_billing_settlement_postgresql import _clock_at_t0 as _clock_at_t0
from tests.database.test_billing_settlement_postgresql import postgres_harness as postgres_harness
from tests.database.test_billing_settlement_postgresql import world as world
from tests.database.test_conversation_postgresql import seed


@pytest.mark.parametrize("use", ["unused", "legacy", "reserved", "settled"])
def test_organisation_pack_refund_accounts_for_member_use(
    postgres_harness, world: World, monkeypatch, use: str
):
    async def exercise(lab: Lab) -> None:
        monkeypatch.setattr(lab.app.service, "trial_policy", TrialPolicy("v2"))
        plan = replace(
            ORGANISATION,
            included_minutes=10,
            packs=(PackCopy("organisation_10", 10, PACK_PRICE.amount_minor),),
        )
        monkeypatch.setattr(lab.app.service, "catalogue", StaticCatalogue((PERSONAL, plan)))
        owner = await seed(lab.engine, role="owner")
        member = await seed(lab.engine, tenant_id=owner.tenant_id, role="member")
        async with lab.sessions() as database, database.begin():
            database.add(
                Organisation(
                    tenant_id=owner.tenant_id,
                    created_by_person_id=owner.person_id,
                    creation_command_id=uuid4(),
                    domain_verification_token="f" * 43,
                )
            )

        def acquisition(database):
            return AcquisitionSessions(
                database,
                tenant_id=member.tenant_id,
                operations_tenant_id=world.operations_tenant_id,
                policy_revision="fictional-org-refund-v1",
                trial_policy=world.app.service.trial_policy,
                trial_enabled=False,
                clock=world.clock,
            )

        subscription = await lab.checkout(
            owner,
            CheckoutCommand(
                kind="subscription",
                account="organisation",
                plan_key="organisation",
                interval="month",
                seats=3,
                idempotency_key="org-subscription",
                body_sha256="a" * 64,
            ),
        )
        subscription_ref = await lab.provider_subscription_ref(
            UUID(subscription.order.subscription_id)
        )
        assert await lab.webhook(
            *world.fake.charge(
                subscription_ref,
                event_id=f"charge:{subscription_ref}",
                order_reference=subscription.hosted.params["reference"],
                money=Money(subscription.order.amount.minor, "INR"),
                period_start=T0,
                period_end=add_months(T0, 1),
            )
        ) == ("paid", False)
        # Consume the earlier-expiring period before buying the 600-second pack.
        lab.tick()
        async with lab.sessions() as database, database.begin():
            app = acquisition(database)
            usage_id = await app.reserve(source(1800), actor=member.actor)
            await app.settle(usage_id, charged_seconds=1800, receipt_sha256="b" * 64)
        pack = await lab.checkout(
            owner,
            CheckoutCommand(
                kind="top_up",
                account="organisation",
                plan_key="organisation",
                pack_key="organisation_10",
                idempotency_key="org-pack",
                body_sha256="c" * 64,
            ),
        )
        order_id = UUID(pack.order.order_id)
        order_ref = pack.hosted.params["reference"]
        payment_ref = world.fake.settle(order_ref)
        assert await lab.webhook(
            *world.fake.signed_event(
                kind=PaymentEventKind.PAID,
                event_id=f"paid:{order_ref}",
                order_reference=order_ref,
                money=Money(pack.order.amount.minor, "INR"),
                provider_payment_ref=payment_ref,
            )
        ) == ("paid", False)
        audit_id = None
        if use == "legacy":
            operations = await seed(lab.engine, tenant_id=world.operations_tenant_id, role="owner")
            async with lab.sessions() as database, database.begin():
                audit_id = await legacy_grant(database, member, operations)
        elif use in {"reserved", "settled"}:
            lab.tick()
            async with lab.sessions() as database, database.begin():
                app = acquisition(database)
                usage_id = await app.reserve(source(600), actor=member.actor)
                if use == "settled":
                    await app.settle(usage_id, charged_seconds=600, receipt_sha256="d" * 64)

        provider_calls = []

        async def refund(**kwargs):
            provider_calls.append(kwargs["money"])
            return await pending_refund(**kwargs)

        monkeypatch.setattr(world.fake, "refund", refund)
        if use in {"reserved", "settled"}:
            with pytest.raises(PaymentUsed):
                await lab.refund(owner, payment_ref, key="org-refund")
            assert await lab.refund_events(order_id) == []
            assert provider_calls == []
        else:
            accepted = await lab.refund(owner, payment_ref, key="org-refund")
            assert accepted.state == "pending"
            assert await lab.refund(owner, payment_ref, key="org-refund") == accepted
            assert provider_calls == [Money(pack.order.amount.minor, "INR")]
        async with lab.sessions() as database, database.begin():
            ledger = lab.app.service.ledger(database, tenant_id=owner.tenant_id)
            assert ledger.trial_enabled is False
            entries = await ledger.organisation_entries(tenant_id=owner.tenant_id)
            (lot,) = [entry for entry in entries if entry.source_ref == f"order:{order_id}"]
            holds = [entry for entry in entries if entry.kind == "refund_hold"]
            assert [(hold.lot_id, hold.seconds) for hold in holds] == (
                [] if use in {"reserved", "settled"} else [(lot.id, -600)]
            )
            pool = await ledger.project_organisation(tenant_id=owner.tenant_id, now=lab.now)
            positions = {p.lot.lot_id: p for p in pool.projection.positions}
            assert "trial" not in positions
            assert positions[str(lot.id)].allocated == (
                600 if use in {"reserved", "settled"} else 0
            )
            assert pool.projection.balance == (600 if use == "legacy" else 0)
            if audit_id is not None:
                assert (
                    len([e for e in entries if e.source_ref == f"{LEGACY_GRANT_PREFIX}{audit_id}"])
                    == 1
                )
            assert (await acquisition(database).allowance(actor=member.actor))[
                "available_seconds"
            ] == pool.available_seconds

    scenario(postgres_harness, world, exercise)
