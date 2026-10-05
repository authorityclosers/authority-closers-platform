"""Fictional prospect fixtures on disposable PostgreSQL, with canonical Calls access."""

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import DBAPIError

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_sessions import MeasuredSource
from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.application import (
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.conversation_intelligence.prospect_models import (
    ConversationProspectMembership,
)
from ac_platform.conversation_intelligence.prospect_store import ProspectStore
from ac_platform.conversation_intelligence.retention import ConversationRetentionScheduler
from ac_platform.conversation_intelligence.worker import OfflineConversationWorker
from ac_platform.db.models import model_metadata
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership, Organisation
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed, wait_blocked
from tests.database.test_conversation_submission_http_postgresql import _setup
from tests.database.test_conversation_submission_labels_postgresql import (
    _retained_claimed_submission,
)
from tests.database.test_conversation_worker_postgresql import _reconcile, _wav_one_second_48k


@pytest.fixture
def postgres_harness() -> Any:
    yield from cast(Any, _postgres_harness).__wrapped__()


def store(setup: Any, database: Any) -> ProspectStore:
    return ProspectStore(GuestOwnership(setup.factory(database)))


async def direct_call(setup: Any, actor: ActorContext | None = None) -> UUID:
    """A fictional measured call through canonical storage, without native media measurement."""
    audio, submission_id = _wav_one_second_48k(), uuid4()
    source_sha256 = hashlib.sha256(audio).hexdigest()
    upload = MeasuredUpload(
        MeasuredSource(
            submission_id,
            source_sha256,
            1_000,
            hashlib.sha256(b"prospect-fixture-duration").hexdigest(),
        ),
        IntakeIntent(
            source_sha256=source_sha256,
            source_bytes=len(audio),
            content_type="audio/wav",
            duration_ms=1_000,
            purpose="internal_analysis",
        ),
    )
    async with setup.sessions() as db, db.begin():
        processing = AcquisitionProcessing(GuestOwnership(setup.factory(db)), setup.runtime)
        processing_actor, quote = await processing.prepare(
            upload,
            policy_sha256=upload_policy(setup.runtime.policy)["policy_sha256"],
            actor=actor or setup.state.actor,
        )
        await processing.application.store_source(
            processing_actor,
            UUID(quote["recording_id"]),
            chunks=(audio,),
            storage=setup.runtime.storage,
        )
    return submission_id


def test_explicit_identity_link_supersession_and_database_history_guards(
    postgres_harness: Any, tmp_path: Path
) -> None:
    with postgres_harness.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), model_metadata()) == []

    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        actor = setup.state.actor
        try:
            claimed = await _retained_claimed_submission(setup)
            direct = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                first = await service.create_from_call(
                    actor, claimed["submission_id"], display_name="Asha Example"
                )
                second = await service.create_from_call(actor, direct, display_name="Asha Example")
                assert first.id != second.id and first.display_name == second.display_name
                old = (await service.read_memberships(actor, second.id))[0]
                new = await service.confirm_link(
                    actor, direct, first.id, expected_membership_id=old.id
                )
                assert old.id != new.id and old.ended_reason == "superseded"
                assert (
                    await service.confirm_link(
                        actor, direct, first.id, expected_membership_id=old.id
                    )
                    is new
                )
                with pytest.raises(ConversationConflict):
                    await service.confirm_link(
                        actor, direct, second.id, expected_membership_id=old.id
                    )
                with pytest.raises(ConversationConflict):
                    await service.create_from_call(actor, direct, display_name="Never created")
                before = [row.id for row in await service.read_memberships(actor, first.id)]
                assert before == [row.id for row in await service.read_memberships(actor, first.id)]
                assert (
                    len(before) == 2
                    and len(await service.read_memberships(actor, first.id, limit=1)) == 1
                )
                for values in (
                    {"prospect_id": second.id},
                    {"created_at": setup.state.now},
                    {"ended_reason": "unlinked"},
                ):
                    with pytest.raises(DBAPIError):
                        async with db.begin_nested():
                            await db.execute(
                                update(ConversationProspectMembership)
                                .where(ConversationProspectMembership.id == new.id)
                                .values(**values)
                            )
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(
                            delete(ConversationProspectMembership).where(
                                ConversationProspectMembership.id == old.id
                            )
                        )
                await service.unlink(actor, direct, expected_membership_id=new.id)
                replacement = await service.confirm_link(
                    actor, direct, first.id, expected_membership_id=None
                )
                assert replacement.id not in (old.id, new.id)
                assert new.ended_by_person_id == actor.person_id and new.ended_reason == "unlinked"
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        await db.execute(
                            update(ConversationProspectMembership)
                            .where(ConversationProspectMembership.id == new.id)
                            .values(ended_reason="superseded")
                        )
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        db.add(
                            ConversationProspectMembership(
                                id=uuid4(),
                                tenant_id=actor.tenant_id,
                                prospect_id=second.id,
                                submission_id=direct,
                                linked_by_person_id=actor.person_id,
                                created_at=setup.state.now,
                            )
                        )
                        await db.flush()
                first_id = first.id
            async with setup.sessions() as db, db.begin():
                assert (await store(setup, db).read(actor, first_id)).display_name == "Asha Example"
                assert (await verify_audit_chain(db, actor.tenant_id)).valid
                events = (
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id)
                    )
                ).all()
                assert "Asha Example" not in str([event.payload for event in events])
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_person_tenant_and_org_read_boundaries(postgres_harness: Any, tmp_path: Path) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        actor = setup.state.actor
        try:
            claimed = await _retained_claimed_submission(setup)
            direct = await direct_call(setup)
            other = await seed(setup.engine, tenant_id=actor.tenant_id, role="member")
            foreign = await seed(setup.engine)
            other_call = await direct_call(setup, other.actor)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                first = await service.create_from_call(
                    actor, claimed["submission_id"], display_name="Shared Fictional Prospect"
                )
                second = await service.create_from_call(
                    actor, direct, display_name="Private Fictional Prospect"
                )
                with pytest.raises(ConversationNotFound):
                    await service.read(other.actor, first.id)
                assert await service.read_memberships(other.actor, first.id) == []
                with pytest.raises(ConversationNotFound):
                    await service.confirm_link(
                        other.actor, direct, first.id, expected_membership_id=None
                    )
                with pytest.raises(ConversationDenied):
                    await service.read(foreign.actor, first.id)
                # The fictional second owner is persisted through the same membership contract.
                own = await service.create_from_call(
                    other.actor, other_call, display_name="Other Owner Prospect"
                )
                current = (await service.read_memberships(actor, first.id))[0]
                await service.confirm_link(
                    actor,
                    direct,
                    first.id,
                    expected_membership_id=(await service.read_memberships(actor, second.id))[0].id,
                )
                # An explicit shared call link grants name visibility but no other calls.
                # Fixture bootstrap only: there is deliberately no public global name search.
                await service.unlink(
                    other.actor,
                    other_call,
                    expected_membership_id=(await service.read_memberships(other.actor, own.id))[
                        0
                    ].id,
                )
                db.add(
                    ConversationProspectMembership(
                        id=uuid4(),
                        tenant_id=actor.tenant_id,
                        prospect_id=first.id,
                        submission_id=other_call,
                        linked_by_person_id=other.person_id,
                        created_at=setup.state.now,
                    )
                )
                await db.flush()
                assert (await service.read(other.actor, first.id)).id == first.id
                assert [
                    row.submission_id
                    for row in await service.read_memberships(other.actor, first.id)
                ] == [other_call]
                assert {
                    row.submission_id for row in await service.read_memberships(actor, first.id)
                } == {direct, claimed["submission_id"]}
                with pytest.raises(DBAPIError):
                    async with db.begin_nested():
                        db.add(
                            ConversationProspectMembership(
                                id=uuid4(),
                                tenant_id=foreign.tenant_id,
                                prospect_id=first.id,
                                submission_id=direct,
                                linked_by_person_id=foreign.person_id,
                                created_at=foreign.now,
                            )
                        )
                        await db.flush()
                db.add(
                    Organisation(
                        tenant_id=actor.tenant_id,
                        created_by_person_id=actor.person_id,
                        creation_command_id=uuid4(),
                        domain_verification_token="fictional-token-" * 4,
                    )
                )
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == actor.tenant_id,
                        Membership.person_id == other.person_id,
                    )
                    .values(role="admin")
                )
                await db.flush()
                assert len(await service.read_memberships(other.actor, first.id)) == 3
                # Organisation read authority grants no writes to another person's call.
                with pytest.raises(ConversationNotFound):
                    await service.unlink(
                        other.actor, claimed["submission_id"], expected_membership_id=current.id
                    )
                await db.execute(
                    update(Membership)
                    .where(
                        Membership.tenant_id == actor.tenant_id,
                        Membership.person_id == other.person_id,
                    )
                    .values(role="member")
                )
                assert len(await service.read_memberships(other.actor, first.id)) == 1
        finally:
            await setup.engine.dispose()

    run(exercise())


