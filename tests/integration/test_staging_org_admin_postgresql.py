"""Canonical services, atomicity, replay and sign-in in a fictional PostgreSQL schema."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain_sync
from ac_platform.conversation_intelligence.acquisition_models import ConversationAcquisitionUsage
from ac_platform.conversation_intelligence.application import DELETE_JOB
from ac_platform.conversation_intelligence.guest_models import ConversationGuestSubmission
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.identity.models import Person
from ac_platform.kernel.errors import AuthorizationDenied
from ac_platform.organisations import service as organisation_service
from ac_platform.organisations.invite_email import (
    ORGANISATION_INVITATION_JOB,
    resolve_organisation_invitation_message,
)
from ac_platform.organisations.service import OrganisationCommandError, OrganisationService
from ac_platform.organisations.sign_in import join_at_sign_in_best_effort
from ac_platform.outbox.models import Job, OutboxEvent
from ac_platform.providers.ports import PermanentProviderError
from ac_platform.providers.resend_email import render_email
from ac_platform.tenancy.models import Membership, OrganisationInvite
from tests.integration.test_media_delivery_renewal_postgresql import postgres_harness  # noqa: F401
from tests.integration.test_organisation_membership_data_change_postgresql import counts
from tests.integration.test_organisation_membership_data_change_postgresql import (
    state as membership_state,
)
from tests.unit.http.test_organisation_activity import seed_call
from tests.unit.organisations.test_staging_org_admin import arguments, tool


@pytest.fixture
def admin_state(postgres_harness, monkeypatch):  # noqa: F811
    state = membership_state.__wrapped__(postgres_harness, monkeypatch)
    monkeypatch.setattr(tool, "_settings", lambda _args: state.settings)
    return state


def args_for(state, targets, **kwargs):
    return arguments(state.tenant, state.owner, targets, **kwargs)


@pytest.mark.asyncio
async def test_preview_is_read_only_and_apply_adds_verified_and_invites_others(admin_state, capsys):
    state = admin_state
    args = args_for(
        state,
        [state.people[state.worker], "new-person@example.test", state.people[state.unverified]],
    )
    before = counts(state)
    await tool._run(args)
    preview = json.loads(capsys.readouterr().out)
    assert [row["status"] for row in preview["targets"]] == [
        "eligible",
        "eligible_invite",
        "eligible_invite",
    ]
    assert counts(state) == before
    assert "new-person@example.test" not in json.dumps(preview)
    args.apply, args.snapshot_reference = True, "snapshot-fixture"
    await tool._run(args)
    report = json.loads(capsys.readouterr().out)
    assert all(row["status"] == "applied" for row in report["targets"])
    with Session(state.harness.engine) as db:
        assert db.get(Membership, (state.tenant, state.worker)).role == "member"
        assert db.get(Membership, (state.tenant, state.unverified)) is None
        assert db.scalar(select(Person).where(Person.email == "new-person@example.test")) is None
        pending = list(
            db.scalars(
                select(OrganisationInvite).where(
                    OrganisationInvite.tenant_id == state.tenant,
                    OrganisationInvite.status == "pending",
                )
            )
        )
        assert len(pending) == 2
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == state.tenant)
            )
            == 2
        )
        audits = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == state.tenant,
                    AuditEvent.action == "organisation.staging_admin_applied",
                )
            )
        )
        assert len(audits) == 3
        assert all(json.loads(audit.reason)["approver"] == args.approver for audit in audits)
        assert all(
            audit.actor_type == "operator" and audit.actor_person_id == state.owner
            for audit in audits
        )
        assert verify_audit_chain_sync(db, state.tenant).valid
    before = counts(state)
    await tool._run(args)
    assert all(
        row["status"] == "replayed" for row in json.loads(capsys.readouterr().out)["targets"]
    )
    assert counts(state) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_operator_invite_mail_and_verified_first_sign_in(
    admin_state, capsys, monkeypatch, expired
):
    state = admin_state
    if expired:
        monkeypatch.setattr(organisation_service, "INVITATION_LIFETIME", timedelta(seconds=-1))
    args = args_for(state, [state.people[state.unverified]], apply=True)
    await tool._run(args)
    invite_id = UUID(json.loads(capsys.readouterr().out)["targets"][0]["invite_id"])
    engine = create_async_engine(state.settings.database_url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            if not expired:
                message = await resolve_organisation_invitation_message(
                    db,
                    state.settings,
                    Job(
                        kind=ORGANISATION_INVITATION_JOB,
                        tenant_id=state.tenant,
                        payload={"invite_id": str(invite_id)},
                    ),
                    provider_key="fictional-mail-key",
                )
                assert message.to == state.people[state.unverified]
                assert str(invite_id) in message.variables["action_link"]
                assert "verify this email address to join" in render_email(message).text
            await join_at_sign_in_best_effort(db, state.unverified, settings=state.settings)
            assert await db.get(Membership, (state.tenant, state.unverified)) is None
            person = await db.get(Person, state.unverified)
            person.email_verified_at = datetime.now(UTC)
            await db.flush()
            await join_at_sign_in_best_effort(db, state.unverified, settings=state.settings)
        with Session(state.harness.engine) as db:
            member = db.get(Membership, (state.tenant, state.unverified))
            invite = db.get(OrganisationInvite, invite_id)
            assert (member is None) is expired
            assert invite.status == ("pending" if expired else "accepted")
            if member is not None:
                assert member.role == "member" and member.status == "active"
            assert verify_audit_chain_sync(db, state.tenant).valid
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_remove_ends_membership_preserves_person_and_replay_never_restores(
    admin_state, capsys
):
    state = admin_state
    await tool._run(args_for(state, [state.people[state.worker]], apply=True))
    capsys.readouterr()
    args = args_for(state, [state.worker], action="remove-members", apply=True)
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["after"]["ended"]
    before = counts(state)
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["status"] == "replayed"
    assert counts(state) == before
    with Session(state.harness.engine) as db:
        assert db.get(Person, state.worker).status == "active"
        member = db.get(Membership, (state.tenant, state.worker))
        assert member.status == "inactive" and member.ended_at is not None
        assert verify_audit_chain_sync(db, state.tenant).valid


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "action",
        "approver",
        "actor_person_id",
        "target",
        "operator_reference",
        "issue_reference",
        "run_reference",
    ],
)
async def test_command_id_cannot_be_reused_with_different_attribution_or_intent(
    admin_state, capsys, field
):
    state = admin_state
    args = args_for(state, [state.people[state.worker]], apply=True)
    await tool._run(args)
    capsys.readouterr()
    setattr(
        args,
        field,
        "remove-members"
        if field == "action"
        else [state.people[state.second]]
        if field == "target"
        else uuid4()
        if field == "run_reference"
        else state.second
        if field == "actor_person_id"
        else "changed",
    )
    before = counts(state)
    with pytest.raises(OrganisationCommandError, match="different intent or attribution"):
        await tool._run(args)
    assert counts(state) == before
    assert capsys.readouterr().out == ""


@pytest.mark.asyncio
async def test_batch_failure_rolls_back_canonical_effects_and_audit(
    admin_state, monkeypatch, capsys
):
    state = admin_state
    original = OrganisationService.request_member

    async def fail_after_invite(self, *args, **kwargs):
        await original(self, *args, **kwargs)
        raise OrganisationCommandError("fictional failure after invite and mail")

    monkeypatch.setattr(OrganisationService, "request_member", fail_after_invite)
    before = counts(state)
    with pytest.raises(OrganisationCommandError):
        await tool._run(
            args_for(state, [state.people[state.worker], "rollback@example.test"], apply=True)
        )
    assert counts(state) == before
    assert capsys.readouterr().out == ""
    with Session(state.harness.engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(OutboxEvent)
                .where(OutboxEvent.tenant_id == state.tenant)
            )
            == 0
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", ["owner", "snapshot", "protected"])
async def test_owner_protected_tenant_and_missing_snapshot_are_refused(admin_state, guard):
    state = admin_state
    args = args_for(
        state,
        [state.people[state.owner] if guard == "owner" else state.people[state.worker]],
        apply=True,
    )
    if guard == "snapshot":
        args.snapshot_reference = None
    elif guard == "protected":
        args.tenant_id = state.operations
    before = counts(state)
    with pytest.raises(OrganisationCommandError):
        await tool._run(args)
    assert counts(state) == before


@pytest.mark.asyncio
async def test_auto_join_policy_is_not_available_to_human_member_commands(admin_state):
    state = admin_state
    engine = create_async_engine(state.settings.database_url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            service = OrganisationService(
                db, operations_tenant_id=state.operations, public_learner_tenant_id=state.public
            )
            with pytest.raises(AuthorizationDenied, match="operator"):
                await service.request_member(
                    state.tenant,
                    "nobody@example.test",
                    "member",
                    uuid4(),
                    actor_person_id=state.owner,
                    operator_auto_join=True,
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_deletion_uses_app_erasure_job_and_preserves_usage_and_history(admin_state, capsys):
    state = admin_state
    with Session(state.harness.engine) as db, db.begin():
        submission = seed_call(
            db, state.tenant, state.owner, created_at=datetime.now(UTC) - timedelta(days=2)
        )
        link = db.get(ConversationGuestSubmission, (state.tenant, submission))
        recording_id, usage_id = link.recording_id, link.usage_id
        usage = db.get(ConversationAcquisitionUsage, usage_id)
        usage_snapshot = {
            column.name: getattr(usage, column.name) for column in usage.__table__.columns
        }
    args = args_for(state, [recording_id], action="delete-recordings")
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["after"] == {
        "state": "deleting",
        "generation": 2,
    }
    with Session(state.harness.engine) as db:
        assert db.get(ConversationRecording, recording_id).state == "ready"
    args.apply, args.snapshot_reference = True, "snapshot-fixture"
    await tool._run(args)
    capsys.readouterr()
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["status"] == "replayed"
    with Session(state.harness.engine) as db:
        recording = db.get(ConversationRecording, recording_id)
        assert recording.state == "deleting" and recording.generation == 2
        job = db.scalar(select(Job).where(Job.tenant_id == state.tenant, Job.kind == DELETE_JOB))
        assert job.payload == {"recording_id": str(recording_id), "generation": 2}
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.tenant_id == state.tenant, Job.kind == DELETE_JOB)
            )
            == 1
        )
        usage = db.get(ConversationAcquisitionUsage, usage_id)
        assert {
            column.name: getattr(usage, column.name) for column in usage.__table__.columns
        } == usage_snapshot
        assert db.get(ConversationGuestSubmission, (state.tenant, submission)) is not None
        assert verify_audit_chain_sync(db, state.tenant).valid
    await tool._run(
        args_for(state, [recording_id, uuid4()], action="delete-recordings", apply=True)
    )
    assert [r["status"] for r in json.loads(capsys.readouterr().out)["targets"]] == [
        "already_deleted",
        "already_absent",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["revoked", "expired", "wrong_tenant"])
async def test_operator_invite_mail_denies_unavailable_invites(
    admin_state, capsys, monkeypatch, denial
):
    state = admin_state
    if denial == "expired":
        monkeypatch.setattr(organisation_service, "INVITATION_LIFETIME", timedelta(seconds=-1))
    await tool._run(args_for(state, ["denied@example.test"], apply=True))
    invite_id = UUID(json.loads(capsys.readouterr().out)["targets"][0]["invite_id"])
    engine = create_async_engine(state.settings.database_url)
    try:
        async with AsyncSession(engine) as db, db.begin():
            if denial == "revoked":
                await OrganisationService(
                    db, operations_tenant_id=state.operations, public_learner_tenant_id=state.public
                ).revoke_invite(state.tenant, invite_id, uuid4(), actor_person_id=state.owner)
            with pytest.raises(PermanentProviderError):
                await resolve_organisation_invitation_message(
                    db,
                    state.settings,
                    Job(
                        kind=ORGANISATION_INVITATION_JOB,
                        tenant_id=state.public if denial == "wrong_tenant" else state.tenant,
                        payload={"invite_id": str(invite_id)},
                    ),
                    provider_key="fictional-mail-key",
                )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_wrong_tenant_deletion_rolls_back_prior_app_deletion(admin_state, capsys):
    state = admin_state
    with Session(state.harness.engine) as db, db.begin():
        db.add(Membership(tenant_id=state.public, person_id=state.owner, role="learner"))
        db.flush()
        targets = []
        for tenant in (state.tenant, state.public):
            submission = seed_call(db, tenant, state.owner, created_at=datetime.now(UTC))
            targets.append(db.get(ConversationGuestSubmission, (tenant, submission)).recording_id)
    with pytest.raises(OrganisationCommandError, match="tenant differs"):
        await tool._run(args_for(state, targets, action="delete-recordings", apply=True))
    assert capsys.readouterr().out == ""
    with Session(state.harness.engine) as db:
        assert all(db.get(ConversationRecording, key).state == "ready" for key in targets)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Job)
                .where(Job.tenant_id == state.tenant, Job.kind == DELETE_JOB)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_existing_admin_is_preserved_without_new_effects(admin_state, capsys):
    state = admin_state
    with Session(state.harness.engine) as db, db.begin():
        db.add(Membership(tenant_id=state.tenant, person_id=state.worker, role="admin"))
    before = counts(state)
    await tool._run(args_for(state, [state.people[state.worker]], apply=True))
    assert json.loads(capsys.readouterr().out)["targets"][0]["status"] == "already_member"
    assert counts(state) == before


@pytest.mark.asyncio
async def test_exact_personal_recording_can_be_deleted_without_org_membership_mutation(
    admin_state, capsys
):
    state = admin_state
    with Session(state.harness.engine) as db, db.begin():
        db.add(Membership(tenant_id=state.public, person_id=state.owner, role="learner"))
        db.flush()
        submission = seed_call(db, state.public, state.owner, created_at=datetime.now(UTC))
        recording_id = db.get(ConversationGuestSubmission, (state.public, submission)).recording_id
    args = args_for(state, [recording_id], action="delete-recordings", apply=True)
    args.tenant_id = state.public
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["after"]["state"] == "deleting"
    with Session(state.harness.engine) as db:
        assert db.get(Membership, (state.public, state.owner)).role == "learner"
        assert verify_audit_chain_sync(db, state.public).valid


@pytest.mark.asyncio
async def test_reissuing_expired_operator_invite_supersedes_and_audits_expiry(
    admin_state, capsys, monkeypatch
):
    state = admin_state
    with monkeypatch.context() as patched:
        patched.setattr(organisation_service, "INVITATION_LIFETIME", timedelta(seconds=-1))
        await tool._run(args_for(state, ["expired@example.test"], apply=True))
    first = UUID(json.loads(capsys.readouterr().out)["targets"][0]["invite_id"])
    await tool._run(args_for(state, ["expired@example.test"], apply=True))
    second = UUID(json.loads(capsys.readouterr().out)["targets"][0]["invite_id"])
    assert first != second
    with Session(state.harness.engine) as db:
        assert db.get(OrganisationInvite, first).status == "revoked"
        assert db.get(OrganisationInvite, second).status == "pending"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.tenant_id == state.tenant,
                    AuditEvent.action == "organisation.invite_expired",
                )
            )
            == 1
        )
        assert verify_audit_chain_sync(db, state.tenant).valid


@pytest.mark.asyncio
async def test_post_commit_receipt_failure_can_be_replayed_without_duplicate_effects(
    admin_state, capsys, monkeypatch
):
    state = admin_state
    args = args_for(state, [state.people[state.worker]], apply=True)

    def broken_output(*_args, **_kwargs):
        raise OSError("fictional output stream failure")

    with monkeypatch.context() as patched:
        patched.setattr(tool, "print", broken_output, raising=False)
        with pytest.raises(tool.ResultDeliveryError):
            await tool._run(args)
    with Session(state.harness.engine) as db:
        assert db.get(Membership, (state.tenant, state.worker)).status == "active"
    committed = counts(state)
    await tool._run(args)
    assert json.loads(capsys.readouterr().out)["targets"][0]["status"] == "replayed"
    assert counts(state) == committed
