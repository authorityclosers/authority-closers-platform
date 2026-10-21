"""AI on calls (owner, 21 Oct 2026) stops a call before the paid stage its level leaves out.

The processing plan reads the seller's level before transcription (C2) and before facts
(C4): Off holds the call before any provider request, Data only after its transcript;
each stop is recorded once, the plan says why, and the background readers that follow a
transcript (deep call data, one pass) leave such calls alone. Disposable PostgreSQL and
the synthetic local providers; nothing here calls a real provider.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from ac_platform.call_ai import policy as call_ai_policy
from ac_platform.call_ai import store
from ac_platform.call_ai.models import CallAiDecision, CallAiSettings
from ac_platform.conversation_intelligence.models import (
    ConversationInferenceTask,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.tenancy.models import Organisation
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import (
    _accept,
    _count,
    _drive_to_completion,
    _make_due,
    _quote,
    _setup,
)
from tests.database.test_conversation_processing_plan_postgresql import (
    postgres_harness as _postgres_harness,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()  # type: ignore[attr-defined]


async def _levels(setup: Any, default: str, people: dict[str, str] | None = None) -> None:
    """A saved settings revision for the fixture's workspace (newest wins)."""
    async with setup.sessions() as database, database.begin():
        current = await store.read(database, setup.prepared.state.tenant_id)
        database.add(
            CallAiSettings(
                id=uuid4(),
                tenant_id=setup.prepared.state.tenant_id,
                revision=(current.revision or 0) + 1,
                config={"default": default, "people": people or {}},
                created_by_person_id=setup.prepared.state.person_id,
                created_at=datetime.now(UTC),
            )
        )


async def _stages(setup: Any) -> list[str]:
    async with setup.sessions() as database:
        tasks = await database.scalars(
            select(ConversationInferenceTask)
            .where(ConversationInferenceTask.recording_id == setup.prepared.recording_id)
            .order_by(ConversationInferenceTask.created_at)
        )
        return [task.stage for task in tasks]


async def _decisions(setup: Any) -> list[tuple[str, str, str | None, UUID | None]]:
    async with setup.sessions() as database:
        rows = await database.scalars(
            select(CallAiDecision)
            .where(CallAiDecision.recording_id == setup.prepared.recording_id)
            .order_by(CallAiDecision.created_at)
        )
        return [(row.decision, row.level, row.stage, row.plan_id) for row in rows]


async def _plan(setup: Any, plan_id: UUID) -> ConversationProcessingPlan:
    async with setup.sessions() as database:
        row = await database.get(ConversationProcessingPlan, plan_id)
        assert row is not None
        return row


async def _run_until_held(setup: Any, plan_id: UUID) -> ConversationProcessingPlan:
    scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
    for _ in range(8):
        await setup.worker.run_once()
        await _make_due(setup, plan_id)
        await scheduler.step()
        row = await _plan(setup, plan_id)
        if row.state != "active":
            return row
    raise AssertionError("The plan never stopped.")


