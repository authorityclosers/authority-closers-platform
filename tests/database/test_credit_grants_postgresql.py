"""Fictional staff grants with real PostgreSQL permissions, locks and rollback.

The existing loopback disposable-schema harness migrates a fresh schema and
fails without database configuration; skips never count as this evidence.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.application import CapabilityApplication
from ac_platform.authorization.policy import CapabilityDenied, CapabilityScope
from ac_platform.billing import credits
from ac_platform.billing.credit_grants import CreditGrantService
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.errors import BillingForbidden
from ac_platform.billing.ledger import BillingConflict, BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.order_models import BillingOrder, BillingPaymentEvent, BillingSubscription
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation, Tenant
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_credits_ledger_postgresql import append
from tests.database.test_credits_ledger_postgresql import lab as ledger_lab


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


async def staff(state, *, permission="platform_access_manage"):
    operator = await seed(state.engine, tenant_id=state.operations.tenant_id, role="support")
    capability = None
    if permission:
        async with state.sessions() as database, database.begin():
            capability = await CapabilityApplication(
                database, operations_tenant_id=state.operations.tenant_id
            )._insert_grant(
                operator.person_id,
                operator.session_id,
                uuid4(),
                operator.person_id,
                permission,
                CapabilityScope("platform"),
                "Fictional staff assignment",
            )
    return operator, capability


@asynccontextmanager
async def lab(postgres_harness):
    async with ledger_lab(postgres_harness) as state:
        state.operations = await seed(state.engine, role="owner")
        state.operator, state.capability = await staff(state)
        async with state.sessions() as database, database.begin():
            database.add(
                Organisation(
                    tenant_id=state.pooled.tenant_id,
                    creation_command_id=uuid4(),
                    domain_verification_token=uuid4().hex * 2,
                )
            )
            await database.execute(
                text("CREATE TABLE IF NOT EXISTS grant_marker (id uuid PRIMARY KEY, entry_id uuid)")
            )
        yield state


def service(database, state):
    return CreditGrantService(
        database,
        operations_tenant_id=state.operations.tenant_id,
        public_learner_tenant_id=state.owner.tenant_id,
        clock=lambda: state.owner.now,
    )


async def grant(database, state, *, account=None, operator=None, **changes):
    account = account or state.personal
    facts = dict(
        actor=(operator or state.operator).actor,
        tenant_id=account.tenant_id,
        account_id=account.id,
        quantity=Decimal("1.25"),
        operation_id="synthetic-staff:grant",
        reason="Synthetic staff credit grant",
    )
    return await service(database, state).grant(**(facts | changes))


@pytest.mark.parametrize("kind", ["personal", "organisation"])
def test_exact_grant_has_staff_provenance_without_changing_minutes_or_provider_state(
    postgres_harness, kind
):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as database, database.begin():
            account = state.personal if kind == "personal" else state.pooled
            ledger = CreditsLedger(database)
            scope = dict(tenant_id=account.tenant_id, account_id=account.id)
            assert await ledger.balance(**scope) == 0
            minutes = BillingLedger(database)
            before = await minutes.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            unchanged = (BillingLedgerEntry, BillingOrder, BillingPaymentEvent, BillingSubscription)
            counts = [
                await database.scalar(select(func.count()).select_from(model))
                for model in unchanged
            ]
            original = await append(database, account, Decimal("0.00000000000000000000000000001"))
            quantity = Decimal("123456789012345678901234567890.12345678901234567890123456789")
            with localcontext() as context:
                context.prec = 2
                receipt = await grant(database, state, account=account, quantity=quantity)
                assert receipt.quantity == quantity
                assert await ledger.balance(**scope) == Decimal(
                    "123456789012345678901234567890.12345678901234567890123456790"
                )
            history = await ledger.history(**scope)
            assert {entry.id for entry in history} == {original.id, receipt.entry_id}
            assert (
                await database.get(BillingCreditEntry, original.id)
            ).quantity == original.quantity
            entry = await database.get(BillingCreditEntry, receipt.entry_id)
            audit = await database.get(AuditEvent, receipt.audit_event_id)
            assert entry.actor_type == audit.actor_type == "person"
            assert entry.actor_person_id == audit.actor_person_id == state.operator.person_id
            assert entry.reason == audit.reason == "Synthetic staff credit grant"
            assert entry.tenant_id == audit.tenant_id == account.tenant_id
            assert audit.session_id == state.operator.session_id
            assert audit.payload["quantity"] == str(quantity)
            assert audit.payload["account_id"] == str(account.id)
            assert audit.payload["source_ref"] == receipt.source_ref
            assert (await AuditRepository(database).verify(account.tenant_id)).valid
            assert (
                await ledger.balance(
                    tenant_id=state.other_personal.tenant_id, account_id=state.other_personal.id
                )
                == 0
            )
            assert (
                await ledger.history(tenant_id=state.operations.tenant_id, account_id=account.id)
                == []
            )
            after = await minutes.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            assert (after.available_seconds, after.plan_key, after.per_call_seconds) == (
                before.available_seconds,
                before.plan_key,
                before.per_call_seconds,
            )
            assert counts == [
                await database.scalar(select(func.count()).select_from(model))
                for model in unchanged
            ]

    run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "missing_permission",
        "billing_permission",
        "revoked_permission",
        "revoked_session",
        "expired_session",
        "wrong_session",
        "inactive_actor",
        "unverified_actor",
        "inactive_ops",
    ],
)
def test_fresh_staff_authority_is_required_even_with_caller_permission_hint(
    postgres_harness, failure
):
    async def exercise():
        async with lab(postgres_harness) as state:
            operator = state.operator
            async with state.sessions() as database, database.begin():
                if failure in {"missing_permission", "billing_permission"}:
                    operator, _ = await staff(
                        state,
                        permission="platform_billing_manage"
                        if failure == "billing_permission"
                        else None,
                    )
                elif failure == "revoked_permission":
                    await CapabilityApplication(
                        database, operations_tenant_id=state.operations.tenant_id
                    ).revoke(
                        state.operator.actor,
                        command_id=uuid4(),
                        grant_id=state.capability.id,
                        reason="Fictional revocation",
                    )
                elif failure in {"revoked_session", "expired_session"}:
                    await database.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == operator.session_id)
                        .values(
                            **(
                                {"revoked_at": operator.now}
                                if failure == "revoked_session"
                                else {
                                    "created_at": operator.now - timedelta(days=2),
                                    "expires_at": operator.now - timedelta(seconds=1),
                                }
                            )
                        )
                    )
                elif failure == "inactive_ops":
                    await database.execute(
                        update(Tenant)
                        .where(Tenant.id == state.operations.tenant_id)
                        .values(status="suspended")
                    )
                elif failure != "wrong_session":
                    await database.execute(
                        update(Person)
                        .where(Person.id == operator.person_id)
                        .values(
                            **(
                                {"status": "suspended"}
                                if failure == "inactive_actor"
                                else {"email_verified_at": None}
                            )
                        )
                    )
            actor = replace(operator.actor, permissions=frozenset({"platform_access_manage"}))
            if failure == "wrong_session":
                actor = replace(actor, session_id=state.owner.session_id)
            async with state.sessions() as database, database.begin():
                count = await database.scalar(select(func.count()).select_from(AuditEvent))
                with pytest.raises(CapabilityDenied):
                    await grant(database, state, actor=actor)
                assert await database.scalar(select(func.count()).select_from(AuditEvent)) == count
                assert (
                    await CreditsLedger(database).history(
                        tenant_id=state.personal.tenant_id, account_id=state.personal.id
                    )
                    == []
                )

    run(exercise())


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "wrong_tenant",
        "staff",
        "foreign_personal",
        "inactive_person",
        "unverified_person",
        "inactive_membership",
        "wrong_role",
        "suspended_org",
        "unregistered_org",
    ],
)
def test_wrong_target_never_creates_an_account_or_credit(postgres_harness, failure):
    async def exercise():
        async with lab(postgres_harness) as state:
            account = state.personal
            changes = {}
            async with state.sessions() as database, database.begin():
                if failure == "missing":
                    changes["account_id"] = uuid4()
                elif failure == "wrong_tenant":
                    changes["tenant_id"] = state.pooled.tenant_id
                elif failure in {"staff", "foreign_personal"}:
                    target = state.operations if failure == "staff" else state.organisation
                    account = await BillingLedger(database).personal_account(
                        tenant_id=target.tenant_id, person_id=target.person_id, create=True
                    )
                elif failure in {"inactive_person", "unverified_person"}:
                    await database.execute(
                        update(Person)
                        .where(Person.id == state.owner.person_id)
                        .values(
                            **(
                                {"status": "suspended"}
                                if failure == "inactive_person"
                                else {"email_verified_at": None}
                            )
                        )
                    )
                elif failure in {"inactive_membership", "wrong_role"}:
                    await database.execute(
                        update(Membership)
                        .where(
                            Membership.tenant_id == state.owner.tenant_id,
                            Membership.person_id == state.owner.person_id,
                        )
                        .values(
                            **(
                                {"status": "inactive", "ended_at": state.owner.now}
                                if failure == "inactive_membership"
                                else {"role": "owner"}
                            )
                        )
                    )
                else:
                    account = state.pooled
                    if failure == "suspended_org":
                        await database.execute(
                            update(Tenant)
                            .where(Tenant.id == account.tenant_id)
                            .values(status="suspended")
                        )
                    else:
                        tenant = await seed(state.engine)
                        account = await BillingLedger(database).organisation_account(
                            tenant_id=tenant.tenant_id, create=True
                        )
            async with state.sessions() as database, database.begin():
                count = await database.scalar(select(func.count()).select_from(BillingAccount))
                audit_count = await database.scalar(select(func.count()).select_from(AuditEvent))
                with pytest.raises(BillingForbidden):
                    await grant(database, state, account=account, **changes)
                assert (
                    await database.scalar(select(func.count()).select_from(BillingAccount)) == count
                )
                assert (
                    await database.scalar(select(func.count()).select_from(AuditEvent))
                    == audit_count
                )
                assert (
                    await CreditsLedger(database).history(
                        tenant_id=account.tenant_id, account_id=account.id
                    )
                    == []
                )

    run(exercise())


def test_replay_changed_facts_and_account_scoped_sources(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            other_staff, _ = await staff(state)
            async with state.sessions() as database, database.begin():
                first = await grant(database, state)
                pooled = await grant(database, state, account=state.pooled)
                assert first.source_ref != pooled.source_ref
            async with state.sessions() as database, database.begin():
                assert (await grant(database, state)).to_dict() == first.to_dict()
                for changes in ({"quantity": Decimal("2.50")}, {"reason": "Changed evidence"}):
                    with pytest.raises(BillingConflict):
                        await grant(database, state, **changes)
                with pytest.raises(BillingConflict):
                    await grant(database, state, operator=other_staff)
                assert await CreditsLedger(database).balance(
                    tenant_id=state.personal.tenant_id, account_id=state.personal.id
                ) == Decimal("1.25")
                assert (
                    len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 1
                )
                assert len(await AuditRepository(database).reconstruct(state.pooled.tenant_id)) == 1

    run(exercise())


@pytest.mark.parametrize("failure", ["audit", "caller", "marker"])
def test_grant_and_caller_write_roll_back_together(postgres_harness, monkeypatch, failure):
    real_append = credits.append_audit_event

    async def fail_audit(*args, **kwargs):
        await real_append(*args, **kwargs)
        raise RuntimeError("Synthetic audit failure")

    async def exercise():
        async with lab(postgres_harness) as state:
            marker = text("INSERT INTO grant_marker (id, entry_id) VALUES (:id, :entry_id)")
            marker_id = uuid4()
            if failure == "audit":
                async with state.sessions() as database, database.begin():
                    with monkeypatch.context() as patch:
                        patch.setattr(credits, "append_audit_event", fail_audit)
                        with pytest.raises(RuntimeError, match="Synthetic audit failure"):
                            await grant(database, state)
                    # Even a caller that catches the failure and commits leaves no audit/credit.
            else:
                with pytest.raises(IntegrityError if failure == "marker" else RuntimeError):
                    async with state.sessions() as database, database.begin():
                        receipt = await grant(database, state)
                        await database.execute(
                            marker, dict(id=marker_id, entry_id=receipt.entry_id)
                        )
                        if failure == "marker":
                            await database.execute(
                                marker, dict(id=marker_id, entry_id=receipt.entry_id)
                            )
                        raise RuntimeError("Synthetic caller failure")
            async with state.sessions() as database:
                assert (
                    await CreditsLedger(database).balance(
                        tenant_id=state.personal.tenant_id, account_id=state.personal.id
                    )
                    == 0
                )
                assert await AuditRepository(database).reconstruct(state.personal.tenant_id) == ()
                assert (
                    await database.scalar(
                        text("SELECT count(*) FROM grant_marker WHERE id = :id"), dict(id=marker_id)
                    )
                    == 0
                )

    run(exercise())


@pytest.mark.parametrize("kind", ["personal", "organisation"])
@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_requests_from_separate_sessions_count_once(postgres_harness, kind, conflicting):
    async def exercise():
        async with lab(postgres_harness) as state:
            account = state.personal if kind == "personal" else state.pooled
            ready = asyncio.get_running_loop().create_future()
            async with state.sessions() as first, first.begin():
                original = await grant(first, state, account=account)

                async def competing():
                    async with state.sessions() as second, second.begin():
                        ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                        return await grant(
                            second,
                            state,
                            account=account,
                            quantity=Decimal("2.50") if conflicting else Decimal("1.25"),
                        )

                task = asyncio.create_task(competing())
                try:
                    await wait_blocked(state.engine, await ready, task)
                    await first.commit()
                    if conflicting:
                        with pytest.raises(BillingConflict):
                            await asyncio.wait_for(task, timeout=10)
                    else:
                        replay = await asyncio.wait_for(task, timeout=10)
                        assert replay.to_dict() == original.to_dict()
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            async with state.sessions() as database:
                assert await CreditsLedger(database).balance(
                    tenant_id=account.tenant_id, account_id=account.id
                ) == Decimal("1.25")
                assert len(await AuditRepository(database).reconstruct(account.tenant_id)) == 1

    run(exercise())
