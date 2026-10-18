"""Owner-approved settlement of stuck provider holds (17 Oct 2026).

A synthetic Scribe call runs through the real inference worker with a local
fake broker, leaving the uncertain hold every successful provider call leaves.
Disposable loopback PostgreSQL; no provider credentials or network calls.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
)
from ac_platform.conversation_intelligence.inference import TRANSCRIPT_RECIPE, ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationMinuteAccount,
    ConversationQuote,
)
from ac_platform.conversation_intelligence.provider_hold_settlement import (
    ACTION,
    settle_provider_holds,
)
from tests.database.test_conversation_inference_postgresql import FakeBroker
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import (  # type: ignore[attr-defined]
    _postgres_harness,
)
from tests.database.test_conversation_worker_postgresql import _prepare as prepare_local


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


async def _uncertain_hold(
    postgres_harness: Any, tmp_path: Path, *, max_cost_paise: int, auto_settle: bool = False
) -> tuple[Any, async_sessionmaker[AsyncSession], Any, str]:
    """A receipted Scribe call. Without ``auto_settle`` its hold is left open, as every
    hold was before the worker settled them itself (19 Oct 2026)."""
    prepared = await prepare_local(postgres_harness, tmp_path)
    assert await prepared.worker.run_once()
    engine = create_async_engine(postgres_harness.url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    state = prepared.state
    now = datetime.now(UTC)
    source_sha256 = hashlib.sha256(prepared.data).hexdigest()
    quote = Quote(
        quote_id=str(uuid4()),
        source=SourceBinding(str(state.tenant_id), str(prepared.recording_id), source_sha256, "1"),
        account_id=str(state.person_id),
        budget_scope_id=str(prepared.scope_id),
        provider_id="elevenlabs",
        provider_model="scribe_v2",
        recipe_revision=TRANSCRIPT_RECIPE,
        operation="transcribe_scribe_v2",
        input_sha256=source_sha256,
        privacy_revision="synthetic-provider-privacy-v1",
        permission_ref=str(state.permission_id),
        provider_terms_ref="synthetic-provider-terms",
        retention_ref="synthetic-provider-retention",
        professional_gate_ref="synthetic-provider-gate",
        pricing_ref="synthetic-price",
        entitlement_seconds=1,
        max_cost_paise=max_cost_paise,
        created_at_epoch=int(now.timestamp()) - 1,
        expires_at_epoch=int(now.timestamp()) + 3600,
    )
    permission = ExecutionPermission(
        "synthetic-provider-execution-approval",
        quote.fingerprint,
        str(state.person_id),
        int(now.timestamp()) + 3600,
    )
    quote_id = UUID(quote.quote_id)
    async with sessions() as database, database.begin():
        database.add(
            ConversationQuote(
                id=quote_id,
                tenant_id=state.tenant_id,
                person_id=state.person_id,
                recording_id=prepared.recording_id,
                budget_scope_id=prepared.scope_id,
                quote=quote.as_dict(),
                execution_permission=permission.as_dict(),
            )
        )
    async with sessions() as database, database.begin():
        service = ConversationInference(ConversationApplication(database))
        await service.accept(
            state.actor,
            prepared.recording_id,
            quote_id,
            QuoteAcceptance(
                quote_fingerprint=quote.fingerprint,
                privacy_revision=quote.privacy_revision,
                accepted=True,
            ),
        )
        view = await service.request_transcription(
            state.actor, prepared.recording_id, quote_id, key="settlement-fixture"
        )
    worker = ConversationInferenceWorker(sessions, prepared.storage, FakeBroker(prepared.data))
    from ac_platform.conversation_intelligence import inference_worker

    automatic = inference_worker.settle_on_receipt

    async def leave_open(*_args: Any, **_kwargs: Any) -> bool:
        return False

    if not auto_settle:
        inference_worker.settle_on_receipt = leave_open  # type: ignore[assignment]
    try:
        assert await worker.run_once()
    finally:
        inference_worker.settle_on_receipt = automatic  # type: ignore[assignment]
    return engine, sessions, prepared, str(view["id"])


async def _ledger(
    sessions: async_sessionmaker[AsyncSession], prepared: Any, reservation_id: str
) -> tuple[Any, Any, int, int]:
    async with sessions() as database:
        budget_row = await database.get(ConversationBudgetAccount, prepared.scope_id)
        minutes_row = await database.get(
            ConversationMinuteAccount, (prepared.state.tenant_id, prepared.state.person_id)
        )
        assert budget_row is not None and minutes_row is not None
        budget = BudgetAccount.from_dict(budget_row.snapshot)
        minutes = MinuteAccount.from_dict(minutes_row.snapshot)
        in_budget = next(r for r in budget.reservations if r.reservation_id == reservation_id)
        in_minutes = next(r for r in minutes.reservations if r.reservation_id == reservation_id)
        assert in_budget == in_minutes
        return in_budget, minutes, budget_row.revision, minutes_row.revision


async def _settle(sessions: async_sessionmaker[AsyncSession], *, apply: bool) -> dict[str, Any]:
    async with sessions() as database, database.begin():
        return await settle_provider_holds(
            database,
            apply=apply,
            approver="owner (test)",
            issue="cost-step-1-test",
            now=datetime.now(UTC),
        )


async def _events(sessions: async_sessionmaker[AsyncSession]) -> int:
    async with sessions() as database:
        return int(
            await database.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.action == ACTION)
            )
            or 0
        )


def test_dry_run_then_apply_settles_once_at_list_price(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine, sessions, prepared, reservation_id = await _uncertain_hold(
            postgres_harness, tmp_path, max_cost_paise=2_000
        )
        try:
            held, minutes_before, budget_rev, minutes_rev = await _ledger(
                sessions, prepared, reservation_id
            )
            assert held.state == "uncertain" and held.committed_paise == 2_000

            dry = await _settle(sessions, apply=False)
            scope = next(s for s in dry["scopes"] if s["scope_id"] == str(prepared.scope_id))
            assert scope["settled"] == 1 and dry["audit_events"] == 0
            # 1 s of Scribe at $0.22/h and the pinned Rs 100/$ planning rate rounds up to 1 paisa.
            assert scope["settled_paise"] == 1
            assert scope["committed_paise_before"] - scope["committed_paise_after"] == 1_999
            unchanged, _, budget_rev_dry, minutes_rev_dry = await _ledger(
                sessions, prepared, reservation_id
            )
            assert unchanged == held and (budget_rev_dry, minutes_rev_dry) == (
                budget_rev,
                minutes_rev,
            )
            assert await _events(sessions) == 0

            applied = await _settle(sessions, apply=True)
            assert applied["audit_events"] == 1
            settled, minutes_after, budget_rev_after, minutes_rev_after = await _ledger(
                sessions, prepared, reservation_id
            )
            assert settled.state == "settled" and settled.settlement is not None
            assert settled.settlement.actual_paise == 1
            assert settled.settlement.receipt_ref.startswith("list-price-estimate:")
            # Customer minutes never change: settled seconds equal the quoted entitlement.
            assert minutes_after.available_seconds == minutes_before.available_seconds
            assert (budget_rev_after, minutes_rev_after) == (budget_rev + 1, minutes_rev + 1)

            again = await _settle(sessions, apply=True)
            scope = next(s for s in again["scopes"] if s["scope_id"] == str(prepared.scope_id))
            assert scope["settled"] == 0 and again["audit_events"] == 0
            assert await _events(sessions) == 1
        finally:
            await engine.dispose()

    run(exercise())


def test_estimate_above_the_quote_stays_on_hold(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        engine, sessions, prepared, reservation_id = await _uncertain_hold(
            postgres_harness, tmp_path, max_cost_paise=0
        )
        try:
            before = await _ledger(sessions, prepared, reservation_id)
            result = await _settle(sessions, apply=True)
            scope = next(s for s in result["scopes"] if s["scope_id"] == str(prepared.scope_id))
            assert scope["settled"] == 0
            assert scope["skipped"] == {"estimate_above_quote": 1}
            assert await _ledger(sessions, prepared, reservation_id) == before
            assert await _events(sessions) == 0
        finally:
            await engine.dispose()

    run(exercise())
