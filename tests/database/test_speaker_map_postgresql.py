"""Disposable PostgreSQL proof for speaker history, tenancy and canonical erasure."""

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import ConversationPermission
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.speaker_map_models import ConversationSpeakerMapRevision
from ac_platform.conversation_intelligence.speaker_map_store import (
    read_speaker_map_revision,
    update_speaker_map,
)
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.db.models import model_metadata
from ac_platform.identity.sales_xray_profile import erase_sales_xray_profile
from tests.database.test_conversation_account_library_postgresql import (
    _seed_retained_guest_submission,
)
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_submission_labels_postgresql import (
    _retained_claimed_submission,
)
from tests.database.test_conversation_worker_postgresql import _reconcile


@pytest.fixture(scope="module")
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


async def _choices(setup: Any, source: dict[str, Any], count: int = 1) -> None:
    async with setup.sessions() as database, database.begin():
        for revision in range(1, count + 1):
            database.add(
                ConversationSpeakerMapRevision(
                    id=uuid4(),
                    tenant_id=setup.state.tenant_id,
                    submission_id=source["submission_id"],
                    revision=revision,
                    transcript_revision="fictional-c2-revision",
                    speakers=[{"speaker_id": "speaker_0", "role": "you", "display_name": "Zoya"}],
                    actor_person_id=setup.state.person_id,
                    created_at=setup.state.now,
                )
            )


