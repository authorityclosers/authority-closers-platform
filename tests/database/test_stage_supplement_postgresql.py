"""Disposable PostgreSQL quote-to-scheduler proof for bounded C5 renewal."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, update

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.activation_contract import (
    InternalTesterApproval,
    StageCallSupplement,
)
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
)
from ac_platform.conversation_intelligence.checkpoints import canonical
from ac_platform.conversation_intelligence.contracts import QuoteAcceptance
from ac_platform.conversation_intelligence.entitlements import BudgetAccount
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.inference import ConversationInference
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.internal_tester import InternalTesterPolicy
from ac_platform.conversation_intelligence.models import (
    ConversationAnalysisSettings,
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
)
from ac_platform.conversation_intelligence.processing_actor import ProcessingActor
from ac_platform.conversation_intelligence.processing_plan import (
    ConversationProcessingPlans,
    PlanAcceptance,
    PlanManifest,
    ProcessingPlanScheduler,
    c5_repair_intent,
)
from ac_platform.conversation_intelligence.providers import ProviderResult
from ac_platform.conversation_intelligence.qualitative_pack import load_qualitative_pack
from ac_platform.conversation_intelligence.reporting_pipeline import (
    COACHING_RECIPE,
    ReportingPipeline,
    StageRequest,
)
from ac_platform.conversation_intelligence.reports import load_report_profile
from ac_platform.conversation_intelligence.stage_supplements import (
    processing_plan_sha256,
    supplemental_reservations,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.identity.sales_xray_profile import get_sales_xray_profile
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import (
    postgres_harness as _postgres_harness,
)
from tests.database.test_conversation_postgresql import run, seed
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_reporting_pipeline_postgresql import ReportingBroker
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    PREFIX,
    _headers,
    _setup,
)
from tests.database.test_conversation_worker_postgresql import (
    OfflineConversationWorker,
    _reconcile,
    _wav_one_second_48k,
)


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


class _BoundedRepairBroker(ReportingBroker):
    """Synthetic Gemini/ASR responses with one invalid C5 per plan."""

    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.c5_requests = 0

    async def execute(self, reservation: Any, payload: bytes) -> ProviderResult:
        result = await super().execute(reservation, payload)
        if reservation.quote.recipe_revision != COACHING_RECIPE:
            return result
        self.c5_requests += 1
        if self.c5_requests not in {1, 3}:
            return result
        invalid = {
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {"role": "model", "parts": [{"text": "{}"}]},
                }
            ]
        }
        raw = canonical(invalid)
        return ProviderResult(
            provider=reservation.quote.provider_id,
            model=reservation.quote.provider_model,
            request_id=f"synthetic-invalid-c5-{self.c5_requests}",
            response_sha256=hashlib.sha256(raw).hexdigest(),
            raw_json=raw,
            data=invalid,
            usage={"total_tokens": 20},
            input_sha256=reservation.quote.input_sha256,
        )


async def _direct_stage(
    setup: Any,
    actor: ProcessingActor,
    recording_id: UUID,
    request: StageRequest | None,
    *,
    key: str,
) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        app = ConversationApplication(database, clock=lambda: setup.clock[0])
        service = ConversationInference(app, authority=setup.authority)
        quote = await setup.authority.issue(
            app, actor, recording_id, key=f"{key}-quote", request=request
        )
        await service.accept(
            actor,
            recording_id,
            UUID(quote["id"]),
            QuoteAcceptance(
                quote_fingerprint=quote["quote_fingerprint"],
                privacy_revision=quote["privacy_revision"],
                accepted=True,
            ),
            request=request,
        )
        if request is None:
            return await service.request_transcription(
                actor, recording_id, UUID(quote["id"]), key=f"{key}-run"
            )
        return await service.request_stage(
            actor,
            recording_id,
            UUID(quote["id"]),
            key=f"{key}-run",
            request=request,
        )


def _c5_request(manifest: PlanManifest, c2_id: UUID, c4_ids: tuple[UUID, ...]) -> StageRequest:
    c5 = manifest.stages[2]
    return StageRequest(
        stage="C5",
        transcript_checkpoint_id=c2_id,
        fact_checkpoint_ids=c4_ids,
        provider=c5.provider_id,
        model=c5.model_id,
        max_input_chars=manifest.max_input_chars,
        max_completion_tokens=c5.max_completion_tokens,
        output_profile=manifest.output_profile,
        profile=manifest.profile,
        coaching_prompt_revision=manifest.coaching_prompt_revision,
        report_language=manifest.report_language,
        qualitative_pack_sha256=manifest.qualitative_pack_sha256,
    )


@pytest.mark.parametrize("named_tester_scope", [False, True], ids=["ordinary", "named-tester"])
def test_paid_exact_source_supplement_completes_primary_and_one_repair(
    postgres_harness: Any, tmp_path: Path, named_tester_scope: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            gemini=True,
            funded=True,
            text_cost_paise=100,
            asr_cost_paise=100,
            c2_max_requests=1,
            c4_max_requests=64,
            c5_max_requests=2,
        )
        data = _wav_one_second_48k()
        submission = UUID(int=uuid4().int)
        path = f"{PREFIX}/submissions/{submission}"
        worker: ConversationInferenceWorker | None = None
        owner_state = setup.state
        owner_token = setup.token
        try:
            if named_tester_scope:
                owner_state = await seed(setup.engine, tenant_id=setup.state.tenant_id)
                owner_token = secrets.token_urlsafe(32)
                token_pepper = setup.settings.session_token_pepper.get_secret_value().encode(
                    "utf-8"
                )
                tester_scope = InternalTesterApproval(
                    id=uuid4(),
                    email="dipak@authorityclosers.com",
                    authorization_ref="ref:approval:dipak-provider-count-test",
                    scopes=("provider_stage_request_count",),
                    reason="Approved internal tester exemption",
                )
                initial_bundle = setup.bundle_box["bundle"].model_copy(
                    update={"internal_tester_accounts": (tester_scope,)}
                )
                setup.bundle_box["bundle"] = initial_bundle
                setup.authority.tester_policy = InternalTesterPolicy(
                    lambda: setup.bundle_box["bundle"], "test"
                )
                async with setup.sessions() as database, database.begin():
                    await database.execute(
                        update(Person)
                        .where(Person.id == owner_state.person_id)
                        .values(email="dipak@authorityclosers.com")
                    )
                    await database.execute(
                        update(IdentitySession)
                        .where(IdentitySession.id == owner_state.session_id)
                        .values(
                            token_hash=hmac.new(
                                token_pepper,
                                owner_token.encode("ascii"),
                                hashlib.sha256,
                            ).digest()
                        )
                    )

            async with setup.sessions() as database:
                profile = await get_sales_xray_profile(database, person_id=owner_state.person_id)
                assert profile.profile_complete

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                client.cookies.set(setup.settings.session_cookie_name, owner_token)
                uploaded = await client.put(
                    path + "/source", content=data, headers=await _headers(client, data)
                )
                assert uploaded.status_code == 202, uploaded.text
            recording_id = UUID(uploaded.json()["recording_id"])
            await _reconcile(setup.sessions, setup.state)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await local.run_once()

            async with setup.sessions() as database, database.begin():
                ownership = GuestOwnership(setup.factory(database))
                actor = await ownership.resolve_processing_actor(
                    submission, actor=owner_state.actor
                )
                assert isinstance(actor, ProcessingActor)
                await setup.authority.claim_allowance(
                    ConversationApplication(database, clock=lambda: setup.clock[0]), actor
                )
                usage = await database.scalar(
                    select(ConversationAcquisitionUsage).where(
                        ConversationAcquisitionUsage.submission_id == submission
                    )
                )
                assert usage is not None
                assert usage.person_id == owner_state.person_id
                assert usage.visitor_id is None
                assert (
                    await database.scalar(
                        select(ConversationVisitorClaim).where(
                            ConversationVisitorClaim.person_id == owner_state.person_id
                        )
                    )
                    is None
                )

            async with setup.sessions() as database, database.begin():
                database.add(
                    ConversationAnalysisSettings(
                        id=uuid4(),
                        tenant_id=owner_state.tenant_id,
                        person_id=owner_state.person_id,
                        session_id=owner_state.session_id,
                        revision=1,
                        c4_max_requests=64,
                        c4_max_completion_tokens=1_400,
                        c5_max_completion_tokens=1_800,
                        c5_output_profile="detailed",
                        c5_coaching_prompt_revision="coaching-v4",
                        report_language_default="en",
                        created_at=setup.clock[0],
                    )
                )

            broker = _BoundedRepairBroker(data)
            worker = ConversationInferenceWorker(
                setup.sessions,
                setup.runtime.storage,
                broker,
                authority=setup.authority,
            )
            c2_run = await _direct_stage(setup, actor, recording_id, None, key="supplement-c2")
            assert await worker.run_once()
            async with setup.sessions() as database:
                c2_task = await database.get(ConversationInferenceTask, UUID(c2_run["id"]))
                assert c2_task is not None and c2_task.checkpoint_id is not None
                c2_id = c2_task.checkpoint_id

            c4_request = StageRequest(
                stage="C4",
                transcript_checkpoint_id=c2_id,
                provider="gemini",
                model="gemini-3.8-flash",
                max_input_chars=16_000,
                max_completion_tokens=1_400,
                fact_prompt_revision="facts-v2",
            )
            c4_run = await _direct_stage(
                setup, actor, recording_id, c4_request, key="supplement-c4"
            )
            assert await worker.run_once()
            async with setup.sessions() as database:
                c4_task = await database.get(ConversationInferenceTask, UUID(c4_run["id"]))
                assert c4_task is not None and c4_task.checkpoint_id is not None
                c4_ids = (c4_task.checkpoint_id,)

            # Use the same C5 task path to retain two historical reservations: a
            # provider-returned invalid primary and its one authorized repair.
            old_c5_request = StageRequest(
                stage="C5",
                transcript_checkpoint_id=c2_id,
                fact_checkpoint_ids=c4_ids,
                provider="gemini",
                model="gemini-3.8-flash",
                max_input_chars=16_000,
                max_completion_tokens=1_800,
                output_profile="detailed",
                profile=load_report_profile(),
                coaching_prompt_revision="coaching-v4",
                report_language="en",
                qualitative_pack_sha256=load_qualitative_pack().sha256,
            )
            old_c5_run = await _direct_stage(
                setup, actor, recording_id, old_c5_request, key="supplement-old-c5"
            )
            assert await worker.run_once()
            async with setup.sessions() as database:
                original = await database.get(ConversationInferenceTask, UUID(old_c5_run["id"]))
                assert original is not None and original.state == "uncertain"
                original_job = await database.get(Job, original.job_id)
                assert original_job is not None
            if named_tester_scope:
                dispatches_before_replay = broker.c5_requests
                same_attempt = await _direct_stage(
                    setup,
                    actor,
                    recording_id,
                    old_c5_request,
                    key="supplement-old-c5",
                )
                assert same_attempt["id"] == old_c5_run["id"]
                with pytest.raises(
                    ConversationConflict,
                    match="previous stage requires explicit recovery",
                ):
                    await _direct_stage(
                        setup,
                        actor,
                        recording_id,
                        old_c5_request,
                        key="supplement-old-c5-new-attempt",
                    )
                assert broker.c5_requests == dispatches_before_replay
            repair = c5_repair_intent(original, original_job)
            assert repair is not None
            repair_run = await _direct_stage(
                setup,
                actor,
                recording_id,
                old_c5_request.model_copy(update={"repair": repair}),
                key="supplement-old-c5-repair",
            )
            assert await worker.run_once()
            async with setup.sessions() as database:
                repaired = await database.get(ConversationInferenceTask, UUID(repair_run["id"]))
                assert repaired is not None and repaired.state == "completed"

            async with setup.sessions() as database, database.begin():
                app = ConversationApplication(database, clock=lambda: setup.clock[0])
                preliminary = await ConversationProcessingPlans(
                    app, setup.authority, setup.runtime.storage
                ).quote(
                    actor,
                    recording_id,
                    key="supplement-preliminary-plan",
                    report_language="mr-Deva+en",
                )
                plan_row = await database.get(ConversationProcessingPlan, UUID(preliminary["id"]))
                assert plan_row is not None and plan_row.manifest is not None
                preliminary_manifest = PlanManifest.model_validate_json(
                    canonical(plan_row.manifest)
                )
                new_request = _c5_request(preliminary_manifest, c2_id, c4_ids)
                recording = await app._recording(actor, recording_id)
                prepared = await ReportingPipeline(
                    ConversationInference(app, authority=setup.authority)
                ).plan(recording, new_request)
                logical_plan_sha256 = processing_plan_sha256(preliminary_manifest.as_dict())
                usage = await database.scalar(
                    select(ConversationAcquisitionUsage).where(
                        ConversationAcquisitionUsage.submission_id == submission
                    )
                )
                assert usage is not None
                assert usage.person_id == owner_state.person_id
                assert usage.visitor_id is None
                owner_id = usage.person_id

            base_bundle = setup.bundle_box["bundle"]
            policy = base_bundle.acquisition_policy
            assert policy is not None
            base_approval = setup.authority.stage_approval(
                base_bundle,
                actor,
                source_sha256=recording.source_sha256,
                stage="C5",
                configuration_sha256=policy.stages[2].configuration_sha256,
            )
            assert base_approval is not None and base_approval.max_cost_paise == 100
            issued = int(setup.clock[0].timestamp())
            supplement = StageCallSupplement(
                id=uuid4(),
                authorization_ref="ref:approval:test-marathi-source-c5",
                base_approval_id=base_approval.id,
                tenant_id=actor.tenant_id,
                processing_person_id=actor.person_id,
                owner_person_id=owner_id,
                source_sha256=recording.source_sha256,
                configuration_sha256=base_approval.configuration_sha256,
                stage="C5",
                recipe_revision=base_approval.recipe_revision,
                coaching_prompt_revision="coaching-v4",
                report_language="mr-Deva+en",
                processing_plan_sha256=logical_plan_sha256,
                prepared_input_sha256=prepared.prepared.input_sha256,
                issued_at_epoch=issued,
                expires_at_epoch=min(base_approval.expires_at_epoch, policy.expires_at_epoch),
                max_additional_requests=2,
                max_cost_per_request_paise=100,
                max_aggregate_cost_paise=200,
            )
            granted_bundle = base_bundle.model_copy(
                update={"stage_call_supplements": (supplement,)}
            )
            setup.bundle_box["bundle"] = granted_bundle
            assert setup.authority.current(setup.clock[0]).digest == granted_bundle.digest

            async with setup.sessions() as database, database.begin():
                app = ConversationApplication(database, clock=lambda: setup.clock[0])
                plans = ConversationProcessingPlans(app, setup.authority, setup.runtime.storage)
                quote = await plans.quote(
                    actor,
                    recording_id,
                    key="supplement-final-plan",
                    report_language="mr-Deva+en",
                )
                fresh_row = await database.get(ConversationProcessingPlan, UUID(quote["id"]))
                assert fresh_row is not None and fresh_row.manifest is not None
                fresh_manifest = PlanManifest.model_validate_json(canonical(fresh_row.manifest))
                assert processing_plan_sha256(fresh_manifest.as_dict()) == logical_plan_sha256
                fresh_request = _c5_request(fresh_manifest, c2_id, c4_ids)
                fresh_prepared = await ReportingPipeline(
                    ConversationInference(app, authority=setup.authority)
                ).plan(await app._recording(actor, recording_id), fresh_request)
                assert fresh_prepared.prepared.input_sha256 == supplement.prepared_input_sha256
                accepted = await plans.accept(
                    actor,
                    recording_id,
                    PlanAcceptance(
                        plan_id=UUID(quote["id"]),
                        plan_fingerprint=quote["plan_fingerprint"],
                        privacy_revision=quote["privacy_revision"],
                        accepted=True,
                    ),
                    key="supplement-final-plan-accept",
                )
                assert accepted["state"] == "active"
            plan_id = UUID(quote["id"])

            # A different prepared C5 input under the active plan cannot use the
            # supplement, even though it names the same source and owner.
            wrong_request = fresh_request.model_copy(update={"report_language": "en"})
            if named_tester_scope:
                async with setup.sessions() as database, database.begin():
                    base_quote = await setup.authority.issue(
                        ConversationApplication(database, clock=lambda: setup.clock[0]),
                        actor,
                        recording_id,
                        key="named-tester-base-c5-other-language",
                        request=wrong_request,
                    )
                    assert base_quote["max_cost_paise"] == 100
            else:
                async with setup.sessions() as database, database.begin():
                    with pytest.raises(ConversationDenied):
                        await setup.authority.issue(
                            ConversationApplication(database, clock=lambda: setup.clock[0]),
                            actor,
                            recording_id,
                            key="supplement-changed-language-denied",
                            request=wrong_request,
                        )

            async with setup.sessions() as database, database.begin():
                app = ConversationApplication(database, clock=lambda: setup.clock[0])
                service = ConversationInference(app, authority=setup.authority)
                concurrent_quote = await setup.authority.issue(
                    app,
                    actor,
                    recording_id,
                    key="supplement-concurrent-primary-quote",
                    request=fresh_request,
                )
                quote_id = UUID(concurrent_quote["id"])
                await service.accept(
                    actor,
                    recording_id,
                    quote_id,
                    QuoteAcceptance(
                        quote_fingerprint=concurrent_quote["quote_fingerprint"],
                        privacy_revision=concurrent_quote["privacy_revision"],
                        accepted=True,
                    ),
                    request=fresh_request,
                )
                concurrent_plan = await ReportingPipeline(service).plan(
                    await app._recording(actor, recording_id), fresh_request
                )
                database.add(
                    ConversationPlanStageAuthorization(
                        quote_id=quote_id,
                        plan_id=plan_id,
                        tenant_id=actor.tenant_id,
                        person_id=actor.person_id,
                        quote_fingerprint=concurrent_quote["quote_fingerprint"],
                        cache_key=concurrent_plan.checkpoint.cache_key,
                        created_at=setup.clock[0],
                    )
                )

            async def start_concurrent_primary(key: str) -> dict[str, Any]:
                async with setup.sessions() as database, database.begin():
                    service = ConversationInference(
                        ConversationApplication(database, clock=lambda: setup.clock[0]),
                        authority=setup.authority,
                    )
                    return await service.request_stage(
                        actor,
                        recording_id,
                        quote_id,
                        key=key,
                        request=fresh_request,
                    )

            concurrent_results = await asyncio.gather(
                start_concurrent_primary("supplement-concurrent-primary-a"),
                start_concurrent_primary("supplement-concurrent-primary-b"),
                return_exceptions=True,
            )
            assert len(concurrent_results) == 2
            admitted = [result for result in concurrent_results if isinstance(result, dict)]
            conflicts = [result for result in concurrent_results if isinstance(result, Exception)]
            assert 1 <= len(admitted) <= 2
            if len(admitted) == 2:
                assert admitted[0]["id"] == admitted[1]["id"]
            else:
                assert len(conflicts) == 1
                assert isinstance(conflicts[0], ConversationConflict | ConversationDenied)

            async with setup.sessions() as database:
                duplicate_primary_tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask).where(
                                ConversationInferenceTask.recording_id == recording_id,
                                ConversationInferenceTask.cache_key
                                == concurrent_plan.checkpoint.cache_key,
                            )
                        )
                    ).all()
                )
                assert len(duplicate_primary_tasks) == 1
                budget = await database.get(
                    ConversationBudgetAccount, granted_bundle.budget_scope_id
                )
                assert budget is not None
                reservations = BudgetAccount.from_dict(budget.snapshot).reservations
                c5_reservations = tuple(
                    item
                    for item in reservations
                    if item.permission.authorization_ref.startswith(
                        f"hosted-stage-v1:{base_approval.id}:"
                    )
                )
                assert len(c5_reservations) == 3
                assert supplemental_reservations(
                    c5_reservations, base_max_requests=base_approval.max_requests
                ) == (1, 100)

            scheduler = ProcessingPlanScheduler(
                setup.sessions, setup.authority, setup.runtime.storage
            )
            plan_id = UUID(quote["id"])
            supplemental_exhausted = False
            for _ in range(10):
                await worker.run_once()
                async with setup.sessions() as database:
                    current_tasks = list(
                        (
                            await database.scalars(
                                select(ConversationInferenceTask)
                                .where(
                                    ConversationInferenceTask.recording_id == recording_id,
                                    ConversationInferenceTask.stage == "C5",
                                )
                                .order_by(ConversationInferenceTask.created_at)
                            )
                        ).all()
                    )
                if len(current_tasks) == 4 and sorted(task.state for task in current_tasks) == [
                    "completed",
                    "completed",
                    "uncertain",
                    "uncertain",
                ]:
                    async with setup.sessions() as database, database.begin():
                        with pytest.raises(ConversationDenied):
                            await setup.authority.issue(
                                ConversationApplication(database, clock=lambda: setup.clock[0]),
                                actor,
                                recording_id,
                                key="supplement-third-request-denied",
                                request=fresh_request,
                            )
                    supplemental_exhausted = True
                    break
                await _make_due(setup, plan_id)
                await scheduler.step()
                async with setup.sessions() as database:
                    current = await database.get(ConversationProcessingPlan, plan_id)
                    assert current is not None
                    if current.state == "completed":
                        break
            assert supplemental_exhausted, [(task.stage, task.state) for task in current_tasks]
            await _make_due(setup, plan_id)
            await scheduler.step()
            async with setup.sessions() as database:
                current = await database.get(ConversationProcessingPlan, plan_id)
                assert current is not None
            assert current.state == "completed"
            assert broker.c5_requests == 4

            async with setup.sessions() as database:
                tasks = list(
                    (
                        await database.scalars(
                            select(ConversationInferenceTask)
                            .where(ConversationInferenceTask.recording_id == recording_id)
                            .order_by(ConversationInferenceTask.created_at)
                        )
                    ).all()
                )
                assert [task.stage for task in tasks].count("C2") == 1
                assert [task.stage for task in tasks].count("C4") == 1
                c5_tasks = [task for task in tasks if task.stage == "C5"]
                assert len(c5_tasks) == 4
                by_id = {str(task.run_id): task.state for task in c5_tasks}
                assert by_id[old_c5_run["id"]] == "uncertain"
                assert by_id[repair_run["id"]] == "completed"
                assert sorted(task.state for task in c5_tasks) == [
                    "completed",
                    "completed",
                    "uncertain",
                    "uncertain",
                ]
                budget = await database.get(
                    ConversationBudgetAccount, granted_bundle.budget_scope_id
                )
                assert budget is not None
                reservations = BudgetAccount.from_dict(budget.snapshot).reservations
                c5_reservations = tuple(
                    item
                    for item in reservations
                    if item.permission.authorization_ref.startswith(
                        f"hosted-stage-v1:{base_approval.id}:"
                    )
                )
                assert len(c5_reservations) == 4
                assert supplemental_reservations(
                    c5_reservations, base_max_requests=base_approval.max_requests
                ) == (2, 200)
                assert sum(item.quote.max_cost_paise for item in c5_reservations) == 400
                assert broker.routes.count("elevenlabs") == 1
                # The retained one-chunk facts checkpoint and C2 task are reused;
                # only the two new C5 calls dispatch for the Marathi plan.
                assert broker.routes.count("gemini") == 5

            if named_tester_scope:
                old_c5_history = {
                    task.run_id: (task.state, task.checkpoint_id, task.input_sha256)
                    for task in c5_tasks
                }
                old_c5_states = {state for state, _, _ in old_c5_history.values()}
                assert {"uncertain", "completed"} <= old_c5_states
                assert len(old_c5_history) >= base_approval.max_requests
                c5_dispatches_after_first_recording = broker.c5_requests

                second_submission = uuid4()
                second_path = f"{PREFIX}/submissions/{second_submission}"
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
                ) as client:
                    client.cookies.set(setup.settings.session_cookie_name, owner_token)
                    second_upload = await client.put(
                        second_path + "/source",
                        content=data,
                        headers=await _headers(client, data),
                    )
                assert second_upload.status_code == 202, second_upload.text
                second_recording_id = UUID(second_upload.json()["recording_id"])
                await _reconcile(setup.sessions, setup.state)
                assert await local.run_once()
                async with setup.sessions() as database, database.begin():
                    app = ConversationApplication(database, clock=lambda: setup.clock[0])
                    second_actor = await GuestOwnership(
                        setup.factory(database)
                    ).resolve_processing_actor(second_submission, actor=owner_state.actor)
                    assert isinstance(second_actor, ProcessingActor)
                    await setup.authority.claim_allowance(app, second_actor)

                second_c2_run = await _direct_stage(
                    setup, second_actor, second_recording_id, None, key="named-c5-second-c2"
                )
                assert await worker.run_once()
                async with setup.sessions() as database:
                    second_c2_task = await database.get(
                        ConversationInferenceTask, UUID(second_c2_run["id"])
                    )
                    assert second_c2_task is not None and second_c2_task.checkpoint_id is not None
                    second_c2_id = second_c2_task.checkpoint_id

                second_c4_request = c4_request.model_copy(
                    update={"transcript_checkpoint_id": second_c2_id}
                )
                second_c4_run = await _direct_stage(
                    setup,
                    second_actor,
                    second_recording_id,
                    second_c4_request,
                    key="named-c5-second-c4",
                )
                assert await worker.run_once()
                async with setup.sessions() as database:
                    second_c4_task = await database.get(
                        ConversationInferenceTask, UUID(second_c4_run["id"])
                    )
                    assert second_c4_task is not None and second_c4_task.checkpoint_id is not None
                    second_c4_id = second_c4_task.checkpoint_id

                second_c5_request = old_c5_request.model_copy(
                    update={
                        "transcript_checkpoint_id": second_c2_id,
                        "fact_checkpoint_ids": (second_c4_id,),
                    }
                )
                second_c5_run = await _direct_stage(
                    setup,
                    second_actor,
                    second_recording_id,
                    second_c5_request,
                    key="named-c5-second-recording",
                )
                assert second_c5_run["state"] == "queued"
                assert broker.c5_requests == c5_dispatches_after_first_recording

                async with setup.sessions() as database:
                    new_task = await database.get(
                        ConversationInferenceTask, UUID(second_c5_run["id"])
                    )
                    assert new_task is not None
                    assert new_task.recording_id == second_recording_id
                    assert new_task.state == "queued"
                    retained_history = list(
                        (
                            await database.scalars(
                                select(ConversationInferenceTask).where(
                                    ConversationInferenceTask.recording_id == recording_id,
                                    ConversationInferenceTask.stage == "C5",
                                )
                            )
                        ).all()
                    )
                    assert {
                        task.run_id: (task.state, task.checkpoint_id, task.input_sha256)
                        for task in retained_history
                    } == old_c5_history
        finally:
            await setup.engine.dispose()

    run(exercise())
