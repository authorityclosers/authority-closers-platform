"""Relational admission and tenant/owner denial; PG races are a separate receipt."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.conversation_intelligence.application import (
    DELETE_JOB,
    ConversationApplication,
    ConversationConflict,
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.contracts import RecordingIntent
from ac_platform.conversation_intelligence.models import (
    ConversationCommand,
    ConversationPermission,
    ConversationRecording,
)
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.test_practice_engine import AwaitableSession
from tests.unit.test_practice_engine import state as platform_state  # noqa: F401


class DatabaseAdapter(AwaitableSession):
    async def get(self, model, identifier, **kwargs):
        return self.database.get(model, identifier, **kwargs)

    async def refresh(self, row):
        self.database.refresh(row)


@pytest.fixture
def state(platform_state):  # noqa: F811
    state = platform_state
    state.async_db = DatabaseAdapter(state.db)
    state.app = ConversationApplication(state.async_db, clock=lambda: state.now)
    state.permission = ConversationPermission(
        id=uuid4(),
        tenant_id=state.tenant,
        person_id=state.person,
        source_sha256="a" * 64,
        provider="local",
        permission_reference="fixture:consent:1",
        retention_reference="fixture:retention:1",
        created_at=state.now,
        expires_at=state.now + timedelta(days=1),
        retention_until=state.now + timedelta(days=2),
    )
    state.db.add(state.permission)
    state.db.flush()
    state.intent = RecordingIntent(
        source_sha256="a" * 64,
        source_bytes=1024,
        content_type="audio/wav",
        permission_reference=state.permission.id,
        purpose="internal_analysis",
    )
    return state


@pytest.mark.asyncio
async def test_register_replays_exact_command_without_extra_audit(state):
    first = await state.app.register(state.actor, state.intent, key="recording-1")
    again = await state.app.register(state.actor, state.intent, key="recording-1")
    assert first == again and first["state"] == "awaiting_upload"
    assert state.db.scalar(select(func.count()).select_from(ConversationCommand)) == 1
    assert verify_audit_chain_sync(state.db, state.tenant).valid
    with pytest.raises(ConversationConflict):
        await state.app.register(
            state.actor,
            state.intent.model_copy(update={"source_bytes": 2048}),
            key="recording-1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["person", "tenant", "missing_tenant", "session", "random"])
async def test_guessed_id_never_grants_read_or_checkpoint_access(state, change):
    result = await state.app.register(state.actor, state.intent, key="recording")
    actor, recording_id = state.other_actor, UUID(result["id"])
    if change == "tenant":
        actor = replace(state.actor, tenant_id=uuid4())
    elif change == "missing_tenant":
        actor = replace(state.actor, tenant_id=None)
    elif change == "session":
        actor = replace(state.actor, session_id=state.other_session)
    elif change == "random":
        actor, recording_id = state.actor, uuid4()
    for method in (state.app.get, state.app.checkpoints):
        with pytest.raises((ConversationDenied, ConversationNotFound)):
            await method(actor, recording_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "expired_session",
        "revoked_session",
        "inactive_person",
        "unverified_person",
        "inactive_tenant",
        "inactive_member",
        "ended_member",
        "expired_permission",
        "revoked_permission",
        "retention",
    ],
)
async def test_fresh_server_authority_is_required(state, change):
    result = await state.app.register(state.actor, state.intent, key="recording")
    if change == "expired_session":
        session = state.db.get(IdentitySession, state.session)
        session.created_at = state.now - timedelta(minutes=1)
        session.expires_at = state.now
    elif change == "revoked_session":
        state.db.get(IdentitySession, state.session).revoked_at = state.now
    elif change == "inactive_person":
        state.db.get(Person, state.person).status = "suspended"
    elif change == "unverified_person":
        state.db.get(Person, state.person).email_verified_at = None
    elif change == "inactive_tenant":
        state.db.get(Tenant, state.tenant).status = "suspended"
    elif change == "inactive_member":
        member = state.db.get(Membership, (state.tenant, state.person))
        member.status, member.ended_at = "inactive", state.now - timedelta(days=1)
    elif change == "ended_member":
        member = state.db.get(Membership, (state.tenant, state.person))
        member.status, member.ended_at = "inactive", state.now
    elif change == "expired_permission":
        state.permission.expires_at = state.now
    elif change == "revoked_permission":
        state.permission.revoked_at = state.now
    else:
        state.now += timedelta(days=3)
    state.db.flush()
    with pytest.raises(ConversationDenied):
        await state.app.get(state.actor, UUID(result["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["random", "different_source", "different_owner"])
async def test_permission_reference_is_resolved_not_trusted(state, change):
    intent = state.intent
    actor = state.actor
    if change == "random":
        intent = intent.model_copy(update={"permission_reference": uuid4()})
    elif change == "different_source":
        intent = intent.model_copy(update={"source_sha256": "b" * 64})
    else:
        actor = state.other_actor
    with pytest.raises(ConversationDenied):
        await state.app.register(actor, intent, key="attempt")
    assert state.db.scalar(select(func.count()).select_from(ConversationRecording)) == 0


@pytest.mark.asyncio
async def test_deletion_revokes_reads_and_enqueues_exactly_one_durable_job(state):
    result = await state.app.register(state.actor, state.intent, key="recording")
    identifier = UUID(result["id"])
    state.permission.revoked_at = state.now  # Erasure remains available after consent withdrawal.
    first = await state.app.request_deletion(state.actor, identifier, key="delete")
    again = await state.app.request_deletion(state.actor, identifier, key="delete")
    assert first == again == {"id": str(identifier), "state": "deleting"}
    with pytest.raises(ConversationNotFound):
        await state.app.get(state.actor, identifier)
    jobs = state.db.scalars(select(Job)).all()
    assert len(jobs) == 1 and jobs[0].kind == DELETE_JOB
    assert jobs[0].payload == {"recording_id": str(identifier), "generation": 2}
    assert jobs[0].external_side_effect is False
    assert verify_audit_chain_sync(state.db, state.tenant).valid


@pytest.mark.asyncio
async def test_same_tenant_admin_cannot_read_another_persons_recording(state):
    result = await state.app.register(state.actor, state.intent, key="recording")
    state.db.get(Membership, (state.tenant, state.other)).role = "admin"
    state.db.flush()
    with pytest.raises(ConversationNotFound):
        await state.app.get(state.other_actor, UUID(result["id"]))
