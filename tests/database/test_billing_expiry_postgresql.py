"""S6a evidence in disposable loopback PostgreSQL; all data is fictional.

The existing harness fails on missing/remote configuration. Independent sessions
prove transaction locks, rollback/restart, immutable history and pool accounting.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.billing import expiry
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.expiry import EXPIRY_ACTION, ExpiryScopeRefused, MinuteExpiryService
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.billing.periods import AccountKind, Interval, add_months, period_lots, top_up_lot
from ac_platform.billing.trial import TrialPolicy
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationAcquisitionUsage,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.admission_lock import take_admission_lock
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.tenancy.models import Membership
from tests.database.test_billing_ledger_postgresql import build_fixtures, raw_usage, source
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked

NOW = datetime(2024, 3, 31, 18, 30, tzinfo=UTC)


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@asynccontextmanager
async def lab(postgres_harness, *, organisation=False):
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        owner = await seed(engine)
        public = await seed(engine) if organisation else owner
        operations = await seed(engine)
        async with sessions() as db, db.begin():
            ledger = BillingLedger(db, clock=lambda: NOW)
            account = (
                await ledger.organisation_account(tenant_id=owner.tenant_id, create=True)
                if organisation
                else await ledger.personal_account(
                    tenant_id=owner.tenant_id, person_id=owner.person_id, create=True
                )
            )
            await db.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS expiry_marker (id uuid PRIMARY KEY, entry_id uuid)"
                )
            )
        yield SimpleNamespace(
            engine=engine,
            sessions=sessions,
            owner=owner,
            public=public,
            operations=operations,
            account=account,
            organisation=organisation,
        )
    finally:
        await engine.dispose()


def service(db, state, at=NOW):
    return MinuteExpiryService(
        db,
        public_learner_tenant_id=state.public.tenant_id,
        operations_tenant_id=state.operations.tenant_id,
        trial_policy=TrialPolicy("v2", NOW - timedelta(days=14)),
        clock=lambda: at,
    )


async def expire(db, state, at=NOW):
    return await service(db, state, at).expire_due(
        tenant_id=state.owner.tenant_id, account_id=state.account.id
    )


async def lot(db, state, *, account=None, seconds=600, start=None, end=NOW, kind="grant", **facts):
    return await BillingLedger(db, clock=lambda: NOW).write_lot(
        account=account or state.account,
        kind=kind,
        seconds=seconds,
        valid_from=start or NOW - timedelta(days=40),
        expires_at=end,
        source_ref=f"fictional-lot:{uuid4()}",
        actor_type="system",
        **facts,
    )


async def projection(db, state, at=NOW):
    ledger = BillingLedger(
        db,
        trial_policy=TrialPolicy("v2", NOW - timedelta(days=14)),
        operations_tenant_id=state.operations.tenant_id,
        trial_enabled=not state.organisation,
    )
    if state.organisation:
        return (
            await ledger.project_organisation(tenant_id=state.owner.tenant_id, now=at)
        ).projection
    return (
        await ledger.project_person(
            tenant_id=state.owner.tenant_id, person_id=state.owner.person_id, now=at
        )
    ).projection


def acquisition(db, state, at):
    return AcquisitionSessions(
        db,
        tenant_id=state.owner.tenant_id,
        operations_tenant_id=state.operations.tenant_id,
        trial_policy=TrialPolicy("v2", NOW - timedelta(days=14)),
        trial_enabled=not state.organisation,
        policy_revision="fictional-expiry-v1",
        clock=lambda: at,
    )


async def settle(db, state, usage_id, seconds):
    if seconds == 0:
        await acquisition(db, state, NOW).settle(
            usage_id, charged_seconds=0, receipt_sha256="a" * 64, no_work=True
        )
    else:
        # A fictional reduced/completed durable receipt uses the same capacity
        # lock. No provider or application database is involved.
        await take_admission_lock(db, state.owner.tenant_id)
        db.add(
            ConversationAcquisitionSettlement(
                usage_id=usage_id,
                charged_seconds=seconds,
                kind="completed",
                receipt_sha256="b" * 64,
                created_at=NOW,
            )
        )
        await db.flush()


async def expiry_rows(db, state):
    return list(
        await db.scalars(
            select(BillingLedgerEntry)
            .join(BillingAccount)
            .where(
                BillingAccount.tenant_id == state.owner.tenant_id,
                BillingLedgerEntry.kind == "expiry",
            )
        )
    )


def test_due_closing_preserves_availability_history_and_credits_and_replays(
    postgres_harness, record_property
):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state, kind="period_grant", plan_key="personal")
                live = await lot(db, state, seconds=300, end=None)
                usage_id = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                await settle(db, state, usage_id, 120)
                await CreditsLedger(db).append(
                    tenant_id=state.owner.tenant_id,
                    account_id=state.account.id,
                    quantity=Decimal("7.125"),
                    source_ref=f"fictional-credit:{uuid4()}",
                    actor_type="system",
                    reason="Independent fictional credits",
                )
                before = await projection(db, state)
                assert before.available == 300 and before.statement_balance == 780
                trial = before.position("trial")
                assert trial.lot.expires_at == NOW and trial.unallocated == 6000
                credit_history = await CreditsLedger(db).history(
                    tenant_id=state.owner.tenant_id, account_id=state.account.id
                )
                result = await expire(db, state)
                assert db.in_transaction()
                assert len(result.closings) == 1 and result.closings[0].seconds == 480
                after = await projection(db, state)
                assert after.available == before.available == after.statement_balance
                assert after.used_seconds == before.used_seconds == 120
                assert await expire(db, state) == expiry.ExpiryResult(
                    state.owner.tenant_id,
                    state.account.id,
                    "personal",
                    state.owner.person_id,
                    NOW,
                    (),
                    (),
                )
            async with state.sessions() as db, db.begin():
                assert (await expire(db, state)).closings == ()
                (closing,) = await expiry_rows(db, state)
                assert (closing.lot_id, closing.seconds, closing.valid_from, closing.plan_key) == (
                    original.id,
                    -480,
                    original.valid_from,
                    "personal",
                )
                assert closing.actor_type == "system" and closing.actor_person_id is None
                event = await db.get(AuditEvent, closing.audit_event_id)
                assert event.action == EXPIRY_ACTION and event.actor_type == "system"
                assert event.resource_id == str(original.id)
                assert event.payload["source_ref"] == closing.source_ref
                assert event.payload["expires_at"] == original.expires_at.isoformat()
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).valid
                assert (await db.get(BillingLedgerEntry, original.id)).seconds == 600
                assert (await db.get(BillingLedgerEntry, live.id)).seconds == 300
                assert (
                    await db.get(ConversationAcquisitionUsage, usage_id)
                ).reserved_seconds == 120
                assert [
                    (entry.id, entry.quantity)
                    for entry in await CreditsLedger(db).history(
                        tenant_id=state.owner.tenant_id, account_id=state.account.id
                    )
                ] == [(entry.id, entry.quantity) for entry in credit_history]
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == state.owner.tenant_id,
                            AuditEvent.action == EXPIRY_ACTION,
                        )
                    )
                    == 1
                )
                record_property("fictional_expiry_receipt", str(result))
                record_property("projected_available_seconds", after.available)

    run(exercise())


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_exact_expiry_boundary_and_partial_closings(postgres_harness, offset):
    async def exercise():
        async with lab(postgres_harness) as state, state.sessions() as db, db.begin():
            original = await lot(db, state)
            ledger = BillingLedger(db)
            await take_admission_lock(db, state.owner.tenant_id)
            for kind, seconds in [("refund", 60), ("correction", 120)]:
                await ledger.write_closing(
                    lot=original,
                    kind=kind,
                    seconds=seconds,
                    remainder=600,
                    source_ref=f"fictional-{kind}:{uuid4()}",
                    actor_type="system",
                )
            result = await expire(db, state, NOW + timedelta(microseconds=offset))
            assert [entry.seconds for entry in result.closings] == ([] if offset < 0 else [420])
            assert (await db.get(BillingLedgerEntry, original.id)).seconds == 600

    run(exercise())


def test_organisation_pool_includes_member_grants_and_former_member_use(postgres_harness):
    async def exercise():
        async with lab(postgres_harness, organisation=True) as state:
            member = await seed(state.engine, tenant_id=state.owner.tenant_id, role="member")
            foreign = await seed(state.engine)
            async with state.sessions() as db, db.begin():
                ledger = BillingLedger(db)
                member_account = await ledger.personal_account(
                    tenant_id=member.tenant_id, person_id=member.person_id, create=True
                )
                member_lot = await lot(
                    db, state, account=member_account, end=NOW - timedelta(days=1)
                )
                pool_lot = await lot(db, state, seconds=300)
                await lot(db, state, seconds=180, end=None)
                use = await raw_usage(db, member, 120, at=NOW - timedelta(days=2))
                await settle(db, state, use, 120)
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == member.tenant_id,
                        Membership.person_id == member.person_id,
                    )
                    .values(status="inactive", ended_at=NOW - timedelta(days=1))
                )
                foreign_account = await ledger.personal_account(
                    tenant_id=foreign.tenant_id, person_id=foreign.person_id, create=True
                )
                foreign_lot = await lot(db, state, account=foreign_account)
                before = await projection(db, state)
                result = await expire(db, state)
                assert result.account_kind == "organisation" and result.person_id is None
                assert {
                    (entry.lot_id, entry.account_id, entry.seconds) for entry in result.closings
                } == {(member_lot.id, member_account.id, 480), (pool_lot.id, state.account.id, 300)}
                after = await projection(db, state)
                assert before.available == after.available == after.statement_balance == 180
                assert (await db.get(BillingLedgerEntry, foreign_lot.id)).seconds == 600
                assert len(await ledger.entries(foreign_account.id)) == 1
                assert all(entry.actor_type == "system" for entry in await expiry_rows(db, state))
                with pytest.raises(ExpiryScopeRefused):
                    await service(db, state).expire_due(
                        tenant_id=member.tenant_id, account_id=member_account.id
                    )

    run(exercise())


@pytest.mark.parametrize("target", ["foreign", "missing", "operations", "wrong_tenant"])
def test_refused_scope_creates_no_accounts_audits_or_entries(postgres_harness, target):
    async def exercise():
        async with lab(postgres_harness) as state:
            foreign = await seed(state.engine)
            async with state.sessions() as db, db.begin():
                foreign_account = await BillingLedger(db).personal_account(
                    tenant_id=foreign.tenant_id, person_id=foreign.person_id, create=True
                )
                await lot(db, state, account=foreign_account)
                before = [
                    await db.scalar(select(func.count()).select_from(model))
                    for model in (
                        BillingAccount,
                        BillingLedgerEntry,
                        AuditEvent,
                        BillingCreditEntry,
                    )
                ]
                tenant, account = {
                    "foreign": (state.owner.tenant_id, foreign_account.id),
                    "missing": (state.owner.tenant_id, uuid4()),
                    "operations": (state.operations.tenant_id, state.account.id),
                    "wrong_tenant": (foreign.tenant_id, state.account.id),
                }[target]
                with pytest.raises(ExpiryScopeRefused, match="unavailable"):
                    await service(db, state).expire_due(tenant_id=tenant, account_id=account)
                after = [
                    await db.scalar(select(func.count()).select_from(model))
                    for model in (
                        BillingAccount,
                        BillingLedgerEntry,
                        AuditEvent,
                        BillingCreditEntry,
                    )
                ]
                assert before == after

    run(exercise())


@pytest.mark.parametrize("organisation", [False, True])
def test_stored_calendar_dates_yearly_future_rollover_and_cancelled_topup(
    postgres_harness, organisation
):
    async def exercise():
        async with (
            lab(postgres_harness, organisation=organisation) as state,
            state.sessions() as db,
            db.begin(),
        ):
            start = datetime(2024, 1, 31, 4, 30, tzinfo=UTC)
            planned = period_lots(
                period_id=str(uuid4()),
                account=AccountKind.ORGANISATION if organisation else AccountKind.PERSONAL,
                interval=Interval.YEAR,
                start=start,
                end=add_months(start, 12),
                included_minutes=10,
            )
            annual = [
                await lot(
                    db,
                    state,
                    start=item.valid_from,
                    end=item.expires_at,
                    seconds=item.seconds,
                    kind="period_grant",
                    plan_key="organisation" if organisation else "personal",
                )
                for item in planned
            ]
            assert planned[0].expires_at.day == (31 if organisation else 29)
            first_paid = datetime(2023, 3, 31, 18, 30, tzinfo=UTC)
            topup = top_up_lot(
                order_id=str(uuid4()), minutes=5, verified_at=start, first_period_start=first_paid
            )
            cancelled_topup = await lot(
                db,
                state,
                start=topup.valid_from,
                end=topup.expires_at,
                seconds=topup.seconds,
                kind="purchase",
            )
            # Cancellation preserves the stored lots. Its provider/subscription
            # status is intentionally absent; expiry consumes recorded dates only.
            before = await projection(db, state)
            result = await expire(db, state)
            expected_periods = annual[: 1 if organisation else 2]
            assert {receipt.lot_id for receipt in result.closings} == {
                *(entry.id for entry in expected_periods),
                cancelled_topup.id,
            }
            assert all(entry.id not in {r.lot_id for r in result.closings} for entry in annual[3:])
            after = await projection(db, state)
            assert before.available == after.available == after.statement_balance
            assert all(
                [
                    (await db.get(BillingLedgerEntry, entry.id)).expires_at == entry.expires_at
                    for entry in annual
                ]
            )

    run(exercise())


@pytest.mark.parametrize("charged", [0, 60, 120])
@pytest.mark.parametrize("fully_pending", [False, True])
def test_pending_settlement_releases_only_expired_remainder(
    postgres_harness, charged, fully_pending
):
    async def exercise():
        async with lab(postgres_harness, organisation=True) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                reserved = 600 if fully_pending else 120
                usage_id = await acquisition(db, state, NOW - timedelta(seconds=1)).reserve(
                    source(reserved), actor=state.owner.actor
                )
            async with state.sessions() as db, db.begin():
                deferred = await expire(db, state)
                assert deferred.closings == () and deferred.deferred_pending_lot_ids == (
                    original.id,
                )
                await settle(db, state, usage_id, charged)
                assert (await projection(db, state)).available == 0
                result = await expire(db, state)
                assert result.closings[0].seconds == 600 - charged
                assert (
                    (await projection(db, state)).available
                    == (await projection(db, state)).statement_balance
                    == 0
                )
                assert (await expire(db, state)).closings == ()

    run(exercise())


def test_exhausted_refund_held_and_never_expiring_lots_write_nothing(postgres_harness):
    async def exercise():
        async with (
            lab(postgres_harness, organisation=True) as state,
            state.sessions() as db,
            db.begin(),
        ):
            exhausted = await lot(db, state, end=NOW - timedelta(days=1))
            usage_id = await raw_usage(db, state.owner, 600, at=NOW - timedelta(days=2))
            await settle(db, state, usage_id, 600)
            held = await lot(db, state)
            await take_admission_lock(db, state.owner.tenant_id)
            await BillingLedger(db).write_closing(
                lot=held,
                kind="refund_hold",
                seconds=600,
                remainder=600,
                source_ref=f"fictional-hold:{uuid4()}",
                actor_type="system",
            )
            never = await lot(db, state, end=None)
            result = await expire(db, state)
            assert result.closings == () and result.deferred_pending_lot_ids == ()
            assert (await projection(db, state)).available == 600
            assert all(
                [
                    (await db.get(BillingLedgerEntry, entry.id)).seconds == 600
                    for entry in (exhausted, held, never)
                ]
            )

    run(exercise())


@pytest.mark.parametrize("failure", ["closing", "audit", "marker"])
def test_service_and_caller_marker_failures_roll_back_and_restart(
    postgres_harness, monkeypatch, failure
):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
                await lot(db, state)
            append = AuditRepository.append
            closing = BillingLedger.write_closing
            calls = 0

            async def fail_after_append(self, **kwargs):
                nonlocal calls
                result = await (append if failure == "audit" else closing)(self, **kwargs)
                calls += 1
                if calls == 2:
                    raise RuntimeError("Synthetic append failure")
                return result

            if failure != "marker":
                monkeypatch.setattr(
                    AuditRepository if failure == "audit" else BillingLedger,
                    "append" if failure == "audit" else "write_closing",
                    fail_after_append,
                )
                # Even a caller that catches and commits sees no orphan evidence.
                async with state.sessions() as db, db.begin():
                    with pytest.raises(RuntimeError, match="Synthetic"):
                        await expire(db, state)
                    assert await expiry_rows(db, state) == []
                    assert (
                        await AuditRepository(db).verify(state.owner.tenant_id)
                    ).checked_events == 0
            else:
                with pytest.raises(IntegrityError):
                    async with state.sessions() as db, db.begin():
                        result = await expire(db, state)
                        await db.execute(
                            text("INSERT INTO expiry_marker VALUES (:id, :entry)"),
                            {"id": state.account.id, "entry": result.closings[0].entry_id},
                        )
                        await db.execute(
                            text("INSERT INTO expiry_marker VALUES (:id, NULL)"),
                            {"id": state.account.id},
                        )
            monkeypatch.setattr(AuditRepository, "append", append)
            monkeypatch.setattr(BillingLedger, "write_closing", closing)
            async with state.sessions() as db, db.begin():
                assert await expiry_rows(db, state) == []
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).checked_events == 0
                assert (
                    await db.scalar(
                        text("SELECT count(*) FROM expiry_marker WHERE id=:id"),
                        {"id": state.account.id},
                    )
                    == 0
                )
                result = await expire(db, state)
                assert len(result.closings) == 2
                await db.execute(
                    text("INSERT INTO expiry_marker VALUES (:id, :entry)"),
                    {"id": state.account.id, "entry": result.closings[0].entry_id},
                )
            async with state.sessions() as db, db.begin():
                assert (await expire(db, state)).closings == ()
                assert len(await expiry_rows(db, state)) == 2
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).checked_events == 2

    run(exercise())


async def race(state, first_command, second_command):
    """Observe actual PostgreSQL blocking, then let the first caller commit."""
    held, release = asyncio.Event(), asyncio.Event()
    second_pid = asyncio.Future()

    async def first():
        async with state.sessions() as db, db.begin():
            result = await first_command(db)
            held.set()
            await release.wait()
            return result

    async def second():
        await held.wait()
        async with state.sessions() as db, db.begin():
            second_pid.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
            return await second_command(db)

    first_task, second_task = asyncio.create_task(first()), asyncio.create_task(second())
    try:
        pid = await asyncio.wait_for(second_pid, timeout=10)
        await wait_blocked(state.engine, pid, second_task)
        release.set()
        return await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=15)
    finally:
        release.set()
        for task in (first_task, second_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(first_task, second_task, return_exceptions=True)


def test_duplicate_workers_serialize_until_caller_commit(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            first, second = await race(
                state, lambda db: expire(db, state), lambda db: expire(db, state)
            )
            assert len(first.closings) == 1 and second.closings == ()
            async with state.sessions() as db, db.begin():
                assert len(await expiry_rows(db, state)) == 1
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).checked_events == 1

    run(exercise())


@pytest.mark.parametrize("completion_first", [False, True])
def test_unchanged_charge_completion_race_safely_defers_without_admission_lock(
    postgres_harness, completion_first
):
    async def exercise():
        async with lab(postgres_harness, organisation=True) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                usage_id = await acquisition(db, state, NOW - timedelta(seconds=1)).reserve(
                    source(120), actor=state.owner.actor
                )

            async def complete(db):
                await acquisition(db, state, NOW).settle(
                    usage_id, charged_seconds=120, receipt_sha256="c" * 64
                )

            # An exact-charge completion does not take the capacity lock. If
            # expiry sees its uncommitted receipt, it still sees pending use
            # and safely defers; if completion follows expiry, the same holds.
            first, second = (
                (complete, lambda db: expire(db, state))
                if completion_first
                else (lambda db: expire(db, state), complete)
            )
            async with state.sessions() as db, db.begin():
                first_result = await first(db)
                async with state.sessions() as other, other.begin():
                    second_result = await asyncio.wait_for(second(other), timeout=10)
                deferred = second_result if completion_first else first_result
                assert deferred.closings == ()
                assert deferred.deferred_pending_lot_ids == (original.id,)
            async with state.sessions() as db, db.begin():
                result = await expire(db, state)
                assert result.closings[0].seconds == 480
                assert (await expire(db, state)).closings == ()
                assert (await projection(db, state)).statement_balance == 0
                assert (await projection(db, state)).available == 0

    run(exercise())


def test_source_conflict_discloses_no_foreign_receipt_or_partial_audit(postgres_harness):
    async def exercise():
        async with lab(postgres_harness) as state:
            foreign = await seed(state.engine)
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                ledger = BillingLedger(db)
                foreign_account = await ledger.personal_account(
                    tenant_id=foreign.tenant_id, person_id=foreign.person_id, create=True
                )
                collision = await ledger.write_lot(
                    account=foreign_account,
                    kind="grant",
                    seconds=60,
                    valid_from=NOW,
                    source_ref=f"expiry:{original.id}",
                    actor_type="system",
                )
                with pytest.raises(expiry.ExpiryConflict, match="already exists") as error:
                    await expire(db, state)
                assert str(collision.id) not in str(error.value)
                assert await expiry_rows(db, state) == []
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).checked_events == 0
                assert (await db.get(BillingLedgerEntry, collision.id)).seconds == 60

    run(exercise())


@pytest.mark.parametrize("expiry_first", [False, True])
def test_no_work_settlement_and_expiry_serialize_in_both_orders(postgres_harness, expiry_first):
    async def exercise():
        async with lab(postgres_harness, organisation=True) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                usage_id = await acquisition(db, state, NOW - timedelta(seconds=1)).reserve(
                    source(120), actor=state.owner.actor
                )
            commands = [lambda db: settle(db, state, usage_id, 0), lambda db: expire(db, state)]
            if expiry_first:
                commands.reverse()
            results = await race(state, *commands)
            if expiry_first:
                assert results[0].deferred_pending_lot_ids == (original.id,)
            else:
                assert results[1].closings[0].seconds == 600
            async with state.sessions() as db, db.begin():
                await expire(db, state)
                assert [entry.seconds for entry in await expiry_rows(db, state)] == [-600]
                assert (
                    (await projection(db, state)).statement_balance
                    == (await projection(db, state)).available
                    == 0
                )

    run(exercise())


@pytest.mark.parametrize("expiry_first", [False, True])
def test_reservation_and_expiry_share_the_admission_lock(postgres_harness, expiry_first):
    async def exercise():
        async with lab(postgres_harness, organisation=True) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)

            async def reserve(db):
                app = acquisition(db, state, NOW if expiry_first else NOW - timedelta(seconds=1))
                if expiry_first:
                    with pytest.raises(ConversationDenied):
                        await app.reserve(source(120), actor=state.owner.actor)
                    return None
                return await app.reserve(source(120), actor=state.owner.actor)

            commands = [reserve, lambda db: expire(db, state)]
            if expiry_first:
                commands.reverse()
            results = await race(state, *commands)
            async with state.sessions() as db, db.begin():
                if expiry_first:
                    assert [entry.seconds for entry in await expiry_rows(db, state)] == [-600]
                else:
                    assert results[1].deferred_pending_lot_ids == (original.id,)
                    await settle(db, state, results[0], 60)
                    assert (await expire(db, state)).closings[0].seconds == 540
                assert (await projection(db, state)).available == 0

    run(exercise())


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_new_closings_and_audits_retain_append_only_constraints(postgres_harness, operation):
    async def exercise():
        async with lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
                (closing,) = (await expire(db, state)).closings
            for model, identifier in [
                (BillingLedgerEntry, closing.entry_id),
                (AuditEvent, closing.audit_event_id),
            ]:
                with pytest.raises(DBAPIError):
                    async with state.sessions() as db, db.begin():
                        statement = (
                            update(model)
                            .where(model.id == identifier)
                            .values(reason="Synthetic rewrite")
                            if operation == "update"
                            else delete(model).where(model.id == identifier)
                        )
                        await db.execute(statement)

    run(exercise())


def test_personal_expiry_uses_existing_claimed_visitor_and_legacy_reservations(postgres_harness):
    async def exercise():
        fixtures = await build_fixtures(postgres_harness)
        account = next(item for item in fixtures.accounts if item.name == "legacy-run-and-grant")
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as db, db.begin():
                ledger = BillingLedger(db, operations_tenant_id=fixtures.operations.tenant_id)
                stored = await ledger.personal_account(
                    tenant_id=account.learner.tenant_id,
                    person_id=account.learner.person_id,
                    create=True,
                )
                projected = await ledger.project_person(
                    tenant_id=account.learner.tenant_id,
                    person_id=account.learner.person_id,
                    now=account.learner.now,
                    mirror=False,
                )
                assert projected.committed_seconds == 1120
                assert projected.projection.used_seconds == 1120
                at = datetime.now(UTC) + timedelta(seconds=1)
                original = await ledger.write_lot(
                    account=stored,
                    kind="grant",
                    seconds=600,
                    valid_from=account.learner.now - timedelta(days=1),
                    expires_at=at,
                    source_ref=f"fictional-legacy-expiry:{uuid4()}",
                    actor_type="system",
                )
                api = MinuteExpiryService(
                    db,
                    public_learner_tenant_id=account.learner.tenant_id,
                    operations_tenant_id=fixtures.operations.tenant_id,
                    trial_policy=TrialPolicy(),
                    clock=lambda: at,
                )
                entries_before = await ledger.entries(stored.id)
                result = await api.expire_due(
                    tenant_id=account.learner.tenant_id, account_id=stored.id
                )
                # The legacy 120s processing use and 1000s claimed guest use are
                # pending and FIFO-allocated to this earlier-expiring lot.
                assert result.closings == () and result.deferred_pending_lot_ids == (original.id,)
                assert (await ledger.entries(stored.id)) == entries_before
        finally:
            await engine.dispose()

    run(exercise())
