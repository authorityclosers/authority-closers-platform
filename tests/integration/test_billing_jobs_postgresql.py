"""Fictional expiry jobs against the existing disposable loopback harness."""

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.billing.credit_models import BillingCreditEntry
from ac_platform.billing.credits import CreditsLedger
from ac_platform.billing.expiry import EXPIRY_ACTION, MinuteExpiryService
from ac_platform.billing.expiry_jobs import EXPIRY_JOB_KIND, ExpiryWorkerResult
from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.models import BillingAccount, BillingLedgerEntry
from ac_platform.outbox.models import Job, OperationsRecoveryState
from ac_platform.outbox.repository import JobRepository
from ac_platform.worker import create_minute_expiry_worker
from tests.database.test_billing_expiry_postgresql import (
    NOW,
    acquisition,
    expiry_rows,
    lab,
    lot,
    projection,
    settle,
)
from tests.database.test_billing_ledger_postgresql import raw_usage, source
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


@asynccontextmanager
async def ready_lab(harness, *, organisation=False):
    async with lab(harness, organisation=organisation) as state:
        state.job_ids = []
        async with state.sessions() as db, db.begin():
            recovery = await db.get(OperationsRecoveryState, 1)
            recovery.status = "ready"
            recovery.reconciled_at = datetime.now(UTC)
            recovery.reconciled_by = state.owner.person_id
            recovery.reconciliation_reason = "Fictional expiry proof"
        try:
            yield state
        finally:
            # Park this fixture's unfinished jobs so module-shared schema tests
            # cannot claim another fixture's deliberate crash/fence evidence.
            async with state.sessions() as db, db.begin():
                await db.execute(
                    update(Job)
                    .where(
                        Job.id.in_(state.job_ids),
                        Job.status.in_(["queued", "leased", "retry_wait"]),
                    )
                    .values(
                        status="held",
                        lease_token=None,
                        leased_until=None,
                        held_at=datetime.now(UTC),
                        hold_reason="Fictional proof fixture ended",
                    )
                )


def worker(state, *, sessions=None, signal=None):
    settings = SimpleNamespace(
        billing_enabled=True,
        public_learner_tenant_id=state.public.tenant_id,
        operations_tenant_id=state.operations.tenant_id,
        sales_xray_trial_policy="v2",
        sales_xray_trial_policy_switch_at=NOW - timedelta(days=14),
    )
    return create_minute_expiry_worker(
        settings=settings,
        session_factory=sessions or state.sessions,
        clock=lambda: NOW,
        signal=signal,
    )


async def enqueue(state, **changes):
    intent = (
        dict(
            kind=EXPIRY_JOB_KIND,
            tenant_id=state.owner.tenant_id,
            payload={"account_id": str(state.account.id)},
            dedupe_key=f"fictional-expiry:{uuid4()}",
        )
        | changes
    )
    async with state.sessions() as db, db.begin():
        job = await JobRepository(db).enqueue(**intent)
        state.job_ids.append(job.id)
    return job


async def count_audits(db, state):
    return await db.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.tenant_id == state.owner.tenant_id,
            AuditEvent.action == EXPIRY_ACTION,
        )
    )


async def make_reclaimable(state, job):
    async with state.sessions() as db, db.begin():
        stored = await db.get(Job, job.id)
        now = datetime.now(UTC) - timedelta(seconds=1)
        if stored.status == "leased":
            stored.leased_until = now
        else:
            stored.available_at = now


def test_fictional_receipt_atomic_success_duplicate_completed_and_independent_replay(
    postgres_harness, record_property
):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                await lot(db, state, seconds=300, end=None)
                usage = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                await settle(db, state, usage, 120)
                await CreditsLedger(db).append(
                    tenant_id=state.owner.tenant_id,
                    account_id=state.account.id,
                    quantity=Decimal("7.125"),
                    source_ref=f"fictional-credit:{uuid4()}",
                    actor_type="system",
                    reason="Fictional independent credits",
                )
            job = await enqueue(state)
            duplicate = await enqueue(state, dedupe_key=job.dedupe_key)
            assert duplicate.id == job.id
            receipt = await worker(state).run_once()
            assert receipt == ExpiryWorkerResult("succeeded", 1, 1, 480)
            assert await worker(state).run_once() == ExpiryWorkerResult("idle")
            second = await enqueue(state)
            assert await worker(state).run_once() == ExpiryWorkerResult("succeeded", 1)
            async with state.sessions() as db:
                (closing,) = await expiry_rows(db, state)
                assert closing.lot_id == original.id and closing.seconds == -480
                assert await count_audits(db, state) == 1
                assert (await AuditRepository(db).verify(state.owner.tenant_id)).valid
                assert (await projection(db, state)).available == 300
                assert (await db.get(Job, job.id)).status == "succeeded"
                assert (await db.get(Job, second.id)).status == "succeeded"
                assert (await db.get(Job, job.id)).provider_receipt is None
                assert [
                    entry.quantity
                    for entry in await CreditsLedger(db).history(
                        tenant_id=state.owner.tenant_id,
                        account_id=state.account.id,
                    )
                ] == [Decimal("7.125")]
                record_property(
                    "fictional_worker_receipt",
                    json.dumps(
                        asdict(receipt)
                        | {
                            "available_seconds": 300,
                            "independent_credits": "7.125",
                            "expiry_audits": 1,
                            "replay_closings": 0,
                        }
                    ),
                )

    run(exercise())


