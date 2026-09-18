"""PostgreSQL proof for the explicit Sales Xray processing plan.

The fixture uses the existing native C1 setup and ReportingBroker.  Provider
effects are synthetic and local; this file never loads credentials or calls a
provider service.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.activation_contract import AcquisitionStagePolicy
from ac_platform.conversation_intelligence.application import (
    AUDIOATLAS_RECIPE,
    ConversationApplication,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import SourceBinding, canonical
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance, RunIntent
from ac_platform.conversation_intelligence.entitlements import (
    BudgetAccount,
    ExecutionPermission,
    MinuteAccount,
    Quote,
    SettlementReceipt,
    mark_dispatched,
    reserve,
    settle,
)
from ac_platform.conversation_intelligence.inference import TRANSCRIPT_RECIPE, ConversationInference
from ac_platform.conversation_intelligence.inference_tasks import InferenceTaskError
from ac_platform.conversation_intelligence.models import (
    ConversationAnalysisSettings,
    ConversationBudgetAccount,
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationQuote,
    ConversationQuoteAcceptance,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.processing_plan import (
    PLAN_PRIVACY_REVISION,
    ConversationProcessingPlans,
    PlanAcceptance,
    ProcessingPlanScheduler,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.conversation_intelligence.provider_registry import parse_registry_config
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from tests.database.test_conversation_authority_postgresql import (
    _application,
    _refs,
    _registry_config,
    _setup,
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_worker_postgresql import _add_quote, _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    """Use a fresh disposable schema for every processing-plan test."""

    yield from _postgres_harness.__wrapped__()


async def _quote(
    setup: Any,
    key: str,
    *,
    storage: Any = None,
    recording_id: UUID | None = None,
) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(
            _application(setup, database), setup.authority, storage
        )
        return await service.quote(
            setup.actor, recording_id or setup.prepared.recording_id, key=key
        )


def test_admin_analysis_settings_bound_new_plan_only(postgres_harness: Any, tmp_path: Any) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as database, database.begin():
                database.add(
                    ConversationAnalysisSettings(
                        id=uuid4(),
                        tenant_id=setup.actor.tenant_id,
                        person_id=setup.actor.person_id,
                        session_id=setup.actor.session_id,
                        revision=1,
                        c4_max_requests=1,
                        c4_max_completion_tokens=512,
                        c5_max_completion_tokens=512,
                        c5_output_profile="standard",
                        created_at=setup.prepared.state.now,
                    )
                )
            quote = await _quote(setup, "analysis-settings-plan")
            async with setup.sessions() as database:
                row = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                assert row is not None and row.manifest is not None
                stages = row.manifest["stages"]
                assert stages[1]["max_requests"] == 1
                assert stages[1]["max_completion_tokens"] == 512
                assert stages[2]["max_completion_tokens"] == 512
                assert row.manifest["output_profile"] == "standard"
                assert row.manifest["analysis_settings_revision"] == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


async def _accept(
    setup: Any,
    quote: dict[str, Any],
    key: str,
    *,
    storage: Any = None,
    recording_id: UUID | None = None,
) -> dict[str, Any]:
    payload = PlanAcceptance(
        plan_id=UUID(quote["id"]),
        plan_fingerprint=quote["plan_fingerprint"],
        privacy_revision=PLAN_PRIVACY_REVISION,
        accepted=True,
    )
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(
            _application(setup, database), setup.authority, storage
        )
        return await service.accept(
            setup.actor,
            recording_id or setup.prepared.recording_id,
            payload,
            key=key,
        )


async def _duplicate_recording(setup: Any, key: str) -> UUID:
    """Create a second ready recording with the exact source bytes and C1 proof."""

    intent = setup.prepared.state.recording_intent.model_copy(
        update={
            "source_bytes": len(setup.prepared.data),
            "content_type": "audio/wav",
        }
    )
    async with setup.sessions() as database, database.begin():
        registered = await ConversationApplication(
            database, clock=lambda: setup.prepared.state.now
        ).register(setup.actor, intent, key=f"{key}-register")
    recording_id = UUID(registered["id"])
    chunks = tuple(
        setup.prepared.data[offset : offset + 1_048_576]
        for offset in range(0, len(setup.prepared.data), 1_048_576)
    )
    async with setup.sessions() as database, database.begin():
        stored = await ConversationApplication(
            database, clock=lambda: setup.prepared.state.now
        ).store_source(
            setup.actor,
            recording_id,
            chunks=chunks,
            storage=setup.prepared.storage,
        )
    assert stored["state"] == "ready"
    local_quote_id = await _add_quote(
        setup.sessions,
        setup.prepared.state,
        recording_id,
        setup.bundle.budget_scope_id,
        setup.prepared.state.source_sha256,
    )
    async with setup.sessions() as database, database.begin():
        requested = await ConversationApplication(
            database, clock=lambda: setup.prepared.state.now
        ).request_run(
            setup.actor,
            RunIntent(
                recording_id=recording_id,
                source_revision="1",
                quote_id=local_quote_id,
                recipe_revision=AUDIOATLAS_RECIPE,
            ),
            key=f"{key}-local-run",
        )
    assert await setup.prepared.worker.run_once()
    assert requested["state"] == "queued"
    return recording_id


async def _view(
    setup: Any, plan_id: UUID | None = None, *, recording_id: UUID | None = None
) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), setup.authority)
        if plan_id is None:
            return await service.get(setup.actor, recording_id or setup.prepared.recording_id)
        return service.view(await database.get(ConversationProcessingPlan, plan_id))


async def _source_c2(setup: Any, key: str) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        application = _application(setup, database)
        quoted = await setup.authority.issue(
            application,
            setup.actor,
            setup.prepared.recording_id,
            key=f"{key}-quote",
        )
        service = ConversationInference(application, authority=setup.authority)
        await service.accept(
            setup.actor,
            setup.prepared.recording_id,
            UUID(quoted["id"]),
            QuoteAcceptance(
                quote_fingerprint=quoted["quote_fingerprint"],
                privacy_revision=quoted["privacy_revision"],
                accepted=True,
            ),
        )
        return await service.request_transcription(
            setup.actor,
            setup.prepared.recording_id,
            UUID(quoted["id"]),
            key=f"{key}-run",
        )


def test_duplicate_upload_reuses_retained_c2_without_a_second_asr_call(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """A verified retained C2 response completes the duplicate's full report path."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source_run = await _source_c2(setup, "retained-c2-source")
            assert await setup.worker.run_once()
            assert setup.broker.calls == 1

            async with setup.sessions() as database:
                source_task = await database.get(ConversationInferenceTask, UUID(source_run["id"]))
                assert source_task is not None
                source_job = await database.get(Job, source_task.job_id)
                assert source_job is not None
                source_quote = await database.get(ConversationQuote, source_task.quote_id)
                assert source_quote is not None
                source_budget = await database.get(
                    ConversationBudgetAccount, source_quote.budget_scope_id
                )
                assert source_budget is not None
                source_budget_snapshot = source_budget.snapshot
                source_snapshot = (
                    source_task.state,
                    source_task.checkpoint_id,
                    source_job.status,
                    source_job.provider_receipt_digest,
                )

            target_recording_id = await _duplicate_recording(setup, "retained-c2-target")
            target_quote = await _quote(
                setup,
                "retained-c2-target-quote",
                storage=setup.prepared.storage,
                recording_id=target_recording_id,
            )
            accepted = await _accept(
                setup,
                target_quote,
                "retained-c2-target-accept",
                storage=setup.prepared.storage,
                recording_id=target_recording_id,
            )
            assert accepted["state"] == "active"
            assert setup.broker.calls == 1

            async with setup.sessions() as database:
                target_tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(ConversationInferenceTask.recording_id == target_recording_id)
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                )
                target_c2 = next(task for task in target_tasks if task.stage == "C2")
                target_job = await database.get(Job, target_c2.job_id)
                assert target_job is not None and target_job.provider_receipt is not None
                marker = target_job.provider_receipt["retained_reuse"]
                assert marker["provider_calls"] == 0
                assert marker["source_run_id"] == str(source_task.run_id)
                assert target_job.provider_receipt["raw_blob_id"] == str(source_task.run_id)
                assert target_job.external_side_effect is False
                assert target_job.dispatch_started_at is None
                assert target_job.provider_idempotency_key is None
                assert target_c2.state == "completed"
                # ConversationApplication.get_run requires a caller-owned
                # transaction. Use a separate inspection session so the
                # preceding ORM reads do not leave an implicit transaction
                # with the wrong origin.
                async with setup.sessions() as view_database, view_database.begin():
                    target_view = await ConversationApplication(
                        view_database, clock=lambda: setup.prepared.state.now
                    ).get_run(setup.actor, target_c2.run_id)
                assert target_view["provider_calls"] == 0

            completed = await _drive_to_completion(
                setup, UUID(target_quote["id"]), recording_id=target_recording_id
            )
            assert completed["state"] == "completed"
            assert completed["report_ready"] is True
            assert setup.broker.calls == 3
            assert setup.broker.routes == ["elevenlabs", "groq", "groq"]

            async with setup.sessions() as database:
                source_task = await database.get(ConversationInferenceTask, UUID(source_run["id"]))
                assert source_task is not None
                source_job = await database.get(Job, source_task.job_id)
                assert source_job is not None
                assert (
                    source_task.state,
                    source_task.checkpoint_id,
                    source_job.status,
                    source_job.provider_receipt_digest,
                ) == source_snapshot
                source_budget = await database.get(
                    ConversationBudgetAccount, source_quote.budget_scope_id
                )
                assert source_budget is not None
                current_source_snapshot = source_budget.snapshot
                assert {
                    key: value
                    for key, value in current_source_snapshot.items()
                    if key != "reservations"
                } == {
                    key: value
                    for key, value in source_budget_snapshot.items()
                    if key != "reservations"
                }
                current_reservations = {
                    item["reservation_id"]: item for item in current_source_snapshot["reservations"]
                }
                for original_reservation in source_budget_snapshot["reservations"]:
                    assert (
                        current_reservations[original_reservation["reservation_id"]]
                        == original_reservation
                    )
                target_tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask).where(
                                ConversationInferenceTask.recording_id == target_recording_id
                            )
                        )
                    ).all()
                )
                assert sorted(task.stage for task in target_tasks) == ["C2", "C4", "C5"]
                assert all(task.state == "completed" for task in target_tasks)
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_duplicate_upload_skips_unsafe_retained_c2_and_runs_fresh_asr(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """An incompatible retained candidate must not block a new authorised upload."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, asr_provider="deepgram")
        try:
            source_run = await _source_c2(setup, "unsafe-retained-c2-source")
            assert await setup.worker.run_once()
            assert setup.broker.calls == 1

            # Move the active approved ASR route forward through the provider
            # configuration contract.  The retained source was completed under
            # Deepgram; the duplicate now requests the current ElevenLabs
            # route.  Its immutable task remains intact, but its checkpoint
            # cache key is incompatible with the current plan.  The duplicate
            # must fall through to a fresh provider request rather than relying
            # on an illegal mutation of immutable inference history.
            current = _registry_config("hosted-test-config-v2", asr_provider="elevenlabs")
            async with setup.sessions() as database, database.begin():
                config_view = await ConversationProviderAdmin(
                    ConversationApplication(database, clock=lambda: setup.prepared.state.now)
                ).save(
                    setup.actor,
                    current.as_dict(),
                    expected_revision=1,
                    key="hosted-config-v2",
                )
            current = parse_registry_config(config_view["configuration"])
            elevenlabs_refs = _refs("elevenlabs")
            elevenlabs_refs.pop("endpoint_approval_ref")
            stages = tuple(
                stage.model_copy(
                    update={
                        # A route change is a new immutable stage approval.  Keep
                        # the prior Deepgram approval (and its reservation) intact;
                        # the duplicate must be admitted against the new
                        # ElevenLabs approval rather than consuming the old
                        # approval's request allowance.
                        "id": uuid4() if stage.stage == "C2" else stage.id,
                        "configuration_sha256": config_view["configuration_sha256"],
                        **(
                            {
                                "provider_id": "elevenlabs",
                                "model_id": "scribe_v2",
                                "recipe_revision": TRANSCRIPT_RECIPE,
                                **elevenlabs_refs,
                            }
                            if stage.stage == "C2"
                            else {}
                        ),
                    }
                )
                for stage in setup.bundle.stages
            )
            policy = setup.bundle.acquisition_policy
            assert policy is not None
            policy_stages = tuple(
                AcquisitionStagePolicy.model_validate(
                    stage.model_dump(exclude={"id", "tenant_id", "person_id", "source_sha256"})
                )
                for stage in stages
            )
            new_bundle = setup.bundle.model_copy(
                update={
                    "stages": stages,
                    "acquisition_policy": policy.model_copy(update={"stages": policy_stages}),
                }
            )
            setup.bundle_box["bundle"] = new_bundle
            async with setup.sessions() as database, database.begin():
                await ConversationProviderAdmin(
                    ConversationApplication(database, clock=lambda: setup.prepared.state.now)
                ).activate(
                    setup.actor,
                    target_revision=2,
                    expected_revision=2,
                    key="hosted-config-activation-v2",
                    bundle=new_bundle,
                )
            assert current.digest == config_view["configuration_sha256"]

            async with setup.sessions() as database, database.begin():
                source_task = await database.get(ConversationInferenceTask, UUID(source_run["id"]))
                assert source_task is not None
                assert source_task.state == "completed"

            target_recording_id = await _duplicate_recording(setup, "unsafe-retained-c2-target")
            target_quote = await _quote(
                setup,
                "unsafe-retained-c2-target-quote",
                storage=setup.prepared.storage,
                recording_id=target_recording_id,
            )
            accepted = await _accept(
                setup,
                target_quote,
                "unsafe-retained-c2-target-accept",
                storage=setup.prepared.storage,
                recording_id=target_recording_id,
            )
            assert accepted["state"] == "active"
            assert setup.broker.calls == 1

            assert await setup.worker.run_once()
            assert setup.broker.calls == 2
            completed = await _drive_to_completion(
                setup, UUID(target_quote["id"]), recording_id=target_recording_id
            )
            assert completed["state"] == "completed"
            assert completed["report_ready"] is True
            assert setup.broker.calls == 4
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_paused_plan_acceptance_preserves_quote_and_can_resume(
    postgres_harness: Any, tmp_path: Any
) -> None:
    from ac_platform.conversation_intelligence.execution_control import ConversationExecutionPaused
    from tests.database.test_conversation_execution_control_postgresql import pause

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, funded=True)
        try:
            quote = await _quote(setup, "pause-plan-quote")
            async with setup.sessions() as database:
                before = (
                    await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                ).snapshot
            await pause(setup)
            with pytest.raises(ConversationExecutionPaused):
                await _accept(setup, quote, "pause-plan-accept")
            async with setup.sessions() as database:
                plan = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                assert plan.state == "quoted" and plan.acceptance_command_id is None
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert budget.snapshot == before
            assert setup.broker.calls == 0
            await pause(setup, value=False, revision=1, key="resume-plan")
            accepted = await _accept(setup, quote, "pause-plan-accept")
            assert accepted["state"] == "active"
        finally:
            await setup.engine.dispose()

    run(exercise())


async def _make_due(setup: Any, plan_id: UUID) -> None:
    """Make the bounded scheduler eligible without waiting in a DB proof."""

    async with setup.sessions() as database, database.begin():
        await database.execute(
            update(ConversationProcessingPlan)
            .where(ConversationProcessingPlan.id == plan_id)
            .values(next_check_at=datetime.now(UTC) - timedelta(seconds=1))
        )


async def _drive_to_completion(
    setup: Any, plan_id: UUID, *, recording_id: UUID | None = None
) -> dict[str, Any]:
    scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
    for _ in range(12):
        await setup.worker.run_once()
        await _make_due(setup, plan_id)
        await scheduler.step()
        view = await _view(setup, recording_id=recording_id)
        if view["state"] == "completed":
            return view
    raise AssertionError("The synthetic processing plan did not reach C6.")


async def _count(setup: Any, model: Any, *conditions: Any) -> int:
    async with setup.sessions() as database:
        value = await database.scalar(select(func.count()).select_from(model).where(*conditions))
    return int(value or 0)


async def _consume_remaining_fixture_minutes(setup: Any) -> int:
    """Persist one typed prior-use transition while keeping ledger history intact.

    This is test fixture setup only.  It deliberately uses the pure paired-ledger
    functions, then persists each resulting snapshot through the ORM so the plan
    proof starts with a real settled debit and no synthetic balance overwrite.
    """

    now_epoch = int(setup.prepared.state.now.timestamp())
    synthetic_recording_id = str(uuid4())

    async with setup.sessions() as database, database.begin():
        minutes_row = await database.get(
            ConversationMinuteAccount,
            (setup.actor.tenant_id, setup.actor.person_id),
        )
        budget_row = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
        assert minutes_row is not None and budget_row is not None
        minutes = MinuteAccount.from_dict(minutes_row.snapshot)
        budget = BudgetAccount.from_dict(budget_row.snapshot)
        prior_balance = minutes.available_seconds
        assert prior_balance > 0
        synthetic_source_sha256 = hashlib.sha256(
            f"synthetic-prior-source-{synthetic_recording_id}".encode()
        ).hexdigest()
        quote = Quote(
            quote_id=str(uuid4()),
            source=SourceBinding(
                str(setup.actor.tenant_id),
                synthetic_recording_id,
                synthetic_source_sha256,
                "1",
            ),
            account_id=str(setup.actor.person_id),
            budget_scope_id=str(setup.bundle.budget_scope_id),
            provider_id="synthetic-prior-debit",
            provider_model="synthetic-ledger",
            recipe_revision="synthetic-prior-ledger-v1",
            operation="prior_legitimate_audio_usage",
            input_sha256=synthetic_source_sha256,
            privacy_revision="synthetic-prior-privacy-v1",
            permission_ref="synthetic-prior-permission",
            provider_terms_ref="synthetic-prior-terms",
            retention_ref="synthetic-prior-retention",
            professional_gate_ref="synthetic-prior-professional-gate",
            pricing_ref="synthetic-prior-zero-price",
            entitlement_seconds=prior_balance,
            max_cost_paise=0,
            created_at_epoch=now_epoch - 1,
            expires_at_epoch=now_epoch + 3600,
        )
        permission = ExecutionPermission(
            authorization_ref="synthetic-prior-authorization",
            quote_fingerprint=quote.fingerprint,
            approved_by=str(setup.actor.person_id),
            expires_at_epoch=now_epoch + 3600,
        )

        def persist(transition: Any) -> None:
            if not transition.changed:
                return
            minutes_row.snapshot = transition.minutes.as_dict()
            budget_row.snapshot = transition.budget.as_dict()
            minutes_row.revision += 1
            budget_row.revision += 1

        held = reserve(
            minutes,
            budget,
            f"synthetic-prior-reservation-{uuid4()}",
            quote,
            permission,
            now_epoch,
        )
        persist(held)
        dispatched = mark_dispatched(
            held.minutes,
            held.budget,
            held.reservation.reservation_id,
            f"synthetic-prior-attempt-{uuid4()}",
            now_epoch,
        )
        persist(dispatched)
        receipt = SettlementReceipt(
            reservation_id=dispatched.reservation.reservation_id,
            quote_fingerprint=quote.fingerprint,
            provider_id=quote.provider_id,
            attempt_id=dispatched.reservation.attempt_id or "",
            actual_seconds=prior_balance,
            actual_paise=0,
            receipt_ref="synthetic-prior-settlement",
        )
        settled = settle(
            dispatched.minutes,
            dispatched.budget,
            dispatched.reservation.reservation_id,
            receipt,
        )
        persist(settled)
        assert settled.reservation.state == "settled"
        assert settled.minutes.available_seconds == 0
        assert settled.budget.available_paise == 0
        return prior_balance


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


def test_processing_plan_finishes_after_last_audio_minute_with_zero_cost_provider_stages(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """A zero balance after C1 does not block the approved hosted report path."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            async with setup.sessions() as database:
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                before_debit = MinuteAccount.from_dict(minutes.snapshot)
                existing_grants = before_debit.grants
                existing_committed_seconds = sum(
                    reservation.committed_seconds for reservation in before_debit.reservations
                )

            prior_balance = await _consume_remaining_fixture_minutes(setup)
            async with setup.sessions() as database:
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert minutes is not None
                initial_account = MinuteAccount.from_dict(minutes.snapshot)
                assert initial_account.available_seconds == 0
                assert initial_account.grants == existing_grants
                prior_debit = next(
                    reservation
                    for reservation in initial_account.reservations
                    if reservation.quote.provider_id == "synthetic-prior-debit"
                )
                assert prior_debit.state == "settled"
                assert prior_debit.committed_seconds == prior_balance

            quote = await _quote(setup, "processing-plan-zero-balance-quote")
            plan_id = UUID(quote["id"])
            assert quote["max_entitlement_seconds"] == 0
            assert [item["stage"] for item in quote["stages"]] == ["C2", "C4", "C5"]
            viewed = await _view(setup, plan_id)
            assert viewed["max_entitlement_seconds"] == 0
            assert viewed["plan_fingerprint"] == quote["plan_fingerprint"]

            accepted = await _accept(setup, quote, "processing-plan-zero-balance-accept")
            assert accepted["state"] == "active"
            async with setup.sessions() as database:
                after_first_accept = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert after_first_accept is not None
                first_account = MinuteAccount.from_dict(after_first_accept.snapshot)
                assert first_account.available_seconds == 0
                assert first_account.grants == existing_grants

            # Retrieval and both replay forms of the owner acceptance cannot
            # debit the already exhausted audio allowance again.
            same_acceptance = await _accept(setup, quote, "processing-plan-zero-balance-accept")
            different_key_acceptance = await _accept(
                setup, quote, "processing-plan-zero-balance-repeat-click"
            )
            assert same_acceptance["id"] == different_key_acceptance["id"] == str(plan_id)
            async with setup.sessions() as database:
                after_replay = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                assert after_replay is not None
                replay_account = MinuteAccount.from_dict(after_replay.snapshot)
                assert replay_account.available_seconds == 0
                assert replay_account.grants == existing_grants
                assert (
                    sum(
                        reservation.committed_seconds for reservation in replay_account.reservations
                    )
                    == existing_committed_seconds + prior_balance
                )
            assert (
                await _count(
                    setup,
                    ConversationCommand,
                    ConversationCommand.action == "processing_plan_accepted",
                )
                == 1
            )

            completed = await _drive_to_completion(setup, plan_id)
            assert completed["state"] == "completed"
            assert completed["report_ready"] is True
            assert completed["current_stage"] == "C6"
            assert completed["report_run_id"]
            assert setup.broker.routes == ["elevenlabs", "groq", "groq"]

            async with setup.sessions() as database:
                minutes = await database.get(
                    ConversationMinuteAccount,
                    (setup.actor.tenant_id, setup.actor.person_id),
                )
                budget = await database.get(ConversationBudgetAccount, setup.bundle.budget_scope_id)
                assert minutes is not None and budget is not None
                final_minutes = MinuteAccount.from_dict(minutes.snapshot)
                final_budget = BudgetAccount.from_dict(budget.snapshot)
                assert final_minutes.available_seconds == 0
                assert final_minutes.grants == existing_grants
                prior_debit = next(
                    reservation
                    for reservation in final_minutes.reservations
                    if reservation.quote.provider_id == "synthetic-prior-debit"
                )
                assert prior_debit.state == "settled"
                assert prior_debit.committed_seconds == prior_balance

                hosted_minute_reservations = [
                    reservation
                    for reservation in final_minutes.reservations
                    if reservation.permission.authorization_ref.startswith("hosted-stage-v1:")
                ]
                hosted_budget_reservations = [
                    reservation
                    for reservation in final_budget.reservations
                    if reservation.permission.authorization_ref.startswith("hosted-stage-v1:")
                ]
                assert len(hosted_minute_reservations) == 3
                assert len(hosted_budget_reservations) == 3
                # Successful content is not an invoice. Preserve the existing
                # provider-cost reconciliation hold while charging no further
                # user audio minutes and reserving no paid budget.
                assert all(
                    reservation.state == "uncertain"
                    and reservation.quote.entitlement_seconds == 0
                    and reservation.committed_seconds == 0
                    and reservation.committed_paise == 0
                    for reservation in hosted_minute_reservations
                )
                assert all(
                    reservation.state == "uncertain"
                    and reservation.quote.entitlement_seconds == 0
                    and reservation.committed_seconds == 0
                    and reservation.committed_paise == 0
                    for reservation in hosted_budget_reservations
                )

                provider_quotes = []
                for row in (
                    await database.scalars(
                        select(ConversationQuote).where(
                            ConversationQuote.recording_id == setup.prepared.recording_id,
                            ConversationQuote.tenant_id == setup.actor.tenant_id,
                            ConversationQuote.person_id == setup.actor.person_id,
                        )
                    )
                ).all():
                    provider_quote = Quote.from_dict(row.quote)
                    if provider_quote.provider_id in {"elevenlabs", "groq"}:
                        provider_quotes.append(provider_quote)
                assert len(provider_quotes) == 3
                assert all(
                    provider_quote.entitlement_seconds == 0 and provider_quote.max_cost_paise == 0
                    for provider_quote in provider_quotes
                )
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


def test_processing_plan_repairs_returned_invalid_c5_once_and_publishes_repaired_report(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """Exercise scheduler -> worker validation failure -> bounded repair -> C6."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            c5 = setup.bundle.stages[2].model_copy(update={"max_requests": 2})
            setup.bundle_box["bundle"] = setup.bundle.model_copy(
                update={"stages": (*setup.bundle.stages[:2], c5)}
            )
            original_execute = setup.broker.execute
            invalid_returned = False

            async def invalid_first_c5(reservation: Any, payload: bytes) -> ProviderResult:
                nonlocal invalid_returned
                if (
                    reservation.quote.provider_id == "groq"
                    and setup.broker.routes.count("groq") == 1
                    and not invalid_returned
                ):
                    invalid_returned = True
                    setup.broker.routes.append("groq")
                    setup.broker.calls += 1
                    setup.broker.payloads.append(payload)
                    envelope = {"choices": [{"message": {"content": json.dumps({})}}]}
                    raw = canonical(envelope)
                    return ProviderResult(
                        provider="groq",
                        model=reservation.quote.provider_model,
                        request_id="synthetic-c5-missing-field",
                        response_sha256=hashlib.sha256(raw).hexdigest(),
                        raw_json=raw,
                        data=envelope,
                        usage={"total_tokens": 0},
                        input_sha256=reservation.quote.input_sha256,
                    )
                return await original_execute(reservation, payload)

            setup.broker.execute = invalid_first_c5
            quote = await _quote(setup, "processing-plan-c5-repair-quote")
            assert quote["stages"][2]["max_requests"] == 2
            assert quote["automatic_c5_repair_cost_paise"] == 0
            await _accept(setup, quote, "processing-plan-c5-repair-accept")
            plan_id = UUID(quote["id"])
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            for _ in range(12):
                await setup.worker.run_once()
                await _make_due(setup, plan_id)
                await scheduler.step()
                view = await _view(setup, plan_id)
                if view["state"] == "completed":
                    break
            assert invalid_returned is True
            assert view["state"] == "completed"
            assert view["report_ready"] is True
            assert view["current_stage"] == "C6"
            assert view["stages"][2]["max_requests"] == 2

            async with setup.sessions() as database:
                plan = await database.get(ConversationProcessingPlan, plan_id)
                assert plan is not None
                assert plan.progress["c5_repair"]["attempt"] == 1
                assert plan.progress["c5_repair"]["failure_code"] == (
                    "conversation_report_payload_missing_field"
                )
                tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(
                                ConversationInferenceTask.recording_id
                                == setup.prepared.recording_id,
                                ConversationInferenceTask.stage == "C5",
                            )
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                )
                assert len(tasks) == 2
                assert tasks[0].state == "uncertain"
                assert tasks[1].state == "completed"
                assert tasks[1].intent["request"]["repair"]["attempt"] == 1
                assert view["report_run_id"] == str(tasks[1].run_id)
                original_job = await database.get(Job, tasks[0].job_id)
                assert original_job is not None and original_job.provider_receipt is not None
                assert original_job.provider_receipt["validation_state"] == "provider_returned"
                assert original_job.provider_receipt["raw_blob_id"] == str(tasks[0].run_id)
                report = await database.scalar(
                    select(ConversationReportDraft).where(
                        ConversationReportDraft.run_id == tasks[1].run_id,
                        ConversationReportDraft.recording_id == setup.prepared.recording_id,
                        ConversationReportDraft.erased_at.is_(None),
                    )
                )
                assert report is not None and report.payload is not None
            assert setup.broker.routes == ["elevenlabs", "groq", "groq", "groq"]
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


def test_deepgram_c2_receipt_advances_to_c4_without_reinvocation(
    postgres_harness: Any, tmp_path: Any
) -> None:
    """A completed Deepgram C2 receipt must survive the C3 planning boundary."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, asr_provider="deepgram")
        try:
            quote = await _quote(setup, "deepgram-processing-plan-quote")
            await _accept(setup, quote, "deepgram-processing-plan-accept")
            plan_id = UUID(quote["id"])
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)

            await setup.worker.run_once()
            assert setup.broker.routes == ["deepgram"]
            assert setup.broker.calls == 1

            await _make_due(setup, plan_id)
            assert await scheduler.step() is True

            async with setup.sessions() as database:
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
                assert [task.stage for task in tasks] == ["C2", "C4"]
                assert tasks[0].state == "completed"
                assert tasks[1].state == "queued"
                alignment = await database.scalar(
                    select(ConversationCheckpoint).where(
                        ConversationCheckpoint.recording_id == setup.prepared.recording_id,
                        ConversationCheckpoint.stage == "C3",
                    )
                )
                assert alignment is not None and alignment.payload is not None
                assert alignment.payload["timebase"]["transcript_timebase_id"] == (
                    "deepgram-native-seconds"
                )
                assert alignment.payload["timebase"]["mapping_status"] == (
                    "provider_native_clock_unmapped_to_decoded_audio_track"
                )

            # Planning reads the durable C2 receipt and must not invoke ASR again.
            assert setup.broker.routes == ["deepgram"]
            assert setup.broker.calls == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_scheduler_holds_strict_c5_input_failure_without_killing_worker(
    postgres_harness: Any, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            quote = await _quote(setup, "processing-plan-c5-budget-quote")
            await _accept(setup, quote, "processing-plan-c5-budget-accept")
            before_tasks = await _count(setup, ConversationInferenceTask)
            assert before_tasks == 1
            plan_id = UUID(quote["id"])
            await _make_due(setup, plan_id)

            async def fail_c5_input(self: Any, actor: Any, row: Any) -> None:
                raise InferenceTaskError("report_prompt_budget_exceeded")

            monkeypatch.setattr(ConversationProcessingPlans, "advance", fail_c5_input)
            scheduler = ProcessingPlanScheduler(setup.sessions, setup.authority)
            assert await scheduler.step() is True
            view = await _view(setup)
            assert view["state"] == "held"
            async with setup.sessions() as database:
                stored = await database.get(ConversationProcessingPlan, plan_id)
                assert stored is not None
                assert stored.progress == {
                    "failure_code": "processing_authorization_or_input_unavailable"
                }
            # The failed scheduler attempt must not append another task.
            assert await _count(setup, ConversationInferenceTask) == before_tasks
            assert await scheduler.step() is False
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
