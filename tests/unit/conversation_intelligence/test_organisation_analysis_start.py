"""Owner decision 16 Oct: organisation owners/admins may start a member's analysis.

Fictional relational proof. Only the start path opens (quote/accept use
``allow_organisation_start``); members, outsiders, removed admins and
personal workspaces get nothing new, and every other change stays the
uploader's alone.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.tenancy.models import Membership
from tests.unit.conversation_intelligence.test_organisation_call_reads import seed_readable_call
from tests.unit.http.test_organisation import state  # noqa: F401
from tests.unit.http.test_workspaces import HttpDatabase, workspace_state  # noqa: F401


def ownership_for(db, tenant) -> GuestOwnership:
    return GuestOwnership(
        AcquisitionSessions(HttpDatabase(db), tenant_id=tenant, policy_revision="fictional")
    )


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
async def test_only_owners_and_admins_may_start_a_members_call(state, role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
        submission = seed_readable_call(
            db, state.tenant, state.member, created_at=datetime.now(UTC)
        )
        ownership = ownership_for(db, state.tenant)
        actor = ActorContext(state.person, state.session, state.tenant)
        # Without the start path nothing changes: the uploader alone may act.
        with pytest.raises(ConversationNotFound):
            await ownership.require_submission_owner(submission, actor=actor)
        with pytest.raises(ConversationNotFound):
            await ownership.ensure_processing_continuation(submission, key="k-1", actor=actor)
        if role == "member":
            with pytest.raises(ConversationNotFound):
                await ownership.require_submission_owner(
                    submission, actor=actor, allow_organisation_start=True
                )
            with pytest.raises(ConversationNotFound):
                await ownership.ensure_processing_continuation(
                    submission, key="k-2", actor=actor, allow_organisation_start=True
                )
            return
        scope = await ownership.require_submission_owner(
            submission, actor=actor, allow_organisation_start=True
        )
        assert scope.submission_id == submission and scope.claimed_account
        # (The lease renewal and processing actor run the same ownership check
        # under PostgreSQL row locks; SQLite stops at the read path here.)
        # The call stays the member's: the audit names them as its owner.
        assert await ownership.call_owner_person_id(submission) == state.member


async def test_outsiders_removed_admins_and_personal_workspaces_get_no_start(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = "admin"
        submission = seed_readable_call(
            db, state.tenant, state.member, created_at=datetime.now(UTC)
        )
        ownership = ownership_for(db, state.tenant)
        # An actor scoped to another workspace is no organisation reader here.
        outsider = ActorContext(state.person, state.session, uuid4())
        with pytest.raises((ConversationNotFound, ConversationDenied)):
            await ownership.require_submission_owner(
                submission, actor=outsider, allow_organisation_start=True
            )
        # Personal workspaces have no organisation authority at all.
        personal = state.settings.public_learner_tenant_id
        db.get(Membership, (personal, state.person)).role = "owner"
        db.get(IdentitySession, state.session).selected_tenant_id = personal
        assert not await ownership_for(db, personal).organisation_call_reader(
            ActorContext(state.person, state.session, personal)
        )
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenant
        # A removed admin loses the start path at once.
        membership = db.get(Membership, (state.tenant, state.person))
        membership.status, membership.ended_at = "inactive", datetime.now(UTC)
        db.flush()
        with pytest.raises((ConversationNotFound, ConversationDenied)):
            await ownership.require_submission_owner(
                submission,
                actor=ActorContext(state.person, state.session, state.tenant),
                allow_organisation_start=True,
            )