@pytest.mark.parametrize("organisation", [False, True])
def test_distinct_concurrent_jobs_share_the_admission_lock(postgres_harness, organisation):
    async def exercise():
        async with ready_lab(postgres_harness, organisation=organisation) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            first, second = await enqueue(state), await enqueue(state)
            receipts = await asyncio.gather(worker(state).run_once(), worker(state).run_once())
            assert all(receipt.outcome == "succeeded" for receipt in receipts)
            assert sum(receipt.closings for receipt in receipts) == 1
            async with state.sessions() as db:
                assert len(await expiry_rows(db, state)) == await count_audits(db, state) == 1
                assert all(
                    [
                        (await db.get(Job, key)).status == "succeeded"
                        for key in [first.id, second.id]
                    ]
                )

    run(exercise())


@pytest.mark.parametrize("organisation", [False, True])
@pytest.mark.parametrize("settled_seconds", [0, 60])
def test_pending_success_waits_for_an_independent_intent_and_keeps_pool_lot_owner(
    postgres_harness, organisation, settled_seconds
):
    async def exercise():
        async with ready_lab(postgres_harness, organisation=organisation) as state:
            member = (
                await seed(state.engine, tenant_id=state.owner.tenant_id, role="member")
                if organisation
                else state.owner
            )
            foreign = await seed(state.engine)
            async with state.sessions() as db, db.begin():
                ledger = BillingLedger(db)
                member_account = (
                    await ledger.personal_account(
                        tenant_id=member.tenant_id,
                        person_id=member.person_id,
                        create=True,
                    )
                    if organisation
                    else state.account
                )
                original = await lot(db, state, account=member_account)
                await lot(db, state, seconds=300, end=None)
                foreign_account = await ledger.personal_account(
                    tenant_id=foreign.tenant_id,
                    person_id=foreign.person_id,
                    create=True,
                )
                foreign_lot = await lot(db, state, account=foreign_account)
                if not organisation:
                    historical = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                    await settle(db, state, historical, 0)
                usage = await acquisition(db, state, NOW - timedelta(seconds=1)).reserve(
                    source(120),
                    actor=member.actor,
                )
            first = await enqueue(state)
            assert await worker(state).run_once() == ExpiryWorkerResult("succeeded", 1, 0, 0, 1)
            assert await worker(state).run_once() == ExpiryWorkerResult("idle")
            async with state.sessions() as db, db.begin():
                await settle(db, state, usage, settled_seconds)
                assert (await projection(db, state)).available == 300
                assert await expiry_rows(db, state) == []
            await enqueue(state)
            assert await worker(state).run_once() == ExpiryWorkerResult(
                "succeeded",
                1,
                1,
                600 - settled_seconds,
            )
            async with state.sessions() as db:
                (closing,) = await expiry_rows(db, state)
                assert closing.lot_id == original.id and closing.account_id == member_account.id
                assert (await projection(db, state)).available == 300
                assert (await db.get(Job, first.id)).attempt_count == 1
                assert (await db.get(BillingLedgerEntry, foreign_lot.id)).seconds == 600
                assert len(await ledger_entries(db, foreign_account.id)) == 1

    run(exercise())


async def ledger_entries(db, account_id):
    return await BillingLedger(db).entries(account_id)


