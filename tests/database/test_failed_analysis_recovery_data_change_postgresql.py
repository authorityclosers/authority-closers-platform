"""Prove the reviewed tool uses the app release path atomically and idempotently."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.acquisition_models import ConversationReportMinuteEvent
from ac_platform.conversation_intelligence.analysis_diagnostics import analysis_inventory
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.models import ConversationProcessingPlan
from ac_platform.conversation_intelligence.report_minutes import ReportMinutes
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_report_minutes_postgresql import (
    postgres_harness as postgres_harness,
)
from tests.database.test_conversation_report_minutes_postgresql import setup_case

SPEC = importlib.util.spec_from_file_location(
    "failed_analysis_data_change",
    Path(__file__).resolve().parents[2] / "scripts/data-changes/release-failed-analysis-minutes.py",
)
assert SPEC and SPEC.loader
CHANGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHANGE)


def args(plan_ids: list, *, apply: bool = False, fingerprint: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        environment="staging",
        plan_id=plan_ids,
        apply=apply,
        expected_fingerprint=fingerprint,
        approver="Fictional owner",
        approval_reference=uuid4(),
        operator_reference=uuid4(),
        run_reference=uuid4(),
        snapshot_reference=None,
    )


def test_read_only_preview_app_release_replay_and_attribution(postgres_harness: Any) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            preview_args = args([case.plan.id])
            async with case.sessions() as db, db.begin():
                await db.execute(text("SET TRANSACTION READ ONLY"))
                preview = await CHANGE.change(db, preview_args)
                assert preview["before"] == preview["after"]
                assert preview["changed_plan_ids"] == []
                assert await ReportMinutes(db).latest(case.usage_id) is None
                inventory = await analysis_inventory(db, now=case.state.now)
                row = next(row for row in inventory["held_plans"] if row["plan_id"] == case.plan.id)
                assert row["minute_kind"] is None and row["reserved_seconds"] == 120
                assert not any(key in row for key in ("payload", "transcript", "manifest"))
            apply_args = args(
                [case.plan.id], apply=True, fingerprint=preview["preview_fingerprint"]
            )
            async with case.sessions() as db, db.begin():
                applied = await CHANGE.change(db, apply_args)
                assert applied["changed_plan_ids"] == [str(case.plan.id)]
                assert applied["after"][0]["minute_kind"] == "released"
            async with case.sessions() as db, db.begin():
                replay = await CHANGE.change(db, apply_args)
                assert replay["changed_plan_ids"] == []
                count = await db.scalar(
                    select(func.count())
                    .select_from(ConversationReportMinuteEvent)
                    .where(ConversationReportMinuteEvent.usage_id == case.usage_id)
                )
                assert count == 1
                events = list(
                    await db.scalars(
                        select(AuditEvent).where(
                            AuditEvent.resource_id == str(case.plan.id),
                            AuditEvent.action
                            == "conversation.owner_approved_failed_minutes_released",
                        )
                    )
                )
                assert len(events) == 1
                assert events[0].payload["approver"] == "Fictional owner"
                assert events[0].payload["issue"] == "AUT-1801"
                assert events[0].payload["provider_calls"] == 0
        finally:
            await engine.dispose()

    run(exercise())


def test_second_target_failure_rolls_back_release_and_audit(
    postgres_harness: Any, monkeypatch: Any
) -> None:
    original = ReportMinutes.release_plan
    calls = 0

    async def fail_second(minutes: ReportMinutes, plan: ConversationProcessingPlan) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ConversationConflict("Fictional second-target refusal.")
        return await original(minutes, plan)

    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            cases = [await setup_case(engine), await setup_case(engine)]
            ids = [case.plan.id for case in cases]
            async with cases[0].sessions() as db, db.begin():
                preview = await CHANGE.change(db, args(ids))
            monkeypatch.setattr(ReportMinutes, "release_plan", fail_second)
            with pytest.raises(ConversationConflict):
                async with cases[0].sessions() as db, db.begin():
                    await CHANGE.change(
                        db, args(ids, apply=True, fingerprint=preview["preview_fingerprint"])
                    )
            assert calls == 2
            async with cases[0].sessions() as db:
                for case in cases:
                    assert await ReportMinutes(db).latest(case.usage_id) is None
                events = await db.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.resource_id.in_([str(identifier) for identifier in ids]),
                        AuditEvent.action == "conversation.owner_approved_failed_minutes_released",
                    )
                )
                assert events == 0
        finally:
            await engine.dispose()

    run(exercise())


@pytest.mark.parametrize("invalid", ["stale_preview", "duplicate", "missing", "active"])
def test_refusal_changes_no_reservation(postgres_harness: Any, invalid: str) -> None:
    async def exercise() -> None:
        engine = create_async_engine(postgres_harness.url)
        try:
            case = await setup_case(engine)
            if invalid == "active":
                async with case.sessions() as db, db.begin():
                    plan = await db.get(ConversationProcessingPlan, case.plan.id)
                    plan.state = "quoted"
            identifiers = [case.plan.id]
            if invalid == "duplicate":
                identifiers.append(case.plan.id)
            if invalid == "missing":
                identifiers.append(uuid4())
            with pytest.raises(ValueError):
                async with case.sessions() as db, db.begin():
                    await CHANGE.change(db, args(identifiers, apply=True, fingerprint="f" * 64))
            async with case.sessions() as db:
                assert await ReportMinutes(db).latest(case.usage_id) is None
        finally:
            await engine.dispose()

    run(exercise())