@pytest.mark.parametrize("retention", [False, True])
def test_source_lifecycle_hides_links_then_ends_them_without_deleting_history(
    postgres_harness: Any, tmp_path: Path, retention: bool
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        actor = setup.state.actor
        try:
            source = await _retained_claimed_submission(setup)
            async with setup.sessions() as db, db.begin():
                prospect = await store(setup, db).create_from_call(
                    actor, source["submission_id"], display_name="Retained Fictional Name"
                )
                prospect_id = prospect.id
                recording = await db.get(ConversationRecording, source["recording_id"])
                permission = await db.get(ConversationPermission, recording.permission_id)
                permission.retention_until = setup.state.now + timedelta(seconds=10)
                deadline = permission.retention_until
            await _reconcile(setup.sessions, setup.state)
            if retention:
                # Session must still be valid when the source retention deadline passes.
                setup.clock[0] = deadline + timedelta(seconds=1)
                async with setup.sessions() as db, db.begin():
                    assert await store(setup, db).read_memberships(actor, prospect_id) == []
                assert await ConversationRetentionScheduler(
                    setup.sessions, clock=lambda: setup.clock[0]
                ).step()
            else:
                async with setup.sessions() as db, db.begin():
                    await GuestOwnership(setup.factory(db)).request_deletion(
                        source["submission_id"], actor=actor, key="fictional-prospect-erasure"
                    )
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                assert await service.read_memberships(actor, prospect_id) == []
                assert (
                    await service.read(actor, prospect_id)
                ).display_name == "Retained Fictional Name"
                with pytest.raises(ConversationNotFound):
                    await service.create_from_call(
                        actor, source["submission_id"], display_name="No erased source"
                    )
            worker = OfflineConversationWorker(
                setup.sessions,
                storage=setup.runtime.storage,
                scratch=setup.runtime.scratch,
                environment="test",
            )
            assert await worker.run_once()
            async with setup.sessions() as db, db.begin():
                rows = (
                    await db.scalars(
                        select(ConversationProspectMembership).where(
                            ConversationProspectMembership.prospect_id == prospect_id
                        )
                    )
                ).all()
                assert len(rows) == 1 and rows[0].ended_reason == "source_erasure"
                assert rows[0].ended_by_person_id is None and rows[0].ended_at is not None
                assert (await verify_audit_chain(db, actor.tenant_id)).valid
        finally:
            await setup.engine.dispose()

    run(exercise())


def test_concurrent_confirm_links_serialize_and_reject_stale_membership(
    postgres_harness: Any, tmp_path: Path
) -> None:
    async def exercise() -> None:
        setup = await _setup(postgres_harness, tmp_path)
        writer = None
        actor = setup.state.actor
        try:
            claimed = await _retained_claimed_submission(setup)
            direct = await direct_call(setup)
            async with setup.sessions() as db, db.begin():
                service = store(setup, db)
                first = await service.create_from_call(
                    actor, claimed["submission_id"], display_name="First"
                )
                second = await service.create_from_call(actor, direct, display_name="Second")
                old_id = (await service.read_memberships(actor, first.id))[0].id
                first_id, second_id = first.id, second.id
            pid_ready = asyncio.get_running_loop().create_future()

            async def competing_link() -> None:
                from sqlalchemy import text

                async with setup.sessions() as db, db.begin():
                    pid_ready.set_result(await db.scalar(text("SELECT pg_backend_pid()")))
                    await store(setup, db).confirm_link(
                        actor, claimed["submission_id"], first_id, expected_membership_id=old_id
                    )

            async with setup.sessions() as db, db.begin():
                await store(setup, db)._write_scope(actor, claimed["submission_id"])
                writer = asyncio.create_task(competing_link())
                await wait_blocked(setup.engine, await asyncio.wait_for(pid_ready, 5), writer)
                await store(setup, db).confirm_link(
                    actor, claimed["submission_id"], second_id, expected_membership_id=old_id
                )
            with pytest.raises(ConversationConflict):
                await asyncio.wait_for(writer, 5)
            async with setup.sessions() as db, db.begin():
                query = (await store(setup, db).queries(actor)).memberships
                assert await db.scalar(query.with_only_columns(func.count())) == 2
        finally:
            if writer is not None and not writer.done():
                writer.cancel()
                await asyncio.gather(writer, return_exceptions=True)
            await setup.engine.dispose()

    run(exercise())
