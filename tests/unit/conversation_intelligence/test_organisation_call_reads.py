"""Fictional relational proof that organisation reads never grant ownership."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from ac_platform.conversation_intelligence.acquisition_reports import AcquisitionReports
from ac_platform.conversation_intelligence.acquisition_sessions import AcquisitionSessions
from ac_platform.conversation_intelligence.application import (
    ConversationDenied,
    ConversationNotFound,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.models import (
    ConversationRecording,
    ConversationReportDraft,
    ConversationRun,
)
from ac_platform.conversation_intelligence.providers import ProviderResult, scribe_transcript
from ac_platform.conversation_intelligence.report_store import ConversationReports
from ac_platform.conversation_intelligence.reports import load_report_profile, parse_report_draft
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.kernel.authz import ActorContext
from ac_platform.outbox.models import Job
from ac_platform.tenancy.models import Membership
from tests.database.test_conversation_reports_postgresql import _intent
from tests.unit.http.test_organisation import state  # noqa: F401
from tests.unit.http.test_organisation_activity import seed_call
from tests.unit.http.test_workspaces import HttpDatabase, workspace_state  # noqa: F401


def seed_readable_call(db, tenant, owner, *, created_at, visitor_id=None):
    """Use the existing call fixture with a valid, wholly fictional private draft."""
    submission = seed_call(
        db, tenant, owner, created_at=created_at, label="Fictional call", visitor_id=visitor_id
    )
    link = db.get(ConversationGuestSubmission, (tenant, submission))
    recording = db.get(ConversationRecording, link.recording_id)
    intent = _intent(recording.source_sha256)
    normalized = scribe_transcript(
        ProviderResult(
            provider="elevenlabs",
            model="scribe_v2",
            request_id=None,
            response_sha256=intent.receipt.transcription_response_sha256,
            raw_json=intent.raw_transcription_json.encode(),
            data=json.loads(intent.raw_transcription_json),
            input_sha256=recording.source_sha256,
        ),
        duration_ms=90_000,
        source_sha256=recording.source_sha256,
    )
    normalized["duration_ms"] = 90_000
    payload = parse_report_draft(
        intent.report, normalized, source_label="Fictional call"
    ).model_dump(mode="json")
    transcript = dict(native_json=intent.raw_transcription_json, normalized=normalized)
    receipt = intent.receipt.model_dump(mode="json")
    job, run = uuid4(), uuid4()
    db.add(Job(id=job, tenant_id=tenant, kind="fictional", dedupe_key=str(job), payload={}))
    db.flush()
    db.add(
        ConversationRun(
            id=run,
            tenant_id=tenant,
            person_id=link.person_id,
            recording_id=recording.id,
            request_key=str(run),
            intent_sha256="2" * 64,
            recipe_revision="fictional",
            generation=1,
            state="completed",
            job_id=job,
            created_at=created_at,
        )
    )
    db.flush()
    draft = ConversationReportDraft(
        id=uuid4(),
        tenant_id=tenant,
        person_id=link.person_id,
        recording_id=recording.id,
        run_id=run,
        source_revision=1,
        source_sha256=recording.source_sha256,
        payload=payload,
        transcript=transcript,
        evidence_receipt=receipt,
        report_sha256=content_hash(payload),
        transcript_sha256=content_hash(transcript),
        profile_sha256=content_hash(load_report_profile()),
        evidence_receipt_sha256=content_hash(receipt),
        created_at=created_at,
    )
    db.add(draft)
    db.flush()
    ConversationReports._validated(draft, recording)
    return submission


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
async def test_live_role_allows_only_opted_in_report_reads(state, role):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        db.get(Membership, (state.tenant, state.person)).role = role
        submission = seed_readable_call(
            db, state.tenant, state.member, created_at=datetime.now(UTC)
        )
        ownership = GuestOwnership(
            AcquisitionSessions(
                HttpDatabase(db), tenant_id=state.tenant, policy_revision="fictional"
            )
        )
        actor = ActorContext(state.person, state.session, state.tenant)
        with pytest.raises(ConversationNotFound, match="This upload is unavailable."):
            await ownership.require_submission_owner(submission, actor=actor)
        if role == "member":
            with pytest.raises(ConversationNotFound):
                await AcquisitionReports(ownership).report(
                    submission, actor=actor, allow_organisation_read=True
                )
        else:
            report = await AcquisitionReports(ownership).report(
                submission, actor=actor, allow_organisation_read=True
            )
            assert report["submission_id"] == str(submission)
            # A loaded membership must not survive an external demotion in the identity map.
            await ownership.database.execute(
                update(Membership)
                .where(Membership.tenant_id == state.tenant, Membership.person_id == state.person)
                .values(role="member")
                .execution_options(synchronize_session=False)
            )
            with pytest.raises(ConversationNotFound):
                await AcquisitionReports(ownership).report(
                    submission, actor=actor, allow_organisation_read=True
                )


async def test_personal_operations_and_removed_members_get_no_broader_scope(state):  # noqa: F811
    with Session(state.engine) as db, db.begin():
        personal = state.settings.public_learner_tenant_id
        db.get(Membership, (personal, state.person)).role = "owner"
        db.get(IdentitySession, state.session).selected_tenant_id = personal
        personal_owner = GuestOwnership(
            AcquisitionSessions(HttpDatabase(db), tenant_id=personal, policy_revision="fictional")
        )
        assert not await personal_owner.organisation_call_reader(
            ActorContext(state.person, state.session, personal)
        )
        ownership = GuestOwnership(
            AcquisitionSessions(
                HttpDatabase(db),
                tenant_id=state.tenant,
                policy_revision="fictional",
                operations_tenant_id=state.tenant,
            )
        )
        assert not await ownership.organisation_call_reader(
            ActorContext(state.person, state.session, state.tenant)
        )
        db.get(IdentitySession, state.session).selected_tenant_id = state.tenant
        membership = db.get(Membership, (state.tenant, state.person))
        membership.status, membership.ended_at = "inactive", datetime.now(UTC)
        db.flush()
        with pytest.raises(ConversationDenied):
            await ownership.require_submission_owner(
                uuid4(),
                actor=ActorContext(state.person, state.session, state.tenant),
                allow_organisation_read=True,
            )
