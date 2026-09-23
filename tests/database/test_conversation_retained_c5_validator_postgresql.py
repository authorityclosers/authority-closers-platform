"""Real PostgreSQL proof of revisioned retained-response admission and replay."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, func, select

from ac_platform.conversation_intelligence import retained_c5_recovery as recovery_module
from ac_platform.conversation_intelligence.application import ConversationApplication
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationInferenceTask,
    ConversationRun,
)
from ac_platform.conversation_intelligence.recovery_models import ConversationRetainedC5Version
from ac_platform.conversation_intelligence.retained_c5_recovery import RetainedC5RecoveryService
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_retained_c5_recovery_postgresql import _seed_retained_case

pytest_plugins = ("tests.database.test_conversation_postgresql",)


def test_validator_upgrade_replays_old_key_and_revalidates_fresh_keys_once(
    postgres_harness: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployed legacy negative result cannot permanently poison valid retained bytes."""

    async def exercise() -> None:
        case = await _seed_retained_case(
            postgres_harness, tmp_path, source_quote="Buyer asks about price and timing."
        )
        prepared = case["prepared"]
        sessions = case["sessions"]
        actor = ActorContext(
            prepared.state.person_id,
            prepared.state.session_id,
            prepared.state.tenant_id,
            frozenset({"admin_surface"}),
        )

        async def revalidate(key: str) -> dict[str, Any]:
            async with sessions() as database, database.begin():
                service = RetainedC5RecoveryService(
                    ConversationApplication(database, clock=lambda: prepared.state.now),
                    operations_tenant_id=prepared.state.tenant_id,
                    recording_tenant_ids=(prepared.state.tenant_id,),
                )
                return await service.revalidate(
                    actor,
                    case["run_id"],
                    original_raw_sha256=case["raw_sha256"],
                    key=key,
                    storage=prepared.storage,
                    historical_input=case["historical_input"],
                )

        def legacy_rejection(*args: Any, **kwargs: Any) -> Any:
            raise ValueError("Synthetic previous validator rejected this supported shape")

        def legacy_insert(
            mapper: Any, connection: Any, target: ConversationRetainedC5Version
        ) -> None:
            # Seed the old release's row before INSERT; immutable history stays
            # enforced throughout the test, with no trigger bypass or UPDATE.
            assert target.run_id == case["run_id"]
            target.fingerprint = content_hash(
                {
                    "run_id": str(case["run_id"]),
                    "original_raw_sha256": case["raw_sha256"],
                    "correction_payload_sha256": None,
                }
            )
            target.proof = {
                key: value
                for key, value in (target.proof or {}).items()
                if key != "validator_revision"
            }

        try:
            with monkeypatch.context() as patch:
                patch.setattr(recovery_module, "validate_coaching_result", legacy_rejection)
                event.listen(ConversationRetainedC5Version, "before_insert", legacy_insert)
                try:
                    original = await revalidate("original-key")
                finally:
                    event.remove(ConversationRetainedC5Version, "before_insert", legacy_insert)
            assert original["recovery"]["validation_state"] == "needs_correction"
            async with sessions() as database:
                legacy = await database.get(ConversationRetainedC5Version, UUID(original["id"]))
                assert legacy is not None and legacy.proof is not None
                old_proof = legacy.proof.copy()

            replay = await revalidate("original-key")
            assert replay["id"] == original["id"]
            assert replay["recovery"]["validation_state"] == "needs_correction"
            first, concurrent = await asyncio.gather(
                revalidate("upgraded-key-one"), revalidate("upgraded-key-two")
            )
            assert first["id"] == concurrent["id"] != original["id"]
            assert first["recovery"]["validation_state"] == "revalidated"
            assert first["recovery"]["provider_calls"] == 0
            assert first["report"] is not None
            assert (await revalidate("upgraded-key-one"))["id"] == first["id"]
            async with sessions() as database:
                versions = (
                    await database.scalars(
                        select(ConversationRetainedC5Version)
                        .where(ConversationRetainedC5Version.run_id == case["run_id"])
                        .order_by(ConversationRetainedC5Version.version)
                    )
                ).all()
                assert [version.version for version in versions] == [1, 2]
                assert versions[0].proof == old_proof
                assert versions[0].payload is None
                assert (
                    versions[1].proof["validator_revision"]
                    == recovery_module.REPORT_VALIDATOR_REVISION
                )
                assert versions[0].original_raw_sha256 == versions[1].original_raw_sha256
                assert versions[0].original_receipt == versions[1].original_receipt
                commands = await database.scalar(
                    select(func.count())
                    .select_from(ConversationCommand)
                    .where(ConversationCommand.result_id.in_([version.id for version in versions]))
                )
                assert commands == 3
                task = await database.get(ConversationInferenceTask, case["run_id"])
                job = await database.get(Job, task.job_id)
                original_run = await database.get(ConversationRun, case["run_id"])
                assert task.state == original_run.state == "failed"
                assert job.status == "dead_letter" and job.attempt_count == 1
                assert job.provider_receipt == versions[0].original_receipt
                assert task.checkpoint_id is None
        finally:
            await case["engine"].dispose()

    run(exercise())
