"""Account HTTP, durable workers, and idempotence proof for fictional samples."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

import ac_platform.development.sales_xray_samples as sample_module
from ac_platform.conversation_intelligence.entitlements import BudgetAccount, MinuteAccount
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.inference_worker import ConversationInferenceWorker
from ac_platform.conversation_intelligence.models import (
    ConversationBudgetAccount,
    ConversationInferenceTask,
    ConversationMinuteAccount,
    ConversationProcessingPlan,
    ConversationQuote,
)
from ac_platform.conversation_intelligence.processing_plan import ProcessingPlanScheduler
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.development.sales_xray_samples import (
    SampleRefused,
    build_fake_router,
    seed_account_samples,
)
from ac_platform.identity.application import ResolvedActorContext
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_processing_plan_postgresql import _make_due
from tests.database.test_conversation_submission_http_postgresql import (
    ORIGIN,
    _setup,
    _sign_in,
)
from tests.database.test_conversation_worker_postgresql import _postgres_harness, _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def _allow_fixture_duration(setup: Any) -> None:
    bundle = setup.bundle_box["bundle"]
    policy = bundle.acquisition_policy
    assert policy is not None
    stages = tuple(
        stage.model_copy(update={"max_source_duration_ms": 240_000}) for stage in policy.stages
    )
    setup.bundle_box["bundle"] = bundle.model_copy(
        update={"acquisition_policy": policy.model_copy(update={"stages": stages})}
    )


def _install_routes_with_stub_native(
    setup: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_path = tmp_path / "sample-native.sock"
    native_socket = socket.socket(socket.AF_UNIX)
    native_socket.bind(str(socket_path))
    native_socket.close()
    socket_path.chmod(0o600)

    class StubNativeRuntime:
        def __init__(self, path: Path, *, workspace_root: Path, expected_image_ref: str) -> None:
            self.path = path
            self.workspace_root = workspace_root
            self.expected_image_ref = expected_image_ref

        def inspect(self, source: Path, outdir: Path, *, job_id: UUID, rate: Any) -> dict[str, Any]:
            return setup.native.inspect(source, outdir, job_id=job_id, rate=rate)

    monkeypatch.setattr(sample_module, "compose_hosted_intake", lambda _settings: setup.runtime)
    monkeypatch.setattr(sample_module, "SocketNativeRuntime", StubNativeRuntime)
    settings = setup.settings.model_copy(
        update={
            "sales_xray_native_socket_path": str(socket_path),
            "sales_xray_native_image_ref": "sha256:" + "a" * 64,
            "sales_xray_acquisition_policy_revision": "guest-processing-v1",
        }
    )
    actor = ResolvedActorContext(
        ActorContext(setup.state.person_id, setup.state.session_id, setup.state.tenant_id),
        "learner",
        1,
        1,
        1,
        1,
    )
    app, intake, native = sample_module._install_sample_routes(
        settings,
        setup.sessions,
        actor,
    )
    assert intake is setup.runtime
    assert isinstance(native, StubNativeRuntime)
    assert native.path == socket_path
    assert native.workspace_root == setup.runtime.scratch.root
    # Run the HTTP assertions below against the app returned by the production
    # route installer. FastAPI's included-router representation is versioned,
    # so inspect the mounted route through HTTP instead of app.routes internals.
    setup.app = app


def test_dev_samples_reach_real_routes_and_second_run_adds_nothing(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        setup = await _setup(
            postgres_harness,
            tmp_path,
            gemini=True,
            funded=True,
            text_cost_paise=1_000,
            asr_cost_paise=50_000,
        )
        try:
            _allow_fixture_duration(setup)
            _install_routes_with_stub_native(setup, tmp_path, monkeypatch)
            bundle = setup.bundle_box["bundle"]
            router = build_fake_router(bundle, setup.authority)
            local = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            inference = ConversationInferenceWorker(
                setup.sessions, setup.runtime.storage, router, authority=setup.authority
            )

            class DueScheduler(ProcessingPlanScheduler):
                async def step(self) -> bool:
                    async with setup.sessions() as db:
                        plan_id = await db.scalar(
                            select(ConversationProcessingPlan.id)
                            .where(ConversationProcessingPlan.state == "active")
                            .order_by(ConversationProcessingPlan.next_check_at)
                            .limit(1)
                        )
                    if plan_id is not None:
                        await _make_due(setup, plan_id)
                    return await super().step()

            scheduler = DueScheduler(setup.sessions, setup.authority, setup.runtime.storage)
            scheduler_steps: list[bool] = []
            scheduler_step = scheduler.step

            async def record_scheduler_step() -> bool:
                result = await scheduler_step()
                scheduler_steps.append(result)
                return result

            monkeypatch.setattr(scheduler, "step", record_scheduler_step)

            async def publish_pending() -> None:
                await _reconcile(setup.sessions, setup.state)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=setup.app), base_url=ORIGIN
            ) as client:
                _sign_in(setup, client)
                try:
                    first = await seed_account_samples(
                        client,
                        setup.sessions,
                        person_id=setup.state.person_id,
                        count=2,
                        budget_cap_paise=bundle.budget_cap_paise,
                        settings=setup.settings,
                        local_worker=local,
                        inference_worker=inference,
                        scheduler=scheduler,
                        publish_pending=publish_pending,
                        wait_seconds=180,
                    )
                except SampleRefused as error:
                    async with setup.sessions() as db:
                        plans = (
                            await db.execute(
                                select(
                                    ConversationProcessingPlan.state,
                                    ConversationProcessingPlan.progress,
                                )
                            )
                        ).all()
                        tasks = (
                            await db.execute(
                                select(
                                    ConversationInferenceTask.stage,
                                    ConversationInferenceTask.state,
                                    Job.last_error,
                                )
                                .join(Job, Job.id == ConversationInferenceTask.job_id)
                            )
                        ).all()
                    safe_progress = [
                        (
                            state,
                            progress.get("failure_code"),
                            progress.get("diagnostic_code"),
                        )
                        for state, progress in plans
                    ]
                    raise AssertionError(
                        "Fictional route pipeline did not finish; "
                        f"plans={safe_progress}, tasks={tasks}, "
                        f"scheduler_steps={len(scheduler_steps)}, "
                        f"advances={sum(scheduler_steps)}"
                    ) from error
                listed = (await client.get("/v1/conversation/acquisition/submissions")).json()[
                    "submissions"
                ]
                samples = [
                    row
                    for row in listed
                    if row["display_name"]
                    in {
                        "Sample call 1 · fictional",
                        "Sample call 2 · fictional",
                    }
                ]
                assert len(samples) == 2
                assert {row["state"] for row in samples} == {"report_ready"}
                for row in samples:
                    submission = row["submission_id"]
                    detail = await client.get(
                        f"/v1/conversation/acquisition/submissions/{submission}"
                    )
                    assert detail.status_code == 200
                    transcript_response = await client.get(
                        f"/v1/conversation/acquisition/submissions/{submission}/transcript"
                    )
                    assert transcript_response.status_code == 200
                    transcript = transcript_response.json()
                    assert len(transcript["segments"]) == 28
                    assert 210_000 <= transcript["duration_ms"] <= 240_000

                    report_response = await client.get(
                        f"/v1/conversation/acquisition/submissions/{submission}/report"
                    )
                    assert report_response.status_code == 200
                    content = report_response.json()["report"]["content"]
                    for section in (
                        "strengths",
                        "missed_opportunities",
                        "improvements",
                        "objection_analysis",
                        "closing_analysis",
                    ):
                        assert len(content[section]) >= 2
                    overview = content["overview"]
                    for section in (
                        "strength_details",
                        "improvement_details",
                        "golden_moments",
                        "missed_details",
                        "prospect_interpretations",
                        "rewatch",
                        "ethics_notes",
                    ):
                        assert len(overview[section]) >= 2

                async with setup.sessions() as db:
                    submission_ids = {UUID(str(row["submission_id"])) for row in samples}
                    recording_ids = set(
                        (
                            await db.scalars(
                                select(ConversationGuestSubmission.recording_id).where(
                                    ConversationGuestSubmission.submission_id.in_(submission_ids)
                                )
                            )
                        ).all()
                    )
                    tasks = (
                        await db.scalars(
                            select(ConversationInferenceTask).where(
                                ConversationInferenceTask.recording_id.in_(recording_ids)
                            )
                        )
                    ).all()
                    assert tasks
                    saw_paid_quote = False
                    for task in tasks:
                        quote = await db.get(ConversationQuote, task.quote_id)
                        assert quote is not None
                        saw_paid_quote = saw_paid_quote or quote.quote["max_cost_paise"] > 0
                        minute_row = await db.get(
                            ConversationMinuteAccount, (task.tenant_id, task.person_id)
                        )
                        budget_row = await db.get(ConversationBudgetAccount, quote.budget_scope_id)
                        assert minute_row is not None and budget_row is not None
                        minute = MinuteAccount.from_dict(minute_row.snapshot)
                        budget = BudgetAccount.from_dict(budget_row.snapshot)
                        reservation = next(
                            item
                            for item in minute.reservations
                            if item.reservation_id == str(task.run_id)
                        )
                        budget_reservation = next(
                            item
                            for item in budget.reservations
                            if item.reservation_id == str(task.run_id)
                        )
                        assert reservation == budget_reservation
                        assert reservation.state == "settled"
                        assert reservation.settlement is not None
                        assert reservation.settlement.actual_paise == 0
                    assert saw_paid_quote

                second = await seed_account_samples(
                    client,
                    setup.sessions,
                    person_id=setup.state.person_id,
                    count=2,
                    budget_cap_paise=bundle.budget_cap_paise,
                    settings=setup.settings,
                    local_worker=local,
                    inference_worker=inference,
                    scheduler=scheduler,
                    publish_pending=publish_pending,
                    wait_seconds=10,
                )
                after = (await client.get("/v1/conversation/acquisition/submissions")).json()[
                    "submissions"
                ]
                assert first == second
                assert (
                    len(
                        [
                            row
                            for row in after
                            if row["display_name"]
                            in {
                                "Sample call 1 · fictional",
                                "Sample call 2 · fictional",
                            }
                        ]
                    )
                    == 2
                )
        finally:
            await setup.engine.dispose()

    run(exercise())
