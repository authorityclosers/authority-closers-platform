"""Fictional persisted release/replay/race/audit proofs on disposable PostgreSQL."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionSettlement,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.acquisition_usage import (
    account_usage,
    acquisition_seconds,
)
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.customer_terminal_settlement import (
    ACTION,
    settle_recovered_customer_failure,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    SettlementReceipt,
    mark_dispatched,
    mark_uncertain,
    reserve,
    settle,
)
from ac_platform.conversation_intelligence.guest_ownership import admit_processing_actor
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationQuote,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_customer_failure_candidate_postgresql import candidate, prepare


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


async def prepared(
    engine: Any, scratch: Path, *, state: str = "uncertain", owner_kind: str = "guest"
) -> Any:
    f = await prepare(engine, scratch, owner_kind=owner_kind)
    async with f.sessions() as db, db.begin():
        task = await db.get(ConversationInferenceTask, f.run_id)
        original = await db.get(ConversationQuote, task.quote_id)
        minutes = await db.get(ConversationMinuteAccount, (f.actor.tenant_id, f.actor.person_id))
        budget = await db.get(ConversationBudgetAccount, original.budget_scope_id)
        # Explicit fictional quote; no live provider/route/settings are changed.
        q = replace(
            Quote.from_dict(original.quote),
            quote_id=str(uuid4()),
            max_cost_paise=23,
            provider_id="fixture",
            provider_model="fictional-no-dispatch",
        )
        permission = ExecutionPermission(
            "fictional-approved-route", q.fingerprint, "fictional-owner", q.expires_at_epoch
        )
        db.add(
            ConversationQuote(
                id=UUID(q.quote_id),
                tenant_id=f.actor.tenant_id,
                person_id=f.actor.person_id,
                recording_id=f.recording_id,
                budget_scope_id=original.budget_scope_id,
                quote=q.as_dict(),
                execution_permission=permission.as_dict(),
            )
        )
        transition = reserve(
            MinuteAccount.from_dict(minutes.snapshot),
            BudgetAccount.from_dict(budget.snapshot),
            str(f.run_id),
            q,
            permission,
            int(f.state.now.timestamp()),
        )
        if state in {"in_flight", "uncertain"}:
            transition = mark_dispatched(
                transition.minutes,
                transition.budget,
                str(f.run_id),
                "fictional-attempt",
                int(f.state.now.timestamp()),
            )
        if state == "uncertain":
            transition = mark_uncertain(
                transition.minutes, transition.budget, str(f.run_id), "fictional-ambiguous-send"
            )
        minutes.snapshot, budget.snapshot = (
            transition.minutes.as_dict(),
            transition.budget.as_dict(),
        )
        f.scope_id = budget.scope_id
        f.before = deepcopy((minutes.snapshot, budget.snapshot, minutes.revision, budget.revision))
    async with f.sessions() as db, candidate(db, f) as receipt:
        f.receipt = receipt
    return f


async def fail(f: Any, *, receipt: Any = None) -> Any:
    async with f.sessions() as db:
        return await settle_recovered_customer_failure(
            db,
            actor=f.actor,
            run_id=f.run_id,
            event_id=f.event_id,
            receipt=f.receipt if receipt is None else receipt,
        )


async def snapshots(db: Any, f: Any) -> Any:
    minutes = await db.get(ConversationMinuteAccount, (f.actor.tenant_id, f.actor.person_id))
    budget = await db.get(ConversationBudgetAccount, f.scope_id)
    return deepcopy((minutes.snapshot, budget.snapshot, minutes.revision, budget.revision))


@pytest.mark.parametrize("provider_state", ["reserved", "in_flight", "uncertain"])
def test_failure_releases_customer_and_preserves_provider_with_persisted_replay(
    postgres_harness: Any, tmp_path: Path, provider_state: str
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path, state=provider_state)
            assert (await fail(f)).changed
            async with f.sessions() as db, db.begin():
                first = await snapshots(db, f)
                settlement = await db.get(ConversationAcquisitionSettlement, f.usage_id)
                assert (settlement.kind, settlement.charged_seconds, settlement.receipt_sha256) == (
                    "terminal_failure",
                    0,
                    f.receipt.fingerprint,
                )
                m, b = MinuteAccount.from_dict(first[0]), BudgetAccount.from_dict(first[1])
                prior = BudgetAccount.from_dict(f.before[1])
                assert m.reservations == b.reservations
                assert b.available_paise == prior.available_paise
                assert b.reservations[0].committed_paise == 23
                assert b.reservations[0].state == provider_state
                unchanged = b.reservations[0].as_dict()
                assert unchanged.pop("customer_terminal_failure") == f.receipt.as_dict()
                assert unchanged == prior.reservations[0].as_dict()
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.actor.tenant_id, visitor_id=f.visitor_id
                    )
                    == 0
                )
                journal = await ReportMinutes(db).latest(f.usage_id)
                assert (journal.kind, journal.seconds) == ("released", 0)
                with pytest.raises(ConversationDenied):
                    await admit_processing_actor(db, f.actor, f.state.now)
            assert not (await fail(f)).changed
            with pytest.raises(ConversationConflict):
                await fail(f, receipt=replace(f.receipt, reserved_seconds=8))
            async with f.sessions() as db:
                assert await snapshots(db, f) == first
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == f.actor.tenant_id, AuditEvent.action == ACTION
                        )
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationReportMinuteEvent)
                        .where(ConversationReportMinuteEvent.usage_id == f.usage_id)
                    )
                    == 1
                )
        finally:
            await engine.dispose()

    run(exercise())


def test_real_audit_failure_rolls_back_settlement_journal_and_pair(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path)
            original = AuditRepository.append

            async def crash(*args: Any, **kwargs: Any) -> None:
                raise RuntimeError("fictional terminal audit failure")

            monkeypatch.setattr(AuditRepository, "append", crash)
            with pytest.raises(RuntimeError, match="fictional terminal audit failure"):
                await fail(f)
            monkeypatch.setattr(AuditRepository, "append", original)
            async with f.sessions() as db:
                assert await snapshots(db, f) == f.before
                assert await db.get(ConversationAcquisitionSettlement, f.usage_id) is None
                assert await ReportMinutes(db).latest(f.usage_id) is None
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.actor.tenant_id, visitor_id=f.visitor_id
                    )
                    == 7
                )
            assert (await fail(f)).changed
        finally:
            await engine.dispose()

    run(exercise())


def test_two_writers_commit_one_failure(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path)
            results = await asyncio.wait_for(asyncio.gather(fail(f), fail(f)), 5)
            assert sorted(result.changed for result in results) == [False, True]
        finally:
            await engine.dispose()

    run(exercise())


def test_late_provider_receipt_keeps_failed_customer_zero(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path)
            await fail(f)
            async with f.sessions() as db, db.begin():
                m = await db.get(ConversationMinuteAccount, (f.actor.tenant_id, f.actor.person_id))
                b = await db.get(ConversationBudgetAccount, f.scope_id)
                before = MinuteAccount.from_dict(m.snapshot).reservations[0]
                transition = settle(
                    MinuteAccount.from_dict(m.snapshot),
                    BudgetAccount.from_dict(b.snapshot),
                    str(f.run_id),
                    SettlementReceipt(
                        str(f.run_id),
                        before.quote.fingerprint,
                        "fixture",
                        "fictional-attempt",
                        0,
                        19,
                        "fictional-late-provider-cost",
                    ),
                )
                m.snapshot, b.snapshot = transition.minutes.as_dict(), transition.budget.as_dict()
                assert transition.reservation.customer_terminal_failure == f.receipt
                assert transition.reservation.committed_seconds == 0
                assert transition.reservation.committed_paise == 19
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.actor.tenant_id, visitor_id=f.visitor_id
                    )
                    == 0
                )
            assert not (await fail(f)).changed
        finally:
            await engine.dispose()

    run(exercise())


def test_person_claim_reads_existing_canonical_release(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path)
            await fail(f)
            async with f.sessions() as db, db.begin():
                await AcquisitionSessions(
                    db,
                    tenant_id=f.state.tenant_id,
                    policy_revision="fictional-claim",
                    clock=lambda: f.state.now,
                ).claim(f.credential_token, f.state.actor)
                value = await account_usage(
                    db, tenant_id=f.state.tenant_id, person_id=f.state.person_id, now=f.state.now
                )
                row = next(
                    x for x in value["calls"] if x["submission_id"] == f.receipt.submission_id
                )
                assert (row["seconds"], row["state"]) == (0, "not_charged")
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.state.tenant_id, person_id=f.state.person_id
                    )
                    == 0
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("owner_kind", ["personal", "organisation"])
def test_direct_person_and_organisation_owners_read_zero_without_tenant_leak(
    postgres_harness: Any, tmp_path: Path, owner_kind: str
) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path, owner_kind=owner_kind)
            await fail(f)
            other = await seed(engine, tenant_id=f.state.tenant_id)
            async with f.sessions() as db, db.begin():
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.state.tenant_id, person_id=f.state.person_id
                    )
                    == 0
                )
                value = await account_usage(
                    db, tenant_id=f.state.tenant_id, person_id=f.state.person_id, now=f.state.now
                )
                row = next(
                    x for x in value["calls"] if x["submission_id"] == f.receipt.submission_id
                )
                assert (row["seconds"], row["state"]) == (0, "not_charged")
                assert (
                    await account_usage(
                        db, tenant_id=other.tenant_id, person_id=other.person_id, now=other.now
                    )
                )["calls"] == []
        finally:
            await engine.dispose()

    run(exercise())


def test_authenticated_retry_reserves_once_and_old_failure_cannot_release_it(
    postgres_harness: Any, tmp_path: Path
) -> None:
    """Existing retry-intent admission only; successor dispatch is not claimed."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path, owner_kind="personal")
            await fail(f)
            other = await seed(engine, tenant_id=f.state.tenant_id)
            async with f.sessions() as db, db.begin():
                with pytest.raises(ConversationDenied):
                    await AcquisitionSessions(
                        db, tenant_id=f.state.tenant_id, policy_revision="fictional-retry"
                    ).reserve_report_retry(
                        UUID(f.receipt.submission_id), actor=other.actor, key="fictional-intent"
                    )
            for _ in range(2):
                async with f.sessions() as db, db.begin():
                    await AcquisitionSessions(
                        db, tenant_id=f.state.tenant_id, policy_revision="fictional-retry"
                    ).reserve_report_retry(
                        UUID(f.receipt.submission_id), actor=f.state.actor, key="fictional-intent"
                    )
            async with f.sessions() as db:
                latest = await ReportMinutes(db).latest(f.usage_id)
                assert (latest.kind, latest.seconds, latest.revision) == ("reserved", 7, 2)
                assert (
                    await acquisition_seconds(
                        db, tenant_id=f.state.tenant_id, person_id=f.state.person_id
                    )
                    == 7
                )
                before = await snapshots(db, f)
                m, b = MinuteAccount.from_dict(before[0]), BudgetAccount.from_dict(before[1])
                with pytest.raises(ValueError, match="fences provider dispatch"):
                    mark_dispatched(
                        m, b, str(f.run_id), "obsolete-worker", int(f.state.now.timestamp())
                    )
            with pytest.raises(ConversationConflict):
                await fail(f)
            async with f.sessions() as db:
                assert await snapshots(db, f) == before
                assert (await ReportMinutes(db).latest(f.usage_id)).revision == 2
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("winner", ["failure", "publication"])
def test_usage_serializes_durable_draft_and_failure(
    postgres_harness: Any, tmp_path: Path, winner: str
) -> None:
    """Actual journal/persistence race; full validated C6 remains a separate journey."""

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            f = await prepared(engine, tmp_path)
            locked = asyncio.Event()
            continue_winner = asyncio.Event()

            async def publication() -> None:
                async with f.sessions() as db, db.begin():
                    journal = ReportMinutes(db)
                    await journal._lock(f.usage_id, f.actor.tenant_id)
                    if winner == "publication":
                        locked.set()
                        await continue_winner.wait()
                    draft = ConversationReportDraft(
                        id=uuid4(),
                        tenant_id=f.actor.tenant_id,
                        person_id=f.actor.person_id,
                        recording_id=f.recording_id,
                        run_id=f.run_id,
                        source_revision=1,
                        source_sha256=f.receipt.source.source_sha256,
                        report_sha256="a" * 64,
                        transcript_sha256="b" * 64,
                        profile_sha256="c" * 64,
                        evidence_receipt_sha256="d" * 64,
                        payload={"fictional": "race-only"},
                        transcript={"fictional": True},
                        evidence_receipt={"fictional": True},
                        created_at=datetime.now(UTC),
                    )
                    db.add(draft)
                    await db.flush()
                    await journal.deliver(f.usage_id, draft)

            if winner == "failure":
                await fail(f)
                with pytest.raises(ConversationConflict):
                    await publication()
            else:
                pending = asyncio.create_task(publication())
                await asyncio.wait_for(locked.wait(), 2)
                loser = asyncio.create_task(fail(f))
                await asyncio.sleep(0.05)
                continue_winner.set()
                await asyncio.wait_for(pending, 5)
                with pytest.raises(ConversationConflict):
                    await asyncio.wait_for(loser, 5)
            async with f.sessions() as db:
                count = await db.scalar(
                    select(func.count())
                    .select_from(ConversationReportDraft)
                    .where(ConversationReportDraft.recording_id == f.recording_id)
                )
                assert count == (1 if winner == "publication" else 0)
                journal = await ReportMinutes(db).latest(f.usage_id)
                assert journal.kind == ("delivered" if winner == "publication" else "released")
        finally:
            await engine.dispose()

    run(exercise())
