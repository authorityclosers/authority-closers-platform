"""Exact owner/destination eligibility without mutation of immutable call facts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationAcquisitionUsage as Usage,
)
from ac_platform.conversation_intelligence.acquisition_models import (
    ConversationVisitor,
    ConversationVisitorClaim,
)
from ac_platform.conversation_intelligence.application import ConversationDenied
from ac_platform.conversation_intelligence.canary_models import ConversationCanarySubmission
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission as Source
from ac_platform.conversation_intelligence.models import ConversationPermission as Permission
from ac_platform.conversation_intelligence.models import ConversationRecording as Recording
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import ResourceNotFound
from ac_platform.organisations.call_move import personal_call_move_candidate
from ac_platform.tenancy.models import Membership, Tenant
from tests.unit.http.test_organisation import state as organisation_state  # noqa: F401
from tests.unit.http.test_organisation_activity import seed_call
from tests.unit.http.test_workspaces import HttpDatabase, workspace_state  # noqa: F401


@pytest.fixture
def state(request):
    state = request.getfixturevalue("organisation_state")
    state.personal = state.settings.public_learner_tenant_id
    state.now = datetime.now(UTC)
    with Session(state.engine) as database, database.begin():
        database.get(IdentitySession, state.session).selected_tenant_id = state.personal
        state.submission = seed_call(
            database, state.personal, state.person, created_at=state.now - timedelta(days=2)
        )
    state.actor = ActorContext(state.person, state.session, state.personal)
    return state


async def candidate(database, state, *, actor=None, destination=None, submission=None):
    return await personal_call_move_candidate(
        HttpDatabase(database),
        actor or state.actor,
        submission_id=submission or state.submission,
        destination_tenant_id=destination or state.tenant,
        public_learner_tenant_id=state.personal,
        operations_tenant_id=state.settings.operations_tenant_id,
        at=state.now,
    )


async def test_actual_person_owns_call_while_recording_principal_and_every_source_fact_stay_intact(
    state,
):
    writes = []

    @event.listens_for(state.engine, "before_cursor_execute")
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    with Session(state.engine) as database, database.begin():
        result = await candidate(database, state)
        link = database.get(Source, (state.personal, state.submission))
        usage = database.get(Usage, link.usage_id)
        recording = database.get(Recording, link.recording_id)
        assert result.processing_person_id == recording.person_id != state.person
        assert result.owner_person_id == usage.person_id == state.person
        assert result.source_tenant_id == recording.tenant_id == usage.tenant_id == state.personal
        assert result.destination_tenant_id == state.tenant
        assert result.recording_id == link.recording_id and result.usage_id == link.usage_id
        assert result.source_sha256 == link.source_sha256 == usage.source_sha256
        assert result.source_revision == result.source_generation == 1
        assert result.permission_id == recording.permission_id
        # Processing permission expiry does not extend or erase retained source authority.
        permission = database.get(Permission, result.permission_id)
        assert permission.expires_at.replace(tzinfo=UTC) < state.now
        assert permission.retention_until.replace(tzinfo=UTC) > state.now
    assert writes == []


@pytest.mark.parametrize(
    "fence",
    ["other_owner", "deleting", "deleted", "consent_revoked", "retention_expired", "canary"],
)
async def test_unowned_or_unavailable_source_cannot_be_assigned(state, fence):
    with Session(state.engine) as database, database.begin():
        link = database.get(Source, (state.personal, state.submission))
        if fence == "other_owner":
            database.add(
                Membership(tenant_id=state.personal, person_id=state.other, role="learner")
            )
            database.flush()
            other_submission = seed_call(
                database, state.personal, state.other, created_at=state.now
            )
        elif fence in {"deleting", "deleted"}:
            database.get(Recording, link.recording_id).state = fence
        elif fence == "consent_revoked":
            database.get(
                Permission, database.get(Recording, link.recording_id).permission_id
            ).revoked_at = state.now
        elif fence == "retention_expired":
            database.get(
                Permission, database.get(Recording, link.recording_id).permission_id
            ).retention_until = state.now - timedelta(days=1)
        else:
            database.add(
                ConversationCanarySubmission(
                    tenant_id=state.personal,
                    submission_id=state.submission,
                    environment="test",
                    fixture_sha256="f" * 64,
                    created_at=state.now,
                )
            )
    with Session(state.engine) as database, database.begin(), pytest.raises(ResourceNotFound):
        await candidate(
            database, state, submission=other_submission if fence == "other_owner" else None
        )


@pytest.mark.parametrize(
    "fence",
    ["not_member", "ended", "processing", "inactive_org", "personal", "operations", "unregistered"],
)
async def test_destination_requires_live_human_membership_in_active_registered_org(state, fence):
    destination = state.tenant
    with Session(state.engine) as database, database.begin():
        member = database.get(Membership, (state.tenant, state.person))
        if fence == "not_member":
            database.delete(member)
        elif fence == "ended":
            member.status, member.ended_at = "inactive", state.now
        elif fence == "processing":
            member.role = "processing"
        elif fence == "inactive_org":
            database.get(Tenant, state.tenant).status = "suspended"
        else:
            destination = {
                "personal": state.personal,
                "operations": state.settings.operations_tenant_id,
                "unregistered": state.tenants["Inactive"],
            }[fence]
            if fence == "unregistered":
                unregistered = database.get(Membership, (destination, state.person))
                unregistered.role, unregistered.status, unregistered.ended_at = (
                    "owner",
                    "active",
                    None,
                )
    with Session(state.engine) as database, database.begin(), pytest.raises(ResourceNotFound):
        await candidate(database, state, destination=destination)


async def test_selected_context_and_session_are_rechecked_without_fabricating_source_actor(state):
    with Session(state.engine) as database, database.begin():
        database.get(IdentitySession, state.session).selected_tenant_id = state.tenant
    with Session(state.engine) as database, database.begin(), pytest.raises(ConversationDenied):
        await candidate(database, state)
    with Session(state.engine) as database, database.begin(), pytest.raises(ResourceNotFound):
        await candidate(
            database, state, actor=ActorContext(state.person, state.session, state.tenant)
        )


async def test_explicit_claim_resolves_guest_owner_without_changing_usage_person(state):
    visitor_id = uuid4()
    with Session(state.engine) as database, database.begin():
        database.add(
            ConversationVisitor(
                id=visitor_id,
                tenant_id=state.personal,
                token_hash=uuid4().bytes * 2,
                created_at=state.now,
                expires_at=state.now + timedelta(days=1),
            )
        )
        database.flush()
        submission = seed_call(
            database, state.personal, state.person, created_at=state.now, visitor_id=visitor_id
        )
    with Session(state.engine) as database, database.begin(), pytest.raises(ResourceNotFound):
        await candidate(database, state, submission=submission)
    with Session(state.engine) as database, database.begin():
        database.add(
            ConversationVisitorClaim(
                visitor_id=visitor_id,
                tenant_id=state.personal,
                person_id=state.person,
                session_id=state.session,
                created_at=state.now,
            )
        )
    with Session(state.engine) as database, database.begin():
        result = await candidate(database, state, submission=submission)
        usage = database.get(Usage, result.usage_id)
        assert result.owner_person_id == state.person
        assert usage.person_id is None and usage.visitor_id == visitor_id
