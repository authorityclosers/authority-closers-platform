"""First-use organisation principal proof in the disposable CI database."""

import asyncio
import hashlib
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import verify_audit_chain
from ac_platform.billing.ledger import BillingLedger
from ac_platform.conversation_intelligence.acquisition_processing import (
    AcquisitionProcessing,
    upload_policy,
)
from ac_platform.conversation_intelligence.acquisition_sessions import (
    AcquisitionSessions,
    MeasuredSource,
)
from ac_platform.conversation_intelligence.acquisition_source import MeasuredUpload
from ac_platform.conversation_intelligence.activation_contract import load_hosted_approval_bundle
from ac_platform.conversation_intelligence.application import ConversationConflict
from ac_platform.conversation_intelligence.authority import ConversationAuthority
from ac_platform.conversation_intelligence.contracts import IntakeIntent
from ac_platform.conversation_intelligence.guest_models import ConversationProcessingPrincipal
from ac_platform.conversation_intelligence.guest_ownership import GuestOwnership
from ac_platform.conversation_intelligence.intake import IntakePolicy
from ac_platform.conversation_intelligence.storage import PrivateLocalRecordingStorage
from ac_platform.http.conversation_intake import ConversationIntakeRuntime
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.organisations.service import OrganisationService
from tests.database.test_conversation_postgresql import postgres_harness as _postgres_harness
from tests.database.test_conversation_postgresql import run, seed
from tests.unit.conversation_intelligence.test_organisation_acquisition_policies import (
    current_payload,
)
from tests.unit.organisations.test_service import seed_paid_seats


@pytest.fixture(scope="module")
def postgres_harness():
    yield from _postgres_harness.__wrapped__()


async def setup(engine, tmp_path):
    owner, member = await seed(engine), await seed(engine)
    async with AsyncSession(engine) as db, db.begin():
        service = OrganisationService(
            db, operations_tenant_id=owner.permission_id, public_learner_tenant_id=owner.tenant_id
        )
        organisation = await service.create(
            "Fictional default organisation",
            owner.person_id,
            uuid4(),
            "self-serve-fixture",
            actor_person_id=owner.person_id,
        )
        await seed_paid_seats(db, organisation.tenant_id, owner.person_id, seats=3)
        invite = await service.request_member(
            organisation.tenant_id,
            f"worker-{member.person_id.hex}@example.test",
            "member",
            uuid4(),
            actor_person_id=owner.person_id,
            require_acceptance=True,
        )
    async with AsyncSession(engine) as db, db.begin():
        service = OrganisationService(
            db, operations_tenant_id=owner.permission_id, public_learner_tenant_id=owner.tenant_id
        )
        await service.accept_invite(
            UUID(invite["invite_id"]), uuid4(), actor_person_id=member.person_id
        )
        await db.execute(
            update(IdentitySession)
            .where(IdentitySession.id == member.session_id)
            .values(selected_tenant_id=organisation.tenant_id)
        )
        ledger = BillingLedger(db, clock=lambda: member.now, trial_enabled=False)
        account = await ledger.personal_account(
            tenant_id=organisation.tenant_id, person_id=member.person_id, create=True
        )
        await ledger.write_lot(
            account=account,
            kind="grant",
            seconds=600,
            valid_from=member.now,
            source_ref=f"test:default-organisation:{organisation.tenant_id}",
            actor_type="person",
            actor_person_id=owner.person_id,
            reason="Fictional fixture capacity",
        )
    member = replace(member, tenant_id=organisation.tenant_id)
    payload = current_payload()
    payload["issued_at_epoch"] = int(member.now.timestamp()) - 1
    bundle = load_hosted_approval_bundle(payload)
    # No exact entry for the created organisation is sealed.
    assert member.tenant_id not in bundle.acquisition_tenant_ids()
    authority = ConversationAuthority(
        lambda: bundle, environment="test", operations_tenant_id=bundle.provider_control_tenant_id
    )
    runtime = ConversationIntakeRuntime(
        policy=IntakePolicy(
            budget_scope_id=bundle.budget_scope_id,
            tenant_ids=frozenset(bundle.acquisition_tenant_ids()),
            authorization_ref=bundle.intake_authorization_ref,
            retention_ref=bundle.intake_retention_ref,
            registered_organisations=True,
        ),
        authority=authority,
        storage=PrivateLocalRecordingStorage(tmp_path / "storage"),
        scratch=PrivateLocalRecordingStorage(tmp_path / "scratch"),
    )
    return member, bundle, runtime


def measured_upload(*, source_bytes=12):
    digest = hashlib.sha256(b"fictional organisation source").hexdigest()
    return MeasuredUpload(
        MeasuredSource(uuid4(), digest, 1000, "d" * 64),
        IntakeIntent(
            source_sha256=digest,
            source_bytes=source_bytes,
            content_type="audio/wav",
            duration_ms=1000,
            purpose="internal_analysis",
        ),
    )


async def prepare(engine, member, runtime, upload):
    async with AsyncSession(engine) as db, db.begin():
        sessions = AcquisitionSessions(
            db,
            tenant_id=member.tenant_id,
            policy_revision="default-organisation-v1",
            clock=lambda: member.now,
            trial_enabled=False,
        )
        return await AcquisitionProcessing(GuestOwnership(sessions), runtime).prepare(
            upload, policy_sha256=upload_policy(runtime.policy)["policy_sha256"], actor=member.actor
        )


def test_create_invite_accept_then_two_first_uploads_create_one_principal(
    postgres_harness, tmp_path
):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            member, bundle, runtime = await setup(engine, tmp_path)
            upload = measured_upload()
            results = await asyncio.gather(
                prepare(engine, member, runtime, upload), prepare(engine, member, runtime, upload)
            )
            assert results[0] == results[1]
            processing, _ = results[0]
            policy = bundle.acquisition_policy_for(member.tenant_id, registered_organisation=True)
            assert processing.person_id == policy.processing_person_id
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationProcessingPrincipal)
                        .where(ConversationProcessingPrincipal.tenant_id == member.tenant_id)
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == member.tenant_id,
                            AuditEvent.action == "conversation.processing_principal_created",
                        )
                    )
                    == 1
                )
                assert (await verify_audit_chain(db, member.tenant_id)).valid
        finally:
            await engine.dispose()

    run(exercise())


def test_failed_first_upload_rolls_back_principal_and_audit(postgres_harness, tmp_path):
    async def exercise():
        engine = create_async_engine(postgres_harness.url)
        try:
            member, _, runtime = await setup(engine, tmp_path)
            with pytest.raises(ConversationConflict, match="recording capacity is full"):
                await prepare(engine, member, runtime, measured_upload(source_bytes=101))
            async with AsyncSession(engine) as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(ConversationProcessingPrincipal)
                        .where(ConversationProcessingPrincipal.tenant_id == member.tenant_id)
                    )
                    == 0
                )
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(AuditEvent)
                        .where(
                            AuditEvent.tenant_id == member.tenant_id,
                            AuditEvent.action == "conversation.processing_principal_created",
                        )
                    )
                    == 0
                )
                assert (await verify_audit_chain(db, member.tenant_id)).valid
        finally:
            await engine.dispose()

    run(exercise())
