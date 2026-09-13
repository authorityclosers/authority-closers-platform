"""PostgreSQL proof for the explicit Sales Xray processing plan.

The fixture uses the existing native C1 setup and ReportingBroker.  Provider
effects are synthetic and local; this file never loads credentials or calls a
provider service.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuoteAcceptance,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.processing_plan import (
    PLAN_PRIVACY_REVISION,
    ConversationProcessingPlans,
    PlanAcceptance,
    ProcessingPlanScheduler,
)
from ac_platform.kernel.authz import ActorContext
from tests.database.test_conversation_authority_postgresql import (
    _application,
    _setup,
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    """Use a fresh disposable schema for every processing-plan test."""

    yield from _postgres_harness.__wrapped__()


async def _quote(setup: Any, key: str) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), setup.authority)
        return await service.quote(setup.actor, setup.prepared.recording_id, key=key)


async def _accept(setup: Any, quote: dict[str, Any], key: str) -> dict[str, Any]:
    payload = PlanAcceptance(
        plan_id=UUID(quote["id"]),
        plan_fingerprint=quote["plan_fingerprint"],
        privacy_revision=PLAN_PRIVACY_REVISION,
        accepted=True,
    )
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), setup.authority)
        return await service.accept(
            setup.actor,
            setup.prepared.recording_id,
            payload,
            key=key,
        )


async def _view(setup: Any, plan_id: UUID | None = None) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), setup.authority)
        if plan_id is None:
            return await service.get(setup.actor, setup.prepared.recording_id)
        return service.view(await database.get(ConversationProcessingPlan, plan_id))


async def _make_due(setup: Any, plan_id: UUID) -> None:
    """Make the bounded scheduler eligible without waiting in a DB proof."""

    async with setup.sessions() as database, database.begin():
        await database.execute(
            update(ConversationProcessingPlan)
            .where(ConversationProcessingPlan.id == plan_id)
            .values(next_check_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def _drive_to_completion(setup: Any, plan_id: UUID) -> dict[str, Any]:
    scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
    for _ in range(12):
        await setup.worker.run_once()
        await _make_due(setup, plan_id)
        await scheduler.step()
        view = await _view(setup)
        if view["state"] == "completed":
            return view
    raise AssertionError("The synthetic processing plan did not reach C6.")


async def _count(setup: Any, model: Any, *conditions: Any) -> int:
    async with setup.sessions() as database:
        value = await database.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(value or 0)


def test_processing_plan_quote_is_explicit_and_side_effect_free(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-quote")
            assert quote["accepted"] is False
            assert quote["state"] == "quoted"
            assert quote["cost_label"] == "₹0 · approved allowance"
            assert quote["max_cost_paise"] == 0
            assert [item["stage"] for item in quote["stages"]] == ["C2", "C4", "C5"]
            assert (
                await _count(
                    setup,
                    ConversationQuoteAcceptance,
                    ConversationQuoteAcceptance.tenant_id == setup.actor.tenant_id,
                )
                == 0
            )
            assert (
                await _count(
                    setup,
                    ConversationCommand,
                    ConversationCommand.action == "processing_plan_accepted",
                )
                == 0
            )
            async with setup.sessions() as database:
                plan = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                assert plan is not None and plan.acceptance_command_id is None
                assert plan.manifest is not None
                assert plan.manifest["source_sha256"] == setup.prepared.state.source_sha256
            assert await _count(setup, ConversationInferenceTask) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_processing_plan_acceptance_drives_c2_to_c6_with_exact_bindings(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-flow-quote")
            accepted = await _accept(setup, quote, "processing-plan-flow-accept")
            plan_id = UUID(quote["id"])
            assert accepted["accepted"] is True
            assert accepted["state"] == "active"

            completed = await _drive_to_completion(setup, plan_id)
            assert completed["state"] == "completed"
            assert completed["report_ready"] is True
            assert completed["current_stage"] == "C6"
            assert completed["report_run_id"]
            assert setup.broker.routes == ["elevenlabs", "groq", "groq"]

            async with setup.sessions() as database, database.begin():
                plan = await database.get(ConversationProcessingPlan, plan_id)
                assert plan is not None and plan.manifest is not None
                manifest = plan.manifest
                assert manifest["source_sha256"] == setup.prepared.state.source_sha256
                assert manifest["source_revision"] == 1
                assert manifest["profile"]
                tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(
                                ConversationInferenceTask.recording_id
                                == setup.prepared.recording_id
                            )
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                )
                assert [task.stage for task in tasks] == ["C2", "C4", "C5"]
                assert tasks[0].input_sha256 == manifest["source_sha256"]
                assert tasks[2].intent["request"]["profile"] == manifest["profile"]
                assert all(task.state == "completed" for task in tasks)
                checkpoints = list(
                    (
                        await database.scalars(
                            select(ConversationCheckpoint)
                            .where(
                                ConversationCheckpoint.recording_id == setup.prepared.recording_id
                            )
                            .order_by(ConversationCheckpoint.created_at)
                        )
                    ).all()
                )
                assert {checkpoint.stage for checkpoint in checkpoints} >= {
                    "C1",
                    "C2",
                    "C4",
                    "C5",
                    "C6",
                }
                draft = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == UUID(completed["report_run_id"]),
                        ConversationReportDraft.recording_id == setup.prepared.recording_id,
                        ConversationReportDraft.erased_at.is_(None),
                    )
                )
                assert draft is not None
                assert draft.source_sha256 == manifest["source_sha256"]
                assert draft.profile_sha256 == manifest["stages"][2]["profile_sha256"]
                assert draft.payload is not None
                assert draft.evidence_receipt["human_approved"] is False
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_processing_plan_acceptance_and_scheduler_restart_do_not_duplicate_effects(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-replay-quote")
            first = await _accept(setup, quote, "processing-plan-replay-accept")
            same_key = await _accept(setup, quote, "processing-plan-replay-accept")
            different_key = await _accept(setup, quote, "processing-plan-repeat-click")
            assert same_key["id"] == first["id"] == different_key["id"]
            assert (
                await _count(
                    setup,
                    ConversationCommand,
                    ConversationCommand.action == "processing_plan_accepted",
                )
                == 1
            )
            assert (
                await _count(
                    setup,
                    ConversationInferenceTask,
                    ConversationInferenceTask.stage == "C2",
                )
                == 1
            )

            plan_id = UUID(quote["id"])
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            await setup.worker.run_once()
            await _make_due(setup, plan_id)
            assert await scheduler.step() is True
            await _make_due(setup, plan_id)
            assert await scheduler.step() is True
            assert (
                await _count(
                    setup,
                    ConversationInferenceTask,
                    ConversationInferenceTask.stage == "C4",
                )
                == 1
            )
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_processing_plan_rejects_cross_owner_and_session_reads_or_acceptance(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-owner-quote")
            other = await seed(setup.engine, tenant_id=setup.actor.tenant_id)
            other_actor = other.actor
            payload = PlanAcceptance(
                plan_id=UUID(quote["id"]),
                plan_fingerprint=quote["plan_fingerprint"],
                privacy_revision=PLAN_PRIVACY_REVISION,
                accepted=True,
            )
            async with setup.sessions() as database, database.begin():
                service = ConversationProcessingPlans(
                    _application(setup, database), setup.authority
                )
                with pytest.raises(ConversationNotFound):
                    await service.get(other_actor, setup.prepared.recording_id)
                with pytest.raises(ConversationNotFound):
                    await service.accept(
                        other_actor,
                        setup.prepared.recording_id,
                        payload,
                        key="processing-plan-other-owner-accept",
                    )
                wrong_session = ActorContext(setup.actor.person_id, uuid4(), setup.actor.tenant_id)
                with pytest.raises(ConversationDenied):
                    await service.get(wrong_session, setup.prepared.recording_id)
            assert await _count(setup, ConversationInferenceTask) == 0
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_processing_plan_queued_stage_is_fenced_by_current_authority(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-expiry-quote")
            await _accept(setup, quote, "processing-plan-expiry-accept")
            expired = setup.bundle.model_copy(
                update={"expires_at_epoch": int(setup.prepared.state.now.timestamp()) - 1}
            )
            setup.bundle_box["bundle"] = expired
            assert await setup.worker.run_once()
            assert setup.broker.calls == 0
            async with setup.sessions() as database:
                task = await database.scalar(
                    select(ConversationInferenceTask).where(
                        ConversationInferenceTask.stage == "C2",
                        ConversationInferenceTask.recording_id == setup.prepared.recording_id,
                    )
                )
                assert task is not None and task.state == "failed"
                assert task.checkpoint_id is None
            assert (
                await _count(setup, ConversationCheckpoint, ConversationCheckpoint.stage == "C2")
                == 0
            )
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_processing_plan_history_is_immutable_and_erasure_only_erases_content(
    postgres_harness: Any, tmp_path: Any
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-immutable-quote")
            await _accept(setup, quote, "processing-plan-immutable-accept")
            plan_id = UUID(quote["id"])

            with pytest.raises(DBAPIError, match="immutable"):
                async with setup.sessions() as database, database.begin():
                    plan = await database.get(ConversationProcessingPlan, plan_id)
                    assert plan is not None
                    plan.plan_sha256 = "f" * 64
                    await database.flush()

            async with setup.sessions() as database:
                link = await database.scalar(
                    select(ConversationPlanStageAuthorization).where(
                        ConversationPlanStageAuthorization.plan_id == plan_id
                    )
                )
                assert link is not None
                link_id = link.quote_id

            with pytest.raises(DBAPIError, match="append-only|immutable"):
                async with setup.sessions() as database, database.begin():
                    link = await database.get(ConversationPlanStageAuthorization, link_id)
                    assert link is not None
                    link.cache_key = "e" * 64
                    await database.flush()

            with pytest.raises(DBAPIError, match="append-only|immutable"):
                async with setup.sessions() as database, database.begin():
                    link = await database.get(ConversationPlanStageAuthorization, link_id)
                    assert link is not None
                    await database.delete(link)
                    await database.flush()

            async with setup.sessions() as database, database.begin():
                deleted = await ConversationApplication(
                    database, clock=lambda: setup.prepared.state.now
                ).request_deletion(
                    setup.actor,
                    setup.prepared.recording_id,
                    key="processing-plan-delete",
                )
            assert deleted["state"] == "deleting"
            assert await setup.prepared.worker.run_once()
            async with setup.sessions() as database, database.begin():
                plan = await database.get(ConversationProcessingPlan, plan_id)
                link = await database.get(ConversationPlanStageAuthorization, link_id)
                assert plan is not None and plan.erased_at is not None
                assert plan.manifest is None and plan.state == "cancelled"
                assert link is not None
                with pytest.raises(ConversationNotFound):
                    await ConversationProcessingPlans(
                        ConversationApplication(database, clock=lambda: setup.prepared.state.now),
                        setup.authority,
                    ).get(setup.actor, setup.prepared.recording_id)
        finally:
            await setup.engine.dispose()

    run(exercise())