def test_off_holds_the_call_before_any_provider_request(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _levels(setup, "off")
            quote = await _quote(setup, "off-quote")
            accepted = await _accept(setup, quote, "off-accept")
            plan_id = UUID(quote["id"])
            # Accepting runs the first pass at once: held before transcription.
            assert accepted["state"] == "held"
            assert accepted["failure_code"] == "ai_off"
            assert accepted["current_stage"] == "C2"
            assert await _count(setup, ConversationInferenceTask) == 0
            assert setup.broker.routes == []
            row = await _plan(setup, plan_id)
            assert row.progress["ai_level"] == "off"
            assert row.progress["ai_level_source"] == "organisation"
            assert await _decisions(setup) == [("skipped", "off", "C2", plan_id)]
            # The scheduler never picks a held plan up again: still no request.
            await _make_due(setup, plan_id)
            await ProcessingPlanScheduler(setup.sessions, setup.authority).step()
            assert setup.broker.routes == [] and await _decisions(setup) == [
                ("skipped", "off", "C2", plan_id)
            ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_data_only_keeps_the_transcript_and_stops_before_facts_and_coaching(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _levels(setup, "data_only")
            quote = await _quote(setup, "data-only-quote")
            accepted = await _accept(setup, quote, "data-only-accept")
            plan_id = UUID(quote["id"])
            assert accepted["state"] == "active"
            held = await _run_until_held(setup, plan_id)
            assert held.state == "held"
            assert held.progress["failure_code"] == "ai_data_only"
            assert held.progress["current_stage"] == "C4"
            assert held.progress["ai_level"] == "data_only"
            # One paid request: the transcript. No facts (C4) or coaching (C5).
            assert await _stages(setup) == ["C2"]
            assert setup.broker.routes == ["elevenlabs"]
            assert await _decisions(setup) == [("skipped", "data_only", "C4", plan_id)]
            async with setup.sessions() as database:
                task = await database.scalar(select(ConversationInferenceTask))
                assert task is not None and task.state == "completed"
            # The readers that would analyse the call further leave it alone.
            async with setup.sessions() as database:
                assert not await database.run_sync(
                    lambda session: store.runs_beyond_transcript(
                        session.connection(),
                        setup.prepared.state.tenant_id,
                        setup.prepared.recording_id,
                    )
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_a_sellers_own_level_beats_the_default_and_auto_runs_in_full(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            # The organisation is Off, this seller is on Auto (full until the router).
            await _levels(setup, "off", {str(setup.prepared.state.person_id): "auto"})
            async with setup.sessions() as database:
                call = await store.level_for_call(
                    database, setup.prepared.state.tenant_id, setup.prepared.recording_id
                )
                assert (call.level, call.source, call.effective) == ("auto", "person", "full")
            quote = await _quote(setup, "auto-quote")
            await _accept(setup, quote, "auto-accept")
            completed = await _drive_to_completion(setup, UUID(quote["id"]))
            assert completed["report_ready"] is True
            assert await _stages(setup) == ["C2", "C4", "C5"]
            assert await _decisions(setup) == []
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_an_upgraded_call_runs_in_full_for_every_reader(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """ "Get full report" on one call: the plan and the background readers see Full for
    that call only. (The HTTP test runs the upgrade to its report, reusing the transcript.)"""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            await _levels(setup, "data_only")
            first = await _quote(setup, "upgrade-first-quote")
            await _accept(setup, first, "upgrade-first-accept")
            held = await _run_until_held(setup, UUID(first["id"]))
            assert held.progress["failure_code"] == "ai_data_only"
            async with setup.sessions() as database, database.begin():
                call = await store.level_for_call(
                    database, setup.prepared.state.tenant_id, setup.prepared.recording_id
                )
                await store.record_upgrade(
                    database,
                    tenant_id=setup.prepared.state.tenant_id,
                    recording_id=setup.prepared.recording_id,
                    call=call,
                    actor_person_id=setup.prepared.state.person_id,
                    now=datetime.now(UTC),
                )
            async with setup.sessions() as database:
                upgraded = await store.level_for_call(
                    database, setup.prepared.state.tenant_id, setup.prepared.recording_id
                )
                assert (upgraded.level, upgraded.source, upgraded.skipped_from) == (
                    "full",
                    "upgrade",
                    None,
                )
                assert await database.run_sync(
                    lambda session: store.runs_beyond_transcript(
                        session.connection(),
                        setup.prepared.state.tenant_id,
                        setup.prepared.recording_id,
                    )
                )
                # The seller's other calls stay Data only.
                assert (await store.read(database, setup.prepared.state.tenant_id)).config[
                    "default"
                ] == "data_only"
            assert [row[:3] for row in await _decisions(setup)] == [
                ("skipped", "data_only", "C4"),
                ("upgraded", "data_only", None),
            ]
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_settings_are_new_revisions_and_a_stale_save_is_refused(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        tenant = setup.prepared.state.tenant_id
        person = setup.prepared.state.person_id
        try:
            now = datetime.now(UTC)
            async with setup.sessions() as database, database.begin():
                before, after = await store.save(
                    database,
                    tenant,
                    {"default": "data_only", "people": {}},
                    expected_revision=None,
                    actor_person_id=person,
                    now=now,
                )
                assert (before.revision, after.revision) == (None, 1)
            async with setup.sessions() as database, database.begin():
                with pytest.raises(store.SettingsConflict):
                    await store.save(
                        database,
                        tenant,
                        {"default": "off", "people": {}},
                        expected_revision=None,
                        actor_person_id=person,
                        now=now,
                    )
            async with setup.sessions() as database, database.begin():
                _, latest = await store.save(
                    database,
                    tenant,
                    {"default": "off", "people": {str(person): "full"}},
                    expected_revision=1,
                    actor_person_id=person,
                    now=now,
                )
                assert latest.revision == 2
            async with setup.sessions() as database:
                rows = (
                    await database.scalars(
                        select(CallAiSettings)
                        .where(CallAiSettings.tenant_id == tenant)
                        .order_by(CallAiSettings.revision)
                    )
                ).all()
                # Append-only: the first revision is still there, unchanged.
                assert [(row.revision, row.config["default"]) for row in rows] == [
                    (1, "data_only"),
                    (2, "off"),
                ]
                assert (await store.read(database, tenant)).config["people"] == {
                    str(person): "full"
                }
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("organisation", [True, False])
def test_a_short_call_in_an_organisation_keeps_only_its_transcript(
    postgres_harness: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch, organisation: bool
) -> None:
    """Owner, 21 Oct 2026: in every organisation a call under a minute (here the 1-second
    fixture, so no conversation) stops after its transcript, its reason recorded; a personal
    workspace runs in full as before."""
    monkeypatch.setattr(call_ai_policy, "SHORT_RULE_OFF", frozenset())

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            if organisation:
                async with setup.sessions() as database, database.begin():
                    database.add(
                        Organisation(
                            tenant_id=setup.prepared.state.tenant_id,
                            creation_command_id=uuid4(),
                            domain_verification_token="fictional-organisation-" + "x" * 43,
                        )
                    )
            quote = await _quote(setup, "short-quote")
            await _accept(setup, quote, "short-accept")
            plan_id = UUID(quote["id"])
            if not organisation:
                completed = await _drive_to_completion(setup, plan_id)
                assert completed["report_ready"] is True
                assert await _stages(setup) == ["C2", "C4", "C5"]
                assert await _decisions(setup) == []
                return
            held = await _run_until_held(setup, plan_id)
            assert held.progress["failure_code"] == "ai_no_conversation"
            assert held.progress["ai_skip_reason"] == "no_conversation"
            assert held.progress["ai_level"] == "full"
            assert await _stages(setup) == ["C2"]
            assert setup.broker.routes == ["elevenlabs"]
            async with setup.sessions() as database:
                row = await database.scalar(select(CallAiDecision))
                assert row is not None
                assert (row.decision, row.level, row.stage, row.reason) == (
                    "skipped",
                    "full",
                    "C4",
                    "no_conversation",
                )
                assert not await database.run_sync(
                    lambda session: store.runs_beyond_transcript(
                        session.connection(),
                        setup.prepared.state.tenant_id,
                        setup.prepared.recording_id,
                    )
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
