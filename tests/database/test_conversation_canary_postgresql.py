"""Canary provenance, retention and capacity proofs using fictional sources."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.exc import DBAPIError

from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationConflict,
)
from ac_platform.conversation_intelligence.canary import mark_canary_submission
from ac_platform.conversation_intelligence.canary_models import (
    ConversationCanarySubmission as Canary,
)
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.db.models import model_metadata
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
)
from tests.database.test_conversation_guest_ownership_postgresql import _processing_actor
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture
def postgres_harness() -> Any:
    yield from _postgres_harness.__wrapped__()


def test_model_builds_on_sqlite() -> None:
    engine = create_engine("sqlite://")
    model_metadata().create_all(engine)
    engine.dispose()


async def _canary(setup: Any) -> dict[str, Any]:
    source = await _seed_retained_guest_submission(setup)
    async with setup.sessions() as db, db.begin():
        recording = await db.get(ConversationRecording, source["recording_id"])
        await mark_canary_submission(
            db,
            tenant_id=setup.state.tenant_id,
            submission_id=source["submission_id"],
            environment="test",
            fixture_sha256=recording.source_sha256,
            created_at=setup.state.now,
        )
    return source


def test_retention_skips_earlier_canary_and_marker_is_append_only(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            canary = await _canary(setup)
            async with setup.sessions() as db, db.begin():
                for statement in (delete(Canary), update(Canary).values(environment="local")):
                    with pytest.raises(DBAPIError, match="append-only"):
                        async with db.begin_nested():
                            await db.execute(statement)
                setup.guest = await setup.factory(db).issue()
            ordinary = await _seed_retained_guest_submission(setup)
            async with setup.sessions() as db, db.begin():
                for index, source in enumerate((canary, ordinary)):
                    recording = await db.get(ConversationRecording, source["recording_id"])
                    permission = await db.get(ConversationPermission, recording.permission_id)
                    permission.retention_until = setup.state.now + timedelta(hours=index + 1)
            await _reconcile(setup.sessions, setup.state)
            scheduler = ConversationRetentionScheduler(
                setup.sessions, clock=lambda: setup.state.now + timedelta(hours=3)
            )
            assert await scheduler.step()
            assert not await scheduler.step()
            worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await worker.run_once()
            async with setup.sessions() as db:
                assert (
                    await db.get(ConversationRecording, canary["recording_id"])
                ).state != "deleted"
                assert (
                    await db.get(ConversationRecording, ordinary["recording_id"])
                ).state == "deleted"
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("cap", ["max_recordings", "max_stored_source_bytes", "global"])
def test_canary_excluded_from_owner_caps_but_included_globally(
    postgres_harness: Any, tmp_path: Path, cap: str
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path, gemini=True)
        try:
            canary = await _canary(setup)
            actor = await _processing_actor(
                setup.engine, setup.state, canary["submission_id"], setup.guest.token
            )
            async with setup.sessions() as db, db.begin():
                recording = await db.get(ConversationRecording, canary["recording_id"])
                size = recording.source_bytes
                intent = IntakeIntent(
                    source_sha256="b" * 64,
                    source_bytes=size,
                    content_type="audio/wav",
                    duration_ms=1000,
                    purpose="internal_analysis",
                )
                bundle = setup.bundle_box["bundle"]
                policy = bundle.acquisition_policy.model_copy(
                    update={
                        "max_recordings": 1 if cap == "max_recordings" else 64,
                        "max_source_bytes": size,
                        "max_stored_source_bytes": size * 2 if cap == "max_recordings" else size,
                    }
                )
                setup.bundle_box["bundle"] = bundle.model_copy(
                    update={
                        "acquisition_policy": policy,
                        "max_stored_source_bytes": size * 2 - 1 if cap == "global" else size * 4,
                    }
                )
                app = ConversationApplication(db, clock=lambda: setup.state.now)
                if cap == "global":
                    with pytest.raises(ConversationConflict, match="capacity is full"):
                        await setup.authority.admit_upload(app, actor, intent)
                else:
                    await setup.authority.admit_upload(app, actor, intent)
        finally:
            await setup.engine.dispose()

    run(exercise())