def test_postgres_schema_bounds_tenant_fks_and_no_history_update(
    postgres_harness: Any, tmp_path: Path
) -> None:
    with postgres_harness.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []
        column = next(
            c
            for c in inspect(connection).get_columns("conversation_processing_plans")
            if c["name"] == "speaker_roles"
        )
        assert column["nullable"] and column["default"] is None

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        try:
            source = await _retained_claimed_submission(setup)
            await _choices(setup, source)
            other = await seed(setup.engine)
            table = ConversationSpeakerMapRevision.__table__
            values = dict(
                id=uuid4(),
                tenant_id=setup.state.tenant_id,
                submission_id=source["submission_id"],
                revision=2,
                transcript_revision="fictional-c2-revision",
                speakers=[],
                actor_person_id=setup.state.person_id,
                created_at=setup.state.now,
            )
            for invalid in (
                {"revision": 0},
                {"revision": 51},
                {"revision": 1},
                {"transcript_revision": ""},
                {"transcript_revision": "r" * 257},
                {"tenant_id": other.tenant_id, "actor_person_id": other.person_id},
                {"actor_person_id": other.person_id},
            ):
                with pytest.raises(DBAPIError), postgres_harness.begin() as connection:
                    connection.execute(table.insert().values({**values, **invalid}))
            with pytest.raises(DBAPIError, match="append-only"), postgres_harness.begin() as conn:
                conn.execute(
                    update(table)
                    .where(table.c.submission_id == source["submission_id"])
                    .values(speakers=[])
                )
            async with setup.sessions() as database:
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(table)
                        .where(table.c.submission_id == source["submission_id"])
                    )
                    == 1
                )
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("conflicting", [False, True])
def test_postgres_speaker_choices_serialize_retry_rollback_and_owner_scope(
    postgres_harness: Any, tmp_path: Path, monkeypatch: Any, conflicting: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        task: asyncio.Task[Any] | None = None
        try:
            source = await _retained_claimed_submission(setup)
            submission_id = source["submission_id"]
            choices = [
                {"speaker_id": "s0", "role": "you", "display_name": "Fictional Zoya"},
                {"speaker_id": "s1", "role": "prospect", "display_name": None},
            ]

            async def current_transcript(_self: Any, recording: Any) -> dict[str, Any]:
                assert recording.id == source["recording_id"]
                assert recording.person_id == source["recording_person_id"]
                return {
                    "revision": "fictional-c2",
                    "segments": [{"speaker_id": "s0"}, {"speaker_id": "s1"}],
                }

            monkeypatch.setattr(AcquisitionReports, "render_transcript", current_transcript)

            async def save(database: Any, speakers: Any, revision: int = 0) -> Any:
                return await update_speaker_map(
                    GuestOwnership(setup.factory(database)),
                    submission_id,
                    actor=setup.state.actor,
                    expected_revision=revision,
                    transcript_revision="fictional-c2",
                    speakers=speakers,
                )

            ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()

            async def retry() -> Any:
                async with setup.sessions() as second, second.begin():
                    ready.set_result(await second.scalar(text("SELECT pg_backend_pid()")))
                    requested = (
                        [{**choices[0], "display_name": "Other choice"}, choices[1]]
                        if conflicting
                        else list(reversed(choices))
                    )
                    return await save(second, requested)

            async with setup.sessions() as first, first.begin():
                assert (
                    await read_speaker_map_revision(
                        GuestOwnership(setup.factory(first)), submission_id, actor=setup.state.actor
                    )
                    is None
                )
                assert (await save(first, choices))["revision"] == 1
                task = asyncio.create_task(retry())
                await wait_blocked(setup.engine, await asyncio.wait_for(ready, timeout=5), task)
            if conflicting:
                with pytest.raises(ConversationConflict):
                    await asyncio.wait_for(task, timeout=5)
            else:
                assert (await asyncio.wait_for(task, timeout=5))["revision"] == 1

            with pytest.raises(RuntimeError, match="rollback proof"):
                async with setup.sessions() as database, database.begin():
                    assert (
                        await save(database, [{**choices[0], "display_name": None}, choices[1]], 1)
                    )["revision"] == 2
                    raise RuntimeError("rollback proof")
            stranger = await seed(setup.engine, tenant_id=setup.state.tenant_id)
            other_tenant = await seed(setup.engine)
            for actor in (stranger.actor, other_tenant.actor):
                async with setup.sessions() as database, database.begin():
                    ownership = GuestOwnership(setup.factory(database))
                    with pytest.raises((ConversationDenied, ConversationNotFound)):
                        await read_speaker_map_revision(ownership, submission_id, actor=actor)
                    with pytest.raises((ConversationDenied, ConversationNotFound)):
                        await update_speaker_map(
                            ownership,
                            submission_id,
                            actor=actor,
                            expected_revision=1,
                            transcript_revision="fictional-c2",
                            speakers=choices,
                        )
            async with setup.sessions() as database, database.begin():
                result = await read_speaker_map_revision(
                    GuestOwnership(setup.factory(database)), submission_id, actor=setup.state.actor
                )
                assert (
                    result is not None and result["revision"] == 1 and result["speakers"] == choices
                )
                assert (
                    await database.scalar(
                        select(func.count())
                        .select_from(ConversationSpeakerMapRevision)
                        .where(ConversationSpeakerMapRevision.submission_id == submission_id)
                    )
                    == 1
                )
                events = (
                    await database.scalars(
                        select(AuditEvent).where(
                            AuditEvent.action == "conversation.speaker_map_changed",
                            AuditEvent.tenant_id == setup.state.tenant_id,
                        )
                    )
                ).all()
                assert len(events) == 1 and events[0].payload == {
                    "old_revision": 0,
                    "new_revision": 1,
                }
                assert "Fictional Zoya" not in str(events[0].payload)
                assert (await verify_audit_chain(database, setup.state.tenant_id)).valid
                assert (
                    await save(database, [{**choices[0], "display_name": None}, choices[1]], 1)
                )["revision"] == 2
            async with setup.sessions() as database, database.begin():
                latest = await read_speaker_map_revision(
                    GuestOwnership(setup.factory(database)), submission_id, actor=setup.state.actor
                )
                assert latest is not None and latest["revision"] == 2
                assert latest["speakers"][0]["display_name"] is None
                history = (
                    await database.scalars(
                        select(ConversationSpeakerMapRevision)
                        .where(ConversationSpeakerMapRevision.submission_id == submission_id)
                        .order_by(ConversationSpeakerMapRevision.revision)
                    )
                ).all()
                assert [row.revision for row in history] == [1, 2]
                assert history[0].speakers == choices
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("erasure", ["recording", "person"])
def test_postgres_canonical_erasure_preserves_other_calls_tenants_and_audit(
    postgres_harness: Any, tmp_path: Path, erasure: str
) -> None:
    async def exercise() -> None:
        (tmp_path / "owner").mkdir()
        (tmp_path / "other-tenant").mkdir()
        setup = await _setup(postgres_harness, tmp_path / "owner")
        other = await _setup(postgres_harness, tmp_path / "other-tenant")
        try:
            source = await _seed_retained_guest_submission(setup)
            sibling = await _seed_retained_guest_submission(setup)
            async with setup.sessions() as database, database.begin():
                await setup.factory(database).claim(setup.guest.token, setup.state.actor)
            unrelated = await _retained_claimed_submission(other)
            for actor, call in ((setup, source), (setup, sibling), (other, unrelated)):
                await _choices(actor, call, count=2)
            async with setup.sessions() as database, database.begin():
                audit_count = await database.scalar(select(func.count()).select_from(AuditEvent))
                permission = await database.get(ConversationPermission, setup.state.permission_id)
                assert permission is not None
                deadline = permission.retention_until
                if erasure == "person":
                    assert await erase_sales_xray_profile(database, person_id=setup.state.person_id)
                    assert not await erase_sales_xray_profile(
                        database, person_id=setup.state.person_id
                    )
            if erasure == "recording":
                await _reconcile(setup.sessions, setup.state)
                # Only this recording reaches its deadline; sibling rows must survive.
                async with setup.sessions() as database, database.begin():
                    from ac_platform.conversation_intelligence.models import ConversationRecording

                    recording = await database.get(ConversationRecording, source["recording_id"])
                    assert recording is not None
                    permission = await database.get(ConversationPermission, recording.permission_id)
                    assert permission is not None
                    permission.retention_until = deadline - timedelta(seconds=1)
                scheduler = ConversationRetentionScheduler(setup.sessions, clock=lambda: deadline)
                assert await scheduler.step()
                worker = OfflineConversationWorker(
                    setup.sessions,
                    storage=setup.runtime.storage,
                    scratch=setup.runtime.scratch,
                    environment="test",
                )
                assert await worker.run_once()
            async with setup.sessions() as database:
                rows = (await database.scalars(select(ConversationSpeakerMapRevision))).all()
                ids = {row.submission_id for row in rows}
                assert source["submission_id"] not in ids
                assert (sibling["submission_id"] in ids) == (erasure == "recording")
                assert unrelated["submission_id"] in ids
                assert (
                    await database.scalar(select(func.count()).select_from(AuditEvent))
                    >= audit_count
                )
                for tenant in (setup.state.tenant_id, other.state.tenant_id):
                    assert (await verify_audit_chain(database, tenant)).valid
        finally:
            await setup.engine.dispose()
            await other.engine.dispose()

    run(exercise())
