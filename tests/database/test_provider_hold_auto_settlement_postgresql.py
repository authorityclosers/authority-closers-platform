"""Provider holds settle at list price as their validated receipt lands (owner, 19 Oct 2026).

The owner's words: "Yes: settle AI budget holds automatically at list price when
a validated provider receipt lands." A synthetic Scribe call runs through the
real inference worker with a local fake broker. Disposable loopback PostgreSQL;
no provider credentials or network calls.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
)
from ac_platform.conversation_intelligence.provider_hold_settlement import (
    APPROVAL,
    AUTO_ACTION,
    settle_on_receipt,
)
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import (  # type: ignore[attr-defined]
    _postgres_harness,
)
from tests.database.test_provider_hold_settlement_postgresql import _ledger, _uncertain_hold


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


async def _auto_events(sessions: async_sessionmaker[AsyncSession]) -> list[AuditEvent]:
    async with sessions() as database:
        return list(
            (
                await database.scalars(select(AuditEvent).where(AuditEvent.action == AUTO_ACTION))
            ).all()
        )


async def _settle(
    sessions: async_sessionmaker[AsyncSession],
    prepared: Any,
    reservation_id: str,
    receipt: Callable[[Any], Any] = lambda saved: saved,
) -> bool:
    async with sessions() as database, database.begin():
        task = await database.scalar(
            select(ConversationInferenceTask).where(
                ConversationInferenceTask.run_id == UUID(reservation_id)
            )
        )
        assert task is not None and task.job_id is not None
        job = await database.get(Job, task.job_id)
        assert job is not None
        minutes = await database.get(
            ConversationMinuteAccount,
            (prepared.state.tenant_id, prepared.state.person_id),
            with_for_update=True,
        )
        budget = await database.get(
            ConversationBudgetAccount, prepared.scope_id, with_for_update=True
        )
        assert minutes is not None and budget is not None
        return await settle_on_receipt(
            database,
            minutes_row=minutes,
            budget_row=budget,
            task=task,
            job_id=job.id,
            receipt=receipt(job.provider_receipt),
            now=datetime.now(UTC),
        )


def test_the_worker_settles_a_hold_once_at_list_price_when_its_receipt_lands(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        engine, sessions, prepared, reservation_id = await _uncertain_hold(
            postgres_harness, tmp_path, max_cost_paise=2_000, auto_settle=True
        )
        try:
            held, minutes, budget_revision, minutes_revision = await _ledger(
                sessions, prepared, reservation_id
            )
            assert held.state == "settled" and held.settlement is not None
            assert held.settlement.receipt_ref.startswith(
                "list-price-estimate:ref:pricing/elevenlabs-scribe-v2-20260914:job:"
            )
            assert 0 < held.settlement.actual_paise < 2_000
            assert held.committed_paise == held.settlement.actual_paise
            # Customer minutes are untouched: settled seconds equal the quote.
            assert held.settlement.actual_seconds == held.quote.entitlement_seconds
            (event,) = await _auto_events(sessions)
            assert event.payload["approval"] == APPROVAL
            assert event.payload["settled_paise"] == held.settlement.actual_paise
            assert event.payload["released_paise"] == 2_000 - held.settlement.actual_paise

            # A duplicate (the same receipt again) changes nothing and audits nothing.
            assert await _settle(sessions, prepared, reservation_id) is False
            again = await _ledger(sessions, prepared, reservation_id)
            assert again[0] == held and again[2:] == (budget_revision, minutes_revision)
            assert len(await _auto_events(sessions)) == 1
        finally:
            await engine.dispose()

    run(exercise())


def test_a_hold_without_a_validated_receipt_stays_open_and_settles_once_when_it_has_one(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        # The hold as the worker left it before 19 Oct: open, waiting.
        engine, sessions, prepared, reservation_id = await _uncertain_hold(
            postgres_harness, tmp_path, max_cost_paise=2_000
        )
        try:
            assert (await _ledger(sessions, prepared, reservation_id))[0].state == "uncertain"
            # No receipt: stays open.
            assert await _settle(sessions, prepared, reservation_id, lambda _: None) is False
            # Invalid receipts: stay open.
            for broken in (
                lambda saved: {**saved, "validation_state": "provisional"},
                lambda saved: {**saved, "schema": "ac.sales-xray.provider-receipt/0"},
                lambda saved: {**saved, "model": "another-model"},
            ):
                assert await _settle(sessions, prepared, reservation_id, broken) is False
            held = (await _ledger(sessions, prepared, reservation_id))[0]
            assert held.state == "uncertain" and held.settlement is None
            assert await _auto_events(sessions) == []

            # The validated receipt settles it, once.
            assert await _settle(sessions, prepared, reservation_id) is True
            assert await _settle(sessions, prepared, reservation_id) is False
            settled = (await _ledger(sessions, prepared, reservation_id))[0]
            assert settled.state == "settled"
            assert len(await _auto_events(sessions)) == 1
        finally:
            await engine.dispose()

    run(exercise())