@pytest.mark.parametrize("phase", ["audit", "acknowledgement", "commit", "crash"])
def test_effect_and_success_rollback_then_restart_reclaims_safely(
    postgres_harness, monkeypatch, phase
):
    class SimulatedProcessLoss(BaseException):
        pass

    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            job = await enqueue(state)
            commit_count = 0

            def fail_commit(connection):
                nonlocal commit_count
                commit_count += 1
                if commit_count == 2:
                    raise RuntimeError("Fictional pre-commit failure")

            target = AuditRepository if phase == "audit" else JobRepository
            name = "append" if phase == "audit" else "complete"
            original = getattr(target, name)

            async def fail_after_write(self, *args, **kwargs):
                await original(self, *args, **kwargs)
                if phase == "crash":
                    raise SimulatedProcessLoss()
                raise RuntimeError("Fictional write failure with raw parameters")

            with monkeypatch.context() as patch:
                if phase == "commit":
                    event.listen(state.engine.sync_engine, "commit", fail_commit)
                else:
                    patch.setattr(target, name, fail_after_write)
                try:
                    if phase == "crash":
                        with pytest.raises(SimulatedProcessLoss):
                            await worker(state).run_once()
                    else:
                        assert await worker(state).run_once() == ExpiryWorkerResult("retry_wait", 1)
                finally:
                    if phase == "commit":
                        event.remove(state.engine.sync_engine, "commit", fail_commit)
            async with state.sessions() as db:
                assert await expiry_rows(db, state) == []
                assert await count_audits(db, state) == 0
                failed = await db.get(Job, job.id)
                assert failed.status == ("leased" if phase == "crash" else "retry_wait")
                assert failed.last_error == (
                    None if phase == "crash" else "expiry_transient_failure"
                )
            await make_reclaimable(state, job)
            assert await worker(state).run_once() == ExpiryWorkerResult("succeeded", 1, 1, 600)
            async with state.sessions() as db:
                assert (await db.get(Job, job.id)).attempt_count == 2
                assert len(await expiry_rows(db, state)) == await count_audits(db, state) == 1

    run(exercise())


@pytest.mark.parametrize("boundary", ["execute", "failure"])
@pytest.mark.parametrize("fence", ["held", "generation", "token", "expired"])
def test_execution_and_failure_transactions_require_the_claim_generation_and_live_lease(
    postgres_harness, monkeypatch, boundary, fence
):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            job = await enqueue(state)
            call_count = 0

            @asynccontextmanager
            async def fenced_sessions():
                nonlocal call_count
                call_count += 1
                if call_count == (2 if boundary == "execute" else 3):
                    async with state.sessions() as mutation, mutation.begin():
                        if fence in {"held", "generation"}:
                            recovery = await mutation.get(OperationsRecoveryState, 1)
                            if fence == "held":
                                recovery.status = "held"
                                recovery.reconciled_at = None
                                recovery.reconciled_by = None
                                recovery.reconciliation_reason = None
                            else:
                                recovery.generation += 1
                        else:
                            stored = await mutation.get(Job, job.id)
                            if fence == "token":
                                stored.lease_token = uuid4()
                            else:
                                stored.leased_until = datetime.now(UTC) - timedelta(seconds=1)
                async with state.sessions() as db:
                    yield db

            async def fail_service(*args, **kwargs):
                raise RuntimeError("Fictional database failure")

            with monkeypatch.context() as patch:
                if boundary == "failure":
                    patch.setattr(MinuteExpiryService, "expire_due", fail_service)
                assert await worker(state, sessions=fenced_sessions).run_once() == (
                    ExpiryWorkerResult("fenced", 1)
                )
            async with state.sessions() as db:
                assert await expiry_rows(db, state) == []
                assert await count_audits(db, state) == 0
                stored = await db.get(Job, job.id)
                assert stored.status == "leased" and stored.last_error is None
                assert stored.attempt_count == 1 and stored.recovery_generation == 0

    run(exercise())


def test_recovery_hold_prevents_claim_and_other_job_kinds_are_untouched(postgres_harness):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            job = await enqueue(state)
            other = await enqueue(state, kind="media.process_version.v1")
            async with state.sessions() as db, db.begin():
                recovery = await db.get(OperationsRecoveryState, 1)
                recovery.status = "held"
                recovery.reconciled_at = None
                recovery.reconciled_by = None
                recovery.reconciliation_reason = None
            assert await worker(state).run_once() == ExpiryWorkerResult("fenced")
            async with state.sessions() as db, db.begin():
                assert (await db.get(Job, job.id)).attempt_count == 0
                recovery = await db.get(OperationsRecoveryState, 1)
                recovery.status = "ready"
                recovery.reconciled_at = datetime.now(UTC)
                recovery.reconciled_by = state.owner.person_id
                recovery.reconciliation_reason = "Fictional proof release"
            assert (await worker(state).run_once()).outcome == "succeeded"
            assert await worker(state).run_once() == ExpiryWorkerResult("idle")
            async with state.sessions() as db:
                assert (await db.get(Job, other.id)).attempt_count == 0

    run(exercise())


