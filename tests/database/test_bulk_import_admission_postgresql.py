"""Real source/race regressions for bounded uploader capacity; no hosted data."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage,
    ConversationReportMinuteEvent,
)
from ac_platform.conversation_intelligence.bulk_import_admission import active_local_item
from ac_platform.conversation_intelligence.bulk_import_models import ConversationRecordingImportItem
from ac_platform.conversation_intelligence.guest_models import (
    ConversationGuestSubmission,
    ConversationProcessingContinuation,
    ConversationProcessingLease,
)
from ac_platform.conversation_intelligence.models import ConversationRecording, ConversationRun
from ac_platform.outbox.models import Job
from tests.database.test_bulk_import_postgresql import (
    client_for,
    confirm,
    setup_import,
    source,
    upload,
)
from tests.database.test_bulk_import_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run
from tests.database.test_conversation_submission_http_postgresql import PREFIX, _wav_one_second_48k


@pytest.fixture
def postgres_harness(monkeypatch):
    yield from _postgres_harness.__wrapped__(monkeypatch)


def test_only_current_bounded_local_work_blocks_its_uploader_and_admission_races_serialize(
    postgres_harness,
    tmp_path,
):
    async def exercise():
        setup = await setup_import(postgres_harness, tmp_path)
        data = _wav_one_second_48k()
        other = bytearray(data)
        other[-2] ^= 1
        other = bytes(other)
        third = bytearray(data)
        third[-4] ^= 1
        third = bytes(third)
        try:
            async with await client_for(setup) as client:
                response, _ = await confirm(client, setup, [source("Rep/one", data)])
                assert response.status_code == 201
                batch = response.json()
                accepted = await upload(client, batch, 0, data)
                assert accepted.status_code == 202, accepted.text
                submission = UUID(accepted.json()["submission_id"])
                another, _ = await confirm(
                    client,
                    setup,
                    [source("Rep/two", other), source("Rep/three", third)],
                    key="second-batch",
                )
                assert another.status_code == 201
                second = another.json()
                blocked = await upload(client, second, 0, other)
                assert blocked.status_code == 409 and "still processing" in blocked.text
                assert setup.native.calls == 1
                async with setup.sessions() as db:
                    usage = await db.scalar(
                        select(ConversationAcquisitionUsage).where(
                            ConversationAcquisitionUsage.submission_id == submission,
                        )
                    )
                    link = await db.get(
                        ConversationGuestSubmission,
                        (
                            setup.organisation.tenant_id,
                            submission,
                        ),
                    )
                    original = await db.scalar(
                        select(ConversationRun).where(
                            ConversationRun.recording_id == link.recording_id,
                        )
                    )
                    recording = await db.get(ConversationRecording, link.recording_id)
                    lease = await db.get(ConversationProcessingLease, link.processing_lease_id)
                    # Keep identifier/recipe snapshots across rolled-back
                    # state probes, without implicit async attribute reloads.
                    db.expunge(original)
                    query = dict(
                        tenant_id=setup.organisation.tenant_id,
                        uploader_id=setup.state.person_id,
                        submission_id=UUID(second["files"][0]["upload_submission_id"]),
                        now=setup.clock[0],
                    )
                    assert await db.scalar(active_local_item(**query)) == usage.id
                    for override in (
                        {"uploader_id": setup.organisation.person_id},
                        {"tenant_id": setup.state.tenant_id},
                        {"submission_id": submission},
                        {"now": setup.clock[0] + timedelta(hours=1)},
                    ):
                        assert await db.scalar(active_local_item(**(query | override))) is None
                    # Missing uploads and refused allowance create no current
                    # local job. Historical reserved minutes cannot own capacity.
                    for state in ("completed", "failed", "cancelled"):
                        async with db.begin_nested() as savepoint:
                            await db.execute(
                                update(ConversationRun)
                                .where(
                                    ConversationRun.id == original.id,
                                )
                                .values(state=state, completed_at=setup.clock[0])
                            )
                            assert await db.scalar(active_local_item(**query)) is None
                            await savepoint.rollback()
                    async with db.begin_nested() as savepoint:
                        db.add(
                            ConversationReportMinuteEvent(
                                usage_id=usage.id,
                                revision=1,
                                key="fictional-reserved",
                                kind="reserved",
                                seconds=usage.reserved_seconds,
                                receipt_sha256="a" * 64,
                                created_at=setup.clock[0],
                            )
                        )
                        await db.execute(
                            update(ConversationRun)
                            .where(
                                ConversationRun.id == original.id,
                            )
                            .values(state="failed", completed_at=setup.clock[0])
                        )
                        await db.flush()
                        assert await db.scalar(active_local_item(**query)) is None
                        await savepoint.rollback()
                    for state in (
                        "queued",
                        "leased",
                        "retry_wait",
                        "succeeded",
                        "held",
                        "dead_letter",
                    ):
                        async with db.begin_nested() as savepoint:
                            values = dict(status=state, lease_token=None, leased_until=None)
                            if state == "leased":
                                values.update(
                                    lease_token=uuid4(),
                                    leased_until=setup.clock[0] + timedelta(minutes=5),
                                )
                            if state == "held":
                                values.update(held_at=setup.clock[0], hold_reason="fictional_hold")
                            if state == "dead_letter":
                                values.update(
                                    dead_lettered_at=setup.clock[0], last_error="fictional_failure"
                                )
                            await db.execute(
                                update(Job).where(Job.id == original.job_id).values(**values)
                            )
                            found = await db.scalar(active_local_item(**query))
                            assert (found is not None) == (
                                state in {"queued", "leased", "retry_wait"}
                            )
                            await savepoint.rollback()
                    # A retry successor owns capacity, even after a failed
                    # predecessor. Only the current recording generation counts.
                    async with db.begin_nested() as savepoint:
                        await db.execute(
                            update(ConversationRun)
                            .where(
                                ConversationRun.id == original.id,
                            )
                            .values(state="failed", completed_at=setup.clock[0])
                        )
                        job = Job(
                            id=uuid4(),
                            tenant_id=recording.tenant_id,
                            kind="conversation.inspect_local.v1",
                            dedupe_key=f"fictional-local-retry:{uuid4()}",
                            payload={},
                        )
                        db.add(job)
                        await db.flush()
                        retry = ConversationRun(
                            id=uuid4(),
                            tenant_id=recording.tenant_id,
                            person_id=recording.person_id,
                            recording_id=recording.id,
                            request_key=f"fictional-retry:{uuid4()}",
                            intent_sha256="f" * 64,
                            recipe_revision=original.recipe_revision,
                            generation=recording.generation,
                            state="queued",
                            job_id=job.id,
                            created_at=setup.clock[0] + timedelta(seconds=1),
                        )
                        db.add(retry)
                        await db.flush()
                        assert await db.scalar(active_local_item(**query)) == usage.id
                        await db.execute(
                            update(ConversationRun)
                            .where(ConversationRun.id == retry.id)
                            .values(
                                generation=recording.generation + 1,
                            )
                        )
                        assert await db.scalar(active_local_item(**query)) is None
                        await savepoint.rollback()
                    # Valid owner continuation counts only while the fixed local
                    # budget remains; expired source authority never blocks.
                    later = lease.expires_at + timedelta(seconds=1)
                    async with db.begin_nested() as savepoint:
                        await db.execute(
                            update(ConversationRun)
                            .where(ConversationRun.id == original.id)
                            .values(
                                created_at=later,
                            )
                        )
                        assert (
                            await db.scalar(active_local_item(**(query | {"now": later}))) is None
                        )
                        db.add(
                            ConversationProcessingContinuation(
                                id=uuid4(),
                                tenant_id=recording.tenant_id,
                                person_id=recording.person_id,
                                submission_id=submission,
                                recording_id=recording.id,
                                processing_lease_id=lease.id,
                                usage_id=usage.id,
                                owner_person_id=usage.person_id,
                                owner_visitor_id=None,
                                source_sha256=recording.source_sha256,
                                source_revision=recording.source_revision,
                                generation=recording.generation,
                                created_at=later,
                                expires_at=later + timedelta(hours=2),
                            )
                        )
                        await db.flush()
                        assert (
                            await db.scalar(active_local_item(**(query | {"now": later})))
                            == usage.id
                        )
                        assert (
                            await db.scalar(
                                active_local_item(**(query | {"now": later + timedelta(hours=1)}))
                            )
                            is None
                        )
                        await savepoint.rollback()
                # Leave the old local run completed, without touching its NULL
                # minute event. New local uploads now compete fairly under the
                # existing transaction lock; a provider report is not required.
                async with setup.sessions() as db, db.begin():
                    await db.execute(
                        update(ConversationRun)
                        .where(
                            ConversationRun.id == original.id,
                        )
                        .values(state="completed", completed_at=setup.clock[0])
                    )
                never_uploaded, _ = await confirm(
                    client,
                    setup,
                    [source("Rep/not-uploaded", b"fictional-refused")],
                    key="not-uploaded",
                )
                assert never_uploaded.status_code == 201
                async with setup.sessions() as db, db.begin():
                    pending = never_uploaded.json()["files"][0]
                    unlinked_usage = ConversationAcquisitionUsage(
                        id=uuid4(),
                        tenant_id=setup.organisation.tenant_id,
                        visitor_id=None,
                        person_id=setup.member.person_id,
                        submission_id=UUID(pending["upload_submission_id"]),
                        source_sha256=pending["source_sha256"],
                        duration_evidence_sha256="c" * 64,
                        reserved_seconds=1,
                        policy_revision="guest-processing-v1",
                        created_at=setup.clock[0],
                    )
                    db.add(unlinked_usage)
                    await db.flush()
                    await db.execute(
                        update(ConversationRecordingImportItem)
                        .where(
                            ConversationRecordingImportItem.batch_id
                            == UUID(never_uploaded.json()["batch_id"]),
                        )
                        .values(usage_id=unlinked_usage.id, linked_at=setup.clock[0])
                    )
                    assert await db.scalar(active_local_item(**query)) is None
                results = await asyncio.gather(
                    upload(client, second, 0, other), upload(client, second, 1, third)
                )
                assert sorted(r.status_code for r in results) in ([202, 409], [202, 429]), [
                    r.text for r in results
                ]
                loser = next(
                    index for index, result in enumerate(results) if result.status_code != 202
                )
                refused = await upload(client, second, loser, other if loser == 0 else third)
                assert refused.status_code == 409
                progress = await client.get(PREFIX + "/imports/" + batch["batch_id"])
                assert progress.status_code == 200
                assert progress.json()["files"][0]["local_state"] == "completed"
                assert "plan_state" in progress.json()["files"][0]
                assert progress.json()["terminal_state"] is None
                replay = await upload(client, batch, 0, data)
                assert replay.status_code == 202 and replay.json()["state"] == "already_imported"
                async with setup.sessions() as db:
                    assert (
                        await db.scalar(
                            select(func.count()).select_from(ConversationAcquisitionUsage)
                        )
                        == 3
                    )
                    assert await db.scalar(select(func.count()).select_from(Job)) == 2
        finally:
            await setup.engine.dispose()

    run(exercise())
