"""Synthetic PostgreSQL proof for the composed hosted conversation runner.

The approval artifact, launch references and private roots are disposable test
values.  ProcessInferenceBroker is replaced with the existing local
ReportingBroker, so this test exercises composition and durable scheduling
without provider network, credentials or paid execution.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.conversation_intelligence import reporting_runtime
from ac_platform.conversation_intelligence.inference_broker import InfisicalLauncher
from ac_platform.conversation_intelligence.models import (
    ConversationCheckpoint,
    ConversationCommand,
    ConversationInferenceTask,
    ConversationPlanStageAuthorization,
    ConversationProcessingPlan,
    ConversationReportDraft,
)
from ac_platform.conversation_intelligence.processing_plan import (
    PLAN_PRIVACY_REVISION,
    ConversationProcessingPlans,
    PlanAcceptance,
)
from ac_platform.conversation_intelligence.runner import ConversationWorkerRunner
from tests.database.test_conversation_authority_postgresql import _application, _setup
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_worker_postgresql import _postgres_harness


@pytest.fixture
def postgres_harness() -> Any:
    """Use only the disposable loopback PostgreSQL harness."""

    yield from _postgres_harness.__wrapped__()


async def _quote(setup: Any, authority: Any) -> dict[str, Any]:
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), authority)
        return await service.quote(
            setup.actor,
            setup.prepared.recording_id,
            key="runtime-composed-plan-quote",
        )


async def _accept(setup: Any, authority: Any, quote: dict[str, Any]) -> dict[str, Any]:
    payload = PlanAcceptance(
        plan_id=UUID(quote["id"]),
        plan_fingerprint=quote["plan_fingerprint"],
        privacy_revision=PLAN_PRIVACY_REVISION,
        accepted=True,
    )
    async with setup.sessions() as database, database.begin():
        service = ConversationProcessingPlans(_application(setup, database), authority)
        return await service.accept(
            setup.actor,
            setup.prepared.recording_id,
            payload,
            key="runtime-composed-plan-accept",
        )


async def _wait_for_plan(setup: Any, plan_id: UUID, stop: asyncio.Event) -> None:
    for _ in range(750):
        async with setup.sessions() as database:
            row = await database.get(ConversationProcessingPlan, plan_id)
            assert row is not None
            if row.state == "completed":
                return
            if row.state == "held":
                raise AssertionError(f"synthetic composed plan held: {row.progress}")
        await asyncio.sleep(0.02)
    stop.set()
    raise AssertionError("synthetic composed plan did not reach C6")


def test_composed_runner_advances_accepted_plan_once_to_private_c6(
    postgres_harness: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose hosted boundaries, then let one serial runner drive all stages."""

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            approval_path = tmp_path / "runtime-hosted-approval.json"
            approval_raw = setup.bundle.to_json()
            approval_path.write_bytes(approval_raw)
            settings = Settings(
                _env_file=None,
                environment="test",
                sales_xray_enabled=True,
                sales_xray_approval_path=str(approval_path),
                sales_xray_approval_sha256=hashlib.sha256(approval_raw).hexdigest(),
                sales_xray_storage_root=str(setup.prepared.storage.root),
                sales_xray_scratch_root=str(setup.prepared.scratch.root),
            )
            launchers = {
                stage.credential_ref: InfisicalLauncher(
                    executable="infisical",
                    provider_id=stage.provider_id,
                    project_ref="ref:synthetic/project",
                    environment_ref="ref:synthetic/test",
                    secret_path_ref=f"ref:synthetic/secrets/{stage.provider_id}",
                )
                for stage in setup.bundle.stages
            }
            assert set(launchers) == {stage.credential_ref for stage in setup.bundle.stages}

            def synthetic_broker(**kwargs: Any) -> Any:
                launcher = kwargs["infisical"]
                assert isinstance(launcher, InfisicalLauncher)
                assert launcher.provider_id in {"elevenlabs", "groq"}
                return setup.broker

            monkeypatch.setattr(
                reporting_runtime,
                "ProcessInferenceBroker",
                synthetic_broker,
            )
            runtime = reporting_runtime.compose_hosted_reporting(
                settings,
                setup.sessions,
                launchers=launchers,
            )
            assert runtime is not None
            assert runtime.storage.root == setup.prepared.storage.root
            assert runtime.authority.current(setup.prepared.state.now).digest == setup.bundle.digest

            quoted = await _quote(setup, runtime.authority)
            assert quoted["accepted"] is False
            assert quoted["state"] == "quoted"
            accepted = await _accept(setup, runtime.authority, quoted)
            assert accepted["accepted"] is True
            assert accepted["state"] == "active"
            plan_id = UUID(quoted["id"])

            runner = ConversationWorkerRunner(
                runtime.retention,
                setup.prepared.worker,
                runtime.plans,
                runtime.inference,
                idle_min=timedelta(milliseconds=10),
                idle_max=timedelta(milliseconds=20),
                recovery_backoff=timedelta(milliseconds=10),
            )
            stop = asyncio.Event()
            runner_task = asyncio.create_task(runner.run(stop))
            try:
                await _wait_for_plan(setup, plan_id, stop)
            finally:
                stop.set()
                summary = await asyncio.wait_for(runner_task, timeout=5)

            assert summary.cycles > 0
            assert summary.inference_work >= 3
            assert setup.broker.routes == ["elevenlabs", "groq", "groq"]

            async with setup.sessions() as database:
                plan = await database.get(ConversationProcessingPlan, plan_id)
                assert plan is not None and plan.state == "completed"
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
                assert all(task.state == "completed" for task in tasks)
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationPlanStageAuthorization)
                        .where(ConversationPlanStageAuthorization.plan_id == plan_id)
                    )
                    == 3
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationCommand)
                        .where(ConversationCommand.action == "processing_plan_accepted")
                    )
                    == 1
                )
                checkpoints = list(
                    (
                        await database.scalars(
                            select(ConversationCheckpoint).where(
                                ConversationCheckpoint.recording_id == setup.prepared.recording_id
                            )
                        )
                    ).all()
                )
                assert {checkpoint.stage for checkpoint in checkpoints} >= {
                    "C1",
                    "C2",
                    "C3",
                    "C4",
                    "C5",
                    "C6",
                }
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationReportDraft)
                        .where(
                            ConversationReportDraft.recording_id == setup.prepared.recording_id,
                            ConversationReportDraft.erased_at.is_(None),
                        )
                    )
                    == 1
                )

            # A fresh runner restart observes completed cache keys and has no
            # accepted work to admit, so it cannot regenerate provider effects.
            restart = ConversationWorkerRunner(
                runtime.retention,
                setup.prepared.worker,
                runtime.plans,
                runtime.inference,
                idle_min=timedelta(milliseconds=10),
                idle_max=timedelta(milliseconds=20),
                recovery_backoff=timedelta(milliseconds=10),
            )
            restart_stop = asyncio.Event()
            restart_task = asyncio.create_task(restart.run(restart_stop))
            await asyncio.sleep(0.08)
            restart_stop.set()
            restart_summary = await asyncio.wait_for(restart_task, timeout=5)
            assert restart_summary.cycles > 0
            assert setup.broker.routes == ["elevenlabs", "groq", "groq"]
        finally:
            await setup.engine.dispose()

    run(exercise())
