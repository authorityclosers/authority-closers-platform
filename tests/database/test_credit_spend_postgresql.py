"""Authorized exact credit spending with real loopback PostgreSQL locks.

All accounts, quantities and caller-owned markers are fictional. The existing
disposable-schema harness fails on absent database configuration; no skips.
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from decimal import Decimal, localcontext
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.billing import credits
from ac_platform.billing.catalogue import StaticCatalogue
from ac_platform.billing.checkout import CheckoutService
from ac_platform.billing.commands import Caller
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credit_spend import CreditSpendService, InsufficientCredits
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.errors import BillingForbidden
from ac_platform.billing.ledger import BillingConflict, BillingLedger
from ac_platform.billing.models import BillingLedgerEntry
from ac_platform.payments.registry import PaymentProviderRegistry
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_credits_ledger_postgresql import append
from tests.database.test_credits_ledger_postgresql import lab as ledger_lab


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@asynccontextmanager
async def lab(postgres_harness):
    async with ledger_lab(postgres_harness) as state:
        state.checkout = CheckoutService(
            catalogue=StaticCatalogue(),
            providers=PaymentProviderRegistry(),
            public_learner_tenant_id=state.owner.tenant_id,
            operations_tenant_id=uuid4(),
            return_url_base="https://fictional.example.test",
            clock=lambda: state.owner.now,
        )
        async with state.sessions() as database, database.begin():
            database.add(
                Organisation(
                    tenant_id=state.pooled.tenant_id,
                    creation_command_id=uuid4(),
                    domain_verification_token=uuid4().hex * 2,
                )
            )
            await database.execute(
                text("CREATE TABLE IF NOT EXISTS spend_marker (id uuid PRIMARY KEY, entry_id uuid)")
            )
        yield state


def caller(actor):
    # Deliberately stale role hint: current membership must decide permission.
    return Caller(actor.person_id, actor.session_id, actor.tenant_id, "owner")


def service(database, state):
    return CreditSpendService(database, checkout=state.checkout)


async def spend(database, state, *, account=None, actor=None, **changes):
    facts = dict(
        caller=caller(actor or state.owner),
        account_id=(account or state.personal).id,
        quantity=Decimal("1.25"),
        operation_id="synthetic-report:unlock",
        reason="Synthetic debit evidence",
    )
    facts.update(changes)
    return await service(database, state).spend(**facts)


def test_exact_spend_and_empty_balance_leave_minutes_and_access_unchanged(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as database, database.begin():
            api = service(database, state)
            scope = dict(caller=caller(state.owner), account_id=state.personal.id)
            assert await api.balance(**scope) == 0
            with pytest.raises(InsufficientCredits):
                await spend(database, state)
            assert (
                await CreditsLedger(database).history(
                    tenant_id=state.personal.tenant_id, account_id=state.personal.id
                )
                == []
            )
            minute_ledger = BillingLedger(database)
            before = await minute_ledger.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            quantity = Decimal("123456789012345678901234567890.12345678901234567890123456789")
            await append(database, state.personal, quantity)
            await append(database, state.personal, Decimal("0.00000000000000000000000000001"))
            with localcontext() as context:
                context.prec = 2
                receipt = await spend(database, state, quantity=quantity)
                assert receipt.quantity == quantity
                assert await api.balance(**scope) == Decimal("0.00000000000000000000000000001")
            after = await minute_ledger.project_person(
                tenant_id=state.owner.tenant_id,
                person_id=state.owner.person_id,
                now=state.owner.now,
            )
            assert (after.available_seconds, after.plan_key, after.per_call_seconds) == (
                before.available_seconds,
                before.plan_key,
                before.per_call_seconds,
            )
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(BillingLedgerEntry)
                    .where(BillingLedgerEntry.account_id == state.personal.id)
                )
                == 0
            )
            entry = await database.get(BillingCreditEntry, receipt.entry_id)
            assert entry.quantity == quantity.copy_negate()
            assert entry.actor_person_id == state.owner.person_id
            audit = await database.get(AuditEvent, receipt.audit_event_id)
            assert audit.payload["quantity"] == str(quantity.copy_negate())

    run(exercise())


@pytest.mark.parametrize(
    "target", ["foreign_person", "foreign_tenant", "missing", "staff", "org", "unselected_org"]
)
def test_foreign_scope_discloses_no_balance_or_receipt_and_appends_nothing(
    postgres_harness, target
):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                foreign = await BillingLedger(database).personal_account(
                    tenant_id=state.organisation.tenant_id,
                    person_id=state.owner.person_id,
                    create=True,
                )
                for account in (state.personal, state.other_personal, state.pooled, foreign):
                    await append(database, account, Decimal("9.75"))
            actor = caller(state.owner)
            targets = {
                "foreign_person": state.other_personal.id,
                "foreign_tenant": foreign.id,
                "missing": uuid4(),
                "staff": state.personal.id,
                "org": state.pooled.id,
                "unselected_org": state.pooled.id,
            }
            if target == "staff":
                actor = replace(actor, tenant_id=state.checkout.operations_tenant_id)
            elif target == "unselected_org":
                actor = replace(caller(state.organisation), tenant_id=state.owner.tenant_id)
            async with state.sessions() as database, database.begin():
                baseline = await database.scalar(select(func.count()).select_from(AuditEvent))
                for operation in ("balance", "spend"):
                    with pytest.raises(BillingForbidden):
                        if operation == "balance":
                            await service(database, state).balance(
                                caller=actor, account_id=targets[target]
                            )
                        else:
                            await spend(database, state, caller=actor, account_id=targets[target])
                assert (
                    await database.scalar(select(func.count()).select_from(AuditEvent)) == baseline
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(BillingCreditEntry)
                        .where(
                            BillingCreditEntry.account_id.in_(
                                [
                                    state.personal.id,
                                    state.other_personal.id,
                                    state.pooled.id,
                                    foreign.id,
                                ]
                            ),
                            BillingCreditEntry.quantity < 0,
                        )
                    )
                    == 0
                )

    run(exercise())


@pytest.mark.parametrize(
    "role,status",
    [
        ("admin", "active"),
        ("member", "active"),
        ("owner", "inactive"),
        ("admin", "inactive"),
    ],
)
def test_current_org_membership_controls_read_and_spend(postgres_harness, role, status):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                await append(database, state.pooled, Decimal("3.75"))
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == state.pooled.tenant_id,
                        Membership.person_id == state.organisation.person_id,
                    )
                    .values(
                        role=role,
                        status=status,
                        ended_at=state.owner.now if status == "inactive" else None,
                    )
                )
            async with state.sessions() as database, database.begin():
                scope = dict(caller=caller(state.organisation), account_id=state.pooled.id)
                if role == "admin" and status == "active":
                    assert await service(database, state).balance(**scope) == Decimal("3.75")
                else:
                    with pytest.raises(BillingForbidden):
                        await service(database, state).balance(**scope)
                with pytest.raises(BillingForbidden):
                    await spend(database, state, account=state.pooled, actor=state.organisation)
                assert len(await AuditRepository(database).reconstruct(state.pooled.tenant_id)) == 1

    run(exercise())


def test_personal_inactive_membership_refuses_balance_and_spend(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as database, database.begin():
            await database.execute(
                update(Membership)
                .where(
                    Membership.tenant_id == state.owner.tenant_id,
                    Membership.person_id == state.owner.person_id,
                )
                .values(status="inactive", ended_at=state.owner.now)
            )
            with pytest.raises(BillingForbidden):
                await service(database, state).balance(
                    caller=caller(state.owner), account_id=state.personal.id
                )
            with pytest.raises(BillingForbidden):
                await spend(database, state)
            assert (
                await database.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.tenant_id == state.owner.tenant_id)
                )
                == 0
            )

    run(exercise())


def test_retries_preserve_receipt_after_exhaustion_and_conflicting_facts_fail(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                await append(database, state.personal)
                first = await spend(database, state)
            async with state.sessions() as database, database.begin():
                replay = await spend(database, state)
                assert replay.to_dict() == first.to_dict()
                for changes in (dict(quantity=Decimal("2.50")), dict(reason="Different evidence")):
                    with pytest.raises(BillingConflict):
                        await spend(database, state, **changes)
                with pytest.raises(InsufficientCredits):
                    await spend(database, state, operation_id="different-operation")
                assert (
                    await service(database, state).balance(
                        caller=caller(state.owner), account_id=state.personal.id
                    )
                    == 0
                )
                assert (
                    len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 2
                )

    run(exercise())


def test_account_namespaced_identity_and_actor_conflict(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            co_owner = await seed(state.engine, tenant_id=state.pooled.tenant_id, role="owner")
            async with state.sessions() as database, database.begin():
                for account in (state.personal, state.pooled):
                    await append(database, account)
                personal = await spend(database, state)
                organisation = await spend(
                    database, state, account=state.pooled, actor=state.organisation
                )
                assert organisation.source_ref != personal.source_ref
                with pytest.raises(BillingConflict):
                    await spend(database, state, account=state.pooled, actor=co_owner)
                await database.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == state.pooled.tenant_id,
                        Membership.person_id == state.organisation.person_id,
                    )
                    .values(role="member")
                )
                with pytest.raises(BillingForbidden):
                    await spend(database, state, account=state.pooled, actor=state.organisation)

    run(exercise())


@pytest.mark.parametrize("failure", ["caller", "marker", "audit"])
def test_caller_marker_debit_and_audit_roll_back_together(postgres_harness, monkeypatch, failure):
    real_append = credits.append_audit_event

    async def fail_audit(*args, **kwargs):
        await real_append(*args, **kwargs)
        raise RuntimeError("Synthetic audit failure")

    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as database, database.begin():
                await append(database, state.personal, Decimal("3.75"))
            marker_id = uuid4()
            expected = IntegrityError if failure == "marker" else RuntimeError
            with pytest.raises(expected):
                async with state.sessions() as database, database.begin():
                    marker = text("INSERT INTO spend_marker (id, entry_id) VALUES (:id, :entry_id)")
                    if failure == "audit":
                        await database.execute(marker, dict(id=marker_id, entry_id=None))
                        with monkeypatch.context() as patch:
                            patch.setattr(credits, "append_audit_event", fail_audit)
                            await spend(database, state)
                    else:
                        receipt = await spend(database, state)
                        await database.execute(
                            marker, dict(id=marker_id, entry_id=receipt.entry_id)
                        )
                        if failure == "marker":
                            await database.execute(
                                marker, dict(id=marker_id, entry_id=receipt.entry_id)
                            )
                        raise RuntimeError("Synthetic caller failure")
            async with state.sessions() as database:
                assert await service(database, state).balance(
                    caller=caller(state.owner), account_id=state.personal.id
                ) == Decimal("3.75")
                assert (
                    len(await AuditRepository(database).reconstruct(state.personal.tenant_id)) == 1
                )
                assert (
                    await database.scalar(
                        text("SELECT count(*) FROM spend_marker WHERE id = :id"), dict(id=marker_id)
                    )
                    == 0
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(BillingCreditEntry)
                        .where(BillingCreditEntry.account_id == state.personal.id)
                    )
                    == 1
                )

    run(exercise())


@pytest.mark.parametrize("kind", ["personal", "organisation"])
@pytest.mark.parametrize("duplicate", [True, False])
def test_independent_sessions_debit_once_and_cannot_overspend(postgres_harness, kind, duplicate):
    async def exercise():
        async with lab(postgres_harness) as state:
            account = state.personal if kind == "personal" else state.pooled
            actor = state.owner if kind == "personal" else state.organisation
            async with state.sessions() as database, database.begin():
                await append(database, account)
            ready = asyncio.get_running_loop().create_future()
            async with state.sessions() as first, first.begin():
                original = await spend(first, state, account=account, actor=actor)

                async def competing():
                    async with state.sessions() as second, second.begin():
                        ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                        return await spend(
                            second,
                            state,
                            account=account,
                            actor=actor,
                            operation_id="synthetic-report:unlock"
                            if duplicate
                            else "other-operation",
                        )

                task = asyncio.create_task(competing())
                try:
                    await wait_blocked(state.engine, await ready, task)
                    await first.commit()
                    if duplicate:
                        replay = await asyncio.wait_for(task, timeout=10)
                        assert replay.to_dict() == original.to_dict()
                    else:
                        with pytest.raises(InsufficientCredits):
                            await asyncio.wait_for(task, timeout=10)
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            async with state.sessions() as database:
                assert (
                    await service(database, state).balance(
                        caller=caller(actor), account_id=account.id
                    )
                    == 0
                )
                assert len(await AuditRepository(database).reconstruct(account.tenant_id)) == 2
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(BillingCreditEntry)
                        .where(
                            BillingCreditEntry.account_id == account.id,
                            BillingCreditEntry.quantity < 0,
                        )
                    )
                    == 1
                )

    run(exercise())
