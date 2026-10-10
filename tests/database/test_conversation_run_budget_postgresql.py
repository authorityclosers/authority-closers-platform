"""Bounded plan expiry remains recoverable without provider execution admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    ProcessingPlanScheduler,
)
from ac_platform.conversation_intelligence.run_budget_alarm import overdue_processing_plans
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _prepare


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


@pytest.mark.parametrize("state", ["quoted", "active"])
def test_expired_plan_is_terminal_and_alarm_is_read_only(
    postgres_harness: Any, tmp_path: Any, state: str
) -> None:
    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        identifier = uuid4()
        try:
            async with sessions() as db, db.begin():
                command_id = await db.scalar(select(ConversationCommand.id).limit(1))
                db.add(
                    ConversationProcessingPlan(
                        id=identifier,
                        tenant_id=prepared.state.tenant_id,
                        person_id=prepared.state.person_id,
                        session_id=prepared.state.session_id,
                        recording_id=prepared.recording_id,
                        generation=1,
                        manifest={},
                        plan_sha256="a" * 64,
                        state=state,
                        acceptance_command_id=command_id if state == "active" else None,
                        progress={"speaker_roles_frozen": True},
                        created_at=datetime.now(UTC) - timedelta(hours=2),
                        expires_at=datetime.now(UTC) - timedelta(hours=1),
                        # Expiry wins even if a prior poll scheduled far ahead.
                        next_check_at=datetime.now(UTC) + timedelta(hours=1),
                    )
                )
            async with sessions() as db:
                alarm = await overdue_processing_plans(db)
                assert [row["plan_id"] for row in alarm["overdue"]] == [str(identifier)]
                row = await db.get(ConversationProcessingPlan, identifier)
                assert row is not None and row.state == state
            authority = Mock()
            scheduler = ProcessingPlanScheduler(sessions, authority)
            async with sessions() as locked, locked.begin():
                await locked.scalar(
                    select(ConversationProcessingPlan)
                    .where(ConversationProcessingPlan.id == identifier)
                    .with_for_update()
                )
                assert not await scheduler.step()
            assert await scheduler.step()
            assert not await scheduler.step()
            authority.admit.assert_not_called()
            async with sessions() as db:
                row = await db.get(ConversationProcessingPlan, identifier)
                assert row is not None and row.state == "held"
                assert row.progress == {
                    "speaker_roles_frozen": True,
                    "failure_code": "processing_budget_expired",
                }
                assert (await overdue_processing_plans(db))["overdue"] == []
                assert (
                    await db.scalar(
                        select(ConversationProcessingPlan.id).where(
                            ConversationProcessingPlan.id == identifier
                        )
                    )
                    == identifier
                )
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (TimeoutError, "processing_coordinator_timeout"),
        (RuntimeError, "processing_coordinator_failed"),
    ],
)
def test_coordinator_failure_is_terminal_after_partial_work_rolls_back(
    postgres_harness: Any,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
    error: type[Exception],
    code: str,
) -> None:
    from ac_platform.conversation_intelligence.application import ConversationApplication

    async def exercise() -> None:
        prepared = await _prepare(postgres_harness, tmp_path)
        engine = create_async_engine(postgres_harness.url)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        identifier = uuid4()
        try:
            async with sessions() as db, db.begin():
                command_id = await db.scalar(select(ConversationCommand.id).limit(1))
                db.add(
                    ConversationProcessingPlan(
                        id=identifier,
                        tenant_id=prepared.state.tenant_id,
                        person_id=prepared.state.person_id,
                        session_id=prepared.state.session_id,
                        recording_id=prepared.recording_id,
                        generation=1,
                        manifest={},
                        plan_sha256="a" * 64,
                        state="active",
                        progress={},
                        acceptance_command_id=command_id,
                        created_at=datetime.now(UTC),
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                        next_check_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                )

            async def admission(self: Any, actor: Any) -> datetime:
                return datetime.now(UTC)

            async def fail(self: Any, actor: Any, row: Any) -> None:
                row.progress = {"partial": "must roll back"}
                await self.db.flush()
                raise error("private details must not enter the public failure")

            monkeypatch.setattr(ConversationApplication, "admit", admission)
            monkeypatch.setattr(ConversationProcessingPlans, "advance", fail)
            scheduler = ProcessingPlanScheduler(sessions, Mock())
            assert await scheduler.step()
            assert not await scheduler.step()
            async with sessions() as db:
                row = await db.get(ConversationProcessingPlan, identifier)
                assert row is not None and row.state == "held"
                assert row.progress == {"failure_code": code}
                assert row.manifest == {}
        finally:
            await engine.dispose()

    run(exercise())