def test_external_flag_is_fenced_without_provider_or_financial_effect(postgres_harness):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            job = await enqueue(state, external_side_effect=True)
            assert await worker(state).run_once() == ExpiryWorkerResult("fenced", 1)
            async with state.sessions() as db:
                stored = await db.get(Job, job.id)
                assert stored.status == "leased" and stored.provider_receipt is None
                assert stored.last_error is None
                assert await expiry_rows(db, state) == []
                assert await count_audits(db, state) == 0

    run(exercise())


def test_transient_failure_uses_only_existing_bounded_retry_budget(postgres_harness, monkeypatch):
    async def fail_service(*args, **kwargs):
        raise RuntimeError("Fictional raw database parameters")

    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                await lot(db, state)
            job = await enqueue(state, max_attempts=2)
            with monkeypatch.context() as patch:
                patch.setattr(MinuteExpiryService, "expire_due", fail_service)
                assert await worker(state).run_once() == ExpiryWorkerResult("retry_wait", 1)
                await make_reclaimable(state, job)
                assert await worker(state).run_once() == ExpiryWorkerResult("dead_lettered", 1)
                assert await worker(state).run_once() == ExpiryWorkerResult("idle")
            async with state.sessions() as db:
                stored = await db.get(Job, job.id)
                assert stored.attempt_count == stored.max_attempts == 2
                assert stored.last_error == "expiry_transient_failure"
                assert await expiry_rows(db, state) == []
                assert await count_audits(db, state) == 0

    run(exercise())


@pytest.mark.parametrize("refusal", ["foreign", "missing", "operations", "tenant", "payload"])
def test_terminal_refusal_has_no_financial_audit_or_account_write(postgres_harness, refusal):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            foreign = await seed(state.engine)
            async with state.sessions() as db, db.begin():
                foreign_account = await BillingLedger(db).personal_account(
                    tenant_id=foreign.tenant_id,
                    person_id=foreign.person_id,
                    create=True,
                )
                await lot(db, state)
                models = [BillingAccount, BillingLedgerEntry, BillingCreditEntry, AuditEvent]
                before = [
                    await db.scalar(select(func.count()).select_from(model)) for model in models
                ]
            changes = {
                "foreign": {"payload": {"account_id": str(foreign_account.id)}},
                "missing": {"payload": {"account_id": str(uuid4())}},
                "operations": {"tenant_id": state.operations.tenant_id},
                "tenant": {"tenant_id": None},
                "payload": {"payload": {"account_id": str(state.account.id), "person_id": "hint"}},
            }[refusal]
            job = await enqueue(state, **changes)
            assert await worker(state).run_once() == ExpiryWorkerResult("dead_lettered", 1)
            assert await worker(state).run_once() == ExpiryWorkerResult("idle")
            async with state.sessions() as db:
                assert [
                    await db.scalar(select(func.count()).select_from(model)) for model in models
                ] == before
                assert (await db.get(Job, job.id)).last_error == "expiry_refused"

    run(exercise())


def test_late_reallocation_conflict_is_terminal_alerts_once_and_preserves_closing(postgres_harness):
    async def exercise():
        async with ready_lab(postgres_harness) as state:
            async with state.sessions() as db, db.begin():
                original = await lot(db, state)
                use = await raw_usage(db, state.owner, 120, at=NOW - timedelta(days=30))
                await settle(db, state, use, 120)
            await enqueue(state)
            assert (await worker(state).run_once()).expired_seconds == 480
            async with state.sessions() as db, db.begin():
                (closing,) = await expiry_rows(db, state)
                # A fictional earlier lot redirects historical FIFO allocation,
                # leaving 120 due on the already-closed lot (the CTO conflict case).
                await lot(
                    db,
                    state,
                    seconds=120,
                    start=NOW - timedelta(days=50),
                    end=NOW - timedelta(days=20),
                )
            conflict_job = await enqueue(state)
            signal = MagicMock()
            assert await worker(state, signal=signal).run_once() == ExpiryWorkerResult(
                "dead_lettered", 1
            )
            for _ in range(2):
                assert await worker(state, signal=signal).run_once() == ExpiryWorkerResult("idle")
            signal.assert_called_once_with(
                "billing.expiry_conflict",
                {
                    "outcome": "dead_lettered",
                    "retryable": False,
                },
            )
            async with state.sessions() as db:
                (preserved,) = await expiry_rows(db, state)
                assert preserved.id == closing.id and preserved.seconds == -480
                assert preserved.lot_id == original.id and await count_audits(db, state) == 1
                failed = await db.get(Job, conflict_job.id)
                assert failed.status == "dead_letter" and failed.attempt_count == 1
                assert failed.last_error == "expiry_conflict"

    run(exercise())
