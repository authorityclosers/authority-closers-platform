from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ac_platform.enrollment.models import (
    CommandIdempotency,
    CommandStatus,
    Enrollment,
    EnrollmentProvenance,
    EnrollmentSource,
    Entitlement,
)
from ac_platform.enrollment.services import (
    CONTROLLED_GAP_AGE_ELIGIBILITY,
    ActorSubjectMismatchError,
    AsyncEnrollmentApplication,
    CommandInProgressError,
    CrossSubjectEnrollmentError,
    CrossTenantEnrollmentError,
    DuplicateEnrollmentError,
    EligibilityPolicyDeniedError,
    EligibilityPolicyInput,
    EnrollmentCommandService,
    EnrollmentPolicyInput,
    FreeEnrollmentCommand,
    IdempotencyConflictError,
    IdempotencyStateError,
    InMemoryEnrollmentRepository,
    InMemoryEnrollmentUnitOfWork,
    InMemoryOutboxIntentPort,
    ManualEnrollmentGrantCommand,
    ManualGrantAuthorizationDeniedError,
    ManualGrantPolicyInput,
    MembershipPolicyInput,
    ProgramVersionPolicyDeniedError,
    ProgramVersionPolicyInput,
    UniqueConstraintViolation,
    _free_request_payload,
    _request_digest,
)
from ac_platform.kernel.authz import ActorContext


class UowFactory:
    def __init__(self) -> None:
        self.store = InMemoryEnrollmentRepository()
        self.outbox = InMemoryOutboxIntentPort()
        self.calls: list[InMemoryEnrollmentUnitOfWork] = []

    def __call__(self) -> InMemoryEnrollmentUnitOfWork:
        transaction = InMemoryEnrollmentUnitOfWork(self.store, self.outbox)
        self.calls.append(transaction)
        return transaction


def free_policy(
    *,
    subject_person_id,
    tenant_id,
    program_version_id,
    age_gate_passed: bool | None = True,
    eligibility_passed: bool | None = True,
    prerequisites_satisfied: bool | None = True,
    membership_person_id=None,
    membership_tenant_id=None,
    program_version_tenant_id=None,
    program_id=None,
) -> EnrollmentPolicyInput:
    return EnrollmentPolicyInput(
        membership=MembershipPolicyInput(
            person_id=membership_person_id or subject_person_id,
            tenant_id=membership_tenant_id or tenant_id,
            active=True,
            tenant_active=True,
            role="learner",
        ),
        program_version=ProgramVersionPolicyInput(
            id=program_version_id,
            tenant_id=program_version_tenant_id or tenant_id,
            published=True,
            immutable=True,
            program_id=program_id or uuid4(),
        ),
        eligibility=EligibilityPolicyInput(
            person_id=subject_person_id,
            age_gate_passed=age_gate_passed,
            eligibility_passed=eligibility_passed,
            prerequisites_satisfied=prerequisites_satisfied,
        ),
    )


def free_command(
    *,
    actor_person_id,
    subject_person_id,
    tenant_id,
    program_version_id,
    idempotency_key="enrollment-1",
    source=EnrollmentSource.FREE_SELF.value,
) -> FreeEnrollmentCommand:
    return FreeEnrollmentCommand(
        actor_person_id=actor_person_id,
        subject_person_id=subject_person_id,
        tenant_id=tenant_id,
        program_version_id=program_version_id,
        idempotency_key=idempotency_key,
        source=source,
    )


def set_free_authority(
    factory: UowFactory,
    command: FreeEnrollmentCommand,
    policy: EnrollmentPolicyInput | None = None,
) -> EnrollmentPolicyInput:
    canonical_policy = policy or free_policy(
        subject_person_id=command.subject_person_id,
        tenant_id=command.tenant_id,
        program_version_id=command.program_version_id,
    )
    factory.store.set_free_enrollment_policy(
        tenant_id=command.tenant_id,
        person_id=command.subject_person_id,
        program_version_id=command.program_version_id,
        policy=canonical_policy,
    )
    return canonical_policy


def test_policy_input_records_unresolved_age_eligibility_gap() -> None:
    policy = free_policy(subject_person_id=uuid4(), tenant_id=uuid4(), program_version_id=uuid4())

    assert policy.eligibility is not None
    assert CONTROLLED_GAP_AGE_ELIGIBILITY in policy.eligibility.controlled_gaps


def test_async_enrollment_boundary_rejects_body_impersonation_and_cross_tenant_authority() -> None:
    actor_id, subject_id, tenant_id, other_tenant_id, version_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    actor = ActorContext(
        person_id=actor_id,
        session_id=uuid4(),
        tenant_id=tenant_id,
    )

    with pytest.raises(ActorSubjectMismatchError):
        AsyncEnrollmentApplication._canonical_free_command(
            free_command(
                actor_person_id=subject_id,
                subject_person_id=subject_id,
                tenant_id=tenant_id,
                program_version_id=version_id,
            ),
            actor,
        )
    with pytest.raises(CrossTenantEnrollmentError):
        AsyncEnrollmentApplication._canonical_free_command(
            free_command(
                actor_person_id=actor_id,
                subject_person_id=actor_id,
                tenant_id=other_tenant_id,
                program_version_id=version_id,
            ),
            actor,
        )

    manual = ManualEnrollmentGrantCommand(
        actor_person_id=actor_id,
        subject_person_id=subject_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="manual-boundary",
        reason="support-approved grant",
        policy=free_policy(
            subject_person_id=subject_id,
            tenant_id=tenant_id,
            program_version_id=version_id,
        ),
    )
    with pytest.raises(ManualGrantAuthorizationDeniedError):
        AsyncEnrollmentApplication._canonical_manual_command(manual, actor)

    grant_actor = ActorContext(
        person_id=actor_id,
        session_id=actor.session_id,
        tenant_id=tenant_id,
        permissions=frozenset({"enrollment_grant"}),
    )
    with pytest.raises(ManualGrantAuthorizationDeniedError):
        AsyncEnrollmentApplication._canonical_manual_command(
            replace(manual, actor_person_id=subject_id),
            grant_actor,
        )


async def test_free_enrollment_creates_audited_entitlement_and_one_outbox_intent() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory, clock=lambda: datetime(2026, 8, 30, tzinfo=UTC))
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()

    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command)

    result = await service.enroll_free(command)

    assert result.created is True
    assert result.replayed is False
    assert len(factory.store.enrollments) == 1
    assert len(factory.store.entitlements) == 1
    assert len(factory.store.provenance) == 1
    assert len(factory.store.commands) == 1
    assert len(factory.outbox.intents) == 1
    assert factory.outbox.intents[0].name == "enrollment.welcome.requested.v1"
    assert factory.outbox.intents[0].tenant_id == tenant_id
    assert factory.calls[0].events[0].name == "audit.enrollment.created.v1"
    provenance = next(iter(factory.store.provenance.values()))
    assert provenance.source == EnrollmentSource.FREE_SELF.value
    assert provenance.actor_person_id == person_id
    assert provenance.person_id == person_id
    assert provenance.controlled_gaps == [CONTROLLED_GAP_AGE_ELIGIBILITY]


async def test_same_command_replays_without_duplicate_state_or_outbox() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command)

    first = await service.enroll_free(command)
    second = await service.enroll_free(command)

    assert second.replayed is True
    assert second.created is False
    assert second == first.__class__(
        enrollment_id=first.enrollment_id,
        entitlement_id=first.entitlement_id,
        provenance_id=first.provenance_id,
        command_idempotency_id=first.command_idempotency_id,
        created=False,
        replayed=True,
    )
    assert len(factory.store.enrollments) == 1
    assert len(factory.store.entitlements) == 1
    assert len(factory.store.provenance) == 1
    assert len(factory.outbox.intents) == 1
    assert len(factory.calls[1].events) == 0


async def test_replay_revalidates_every_bound_result_identifier() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command)
    await service.enroll_free(command)
    stored_command = next(iter(factory.store.commands.values()))
    stored_command.result_entitlement_id = uuid4()

    with pytest.raises(IdempotencyStateError):
        await service.enroll_free(command)


async def test_same_key_with_different_request_is_rejected() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id = uuid4(), uuid4()
    first = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=uuid4(),
        idempotency_key="same-key",
    )
    second = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=uuid4(),
        idempotency_key="same-key",
    )
    set_free_authority(factory, first)
    set_free_authority(factory, second)

    await service.enroll_free(first)
    with pytest.raises(IdempotencyConflictError):
        await service.enroll_free(second)

    assert len(factory.store.enrollments) == 1
    assert len(factory.outbox.intents) == 1


async def test_different_key_cannot_duplicate_the_pinned_enrollment() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    first = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="first-key",
    )
    second = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="second-key",
    )
    set_free_authority(factory, first)

    await service.enroll_free(first)
    with pytest.raises(DuplicateEnrollmentError):
        await service.enroll_free(second)

    assert len(factory.store.commands) == 1
    assert len(factory.outbox.intents) == 1


async def test_pending_idempotency_claim_is_a_concurrency_intent_denial() -> None:
    factory = UowFactory()
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="pending-key",
    )
    policy = set_free_authority(factory, command)
    assert policy.program_version.program_id is not None
    pending = CommandIdempotency(
        id=uuid4(),
        tenant_id=tenant_id,
        actor_person_id=person_id,
        subject_person_id=person_id,
        program_version_id=version_id,
        program_id=policy.program_version.program_id,
        program_scope="tenant",
        program_tenant_id=tenant_id,
        program_owner_key=tenant_id,
        operation="enroll_free",
        idempotency_key="pending-key",
        request_digest=_request_digest(_free_request_payload(command)),
        status=CommandStatus.PENDING.value,
    )
    factory.store.commands[(tenant_id, person_id, "enroll_free", "pending-key")] = pending
    service = EnrollmentCommandService(factory)

    with pytest.raises(CommandInProgressError):
        await service.enroll_free(command)


async def test_actor_cannot_enroll_another_subject() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    actor_id, subject_id, tenant_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()

    with pytest.raises(ActorSubjectMismatchError):
        await service.enroll_free(
            free_command(
                actor_person_id=actor_id,
                subject_person_id=subject_id,
                tenant_id=tenant_id,
                program_version_id=version_id,
            )
        )

    assert not factory.store.enrollments
    assert not factory.outbox.intents


async def test_cross_tenant_program_version_input_is_denied() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id, other_tenant_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    policy = free_policy(
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        program_version_tenant_id=other_tenant_id,
    )
    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command, policy)

    with pytest.raises(CrossTenantEnrollmentError):
        await service.enroll_free(command)


async def test_cross_subject_membership_and_missing_eligibility_are_denied() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    actor_id, other_subject_id, tenant_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    policy = free_policy(
        subject_person_id=actor_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        membership_person_id=other_subject_id,
    )
    command = free_command(
        actor_person_id=actor_id,
        subject_person_id=actor_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command, policy)
    with pytest.raises(CrossSubjectEnrollmentError):
        await service.enroll_free(command)
    missing_eligibility = free_policy(
        subject_person_id=actor_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        age_gate_passed=None,
    )
    missing_command = free_command(
        actor_person_id=actor_id,
        subject_person_id=actor_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="missing-eligibility",
    )
    set_free_authority(factory, missing_command, missing_eligibility)
    with pytest.raises(EligibilityPolicyDeniedError):
        await service.enroll_free(missing_command)


async def test_unpublished_program_version_is_denied() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    policy = free_policy(
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    policy = EnrollmentPolicyInput(
        membership=policy.membership,
        program_version=ProgramVersionPolicyInput(
            id=version_id,
            tenant_id=tenant_id,
            published=False,
            immutable=True,
        ),
        eligibility=policy.eligibility,
    )
    command = free_command(
        actor_person_id=person_id,
        subject_person_id=person_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    set_free_authority(factory, command, policy)

    with pytest.raises(ProgramVersionPolicyDeniedError):
        await service.enroll_free(command)


async def test_manual_grant_is_a_named_seam_with_reason_and_provenance() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    actor_id, subject_id, tenant_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    base = free_policy(
        subject_person_id=subject_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    policy = EnrollmentPolicyInput(
        membership=base.membership,
        program_version=base.program_version,
        manual_grant=ManualGrantPolicyInput(
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            active=True,
            authorized=True,
            role="admin",
        ),
    )
    command = ManualEnrollmentGrantCommand(
        actor_person_id=actor_id,
        subject_person_id=subject_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="manual-1",
        reason="Support-approved accessibility accommodation",
        policy=policy,
    )

    result = await service.grant_manual(command)

    assert result.created is True
    provenance = next(iter(factory.store.provenance.values()))
    assert provenance.source == EnrollmentSource.MANUAL_GRANT.value
    assert provenance.actor_person_id == actor_id
    assert provenance.person_id == subject_id
    assert provenance.reason == command.reason


async def test_manual_grant_without_named_authorization_is_denied() -> None:
    factory = UowFactory()
    service = EnrollmentCommandService(factory)
    actor_id, subject_id, tenant_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
    base = free_policy(
        subject_person_id=subject_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
    )
    policy = EnrollmentPolicyInput(
        membership=base.membership,
        program_version=base.program_version,
        manual_grant=ManualGrantPolicyInput(
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            active=True,
            authorized=False,
            role="admin",
        ),
    )

    command = ManualEnrollmentGrantCommand(
        actor_person_id=actor_id,
        subject_person_id=subject_id,
        tenant_id=tenant_id,
        program_version_id=version_id,
        idempotency_key="manual-denied",
        reason="Attempted grant",
        policy=policy,
    )
    with pytest.raises(ManualGrantAuthorizationDeniedError):
        await service.grant_manual(command)

    assert not factory.store.enrollments


async def test_in_memory_repository_enforces_the_same_enrollment_uniqueness_intent() -> None:
    repository = InMemoryEnrollmentRepository()
    person_id, tenant_id, version_id = uuid4(), uuid4(), uuid4()
    first = Enrollment(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        program_version_id=version_id,
        source="free_self",
    )
    second = Enrollment(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        program_version_id=version_id,
        source="free_self",
    )
    provenance = EnrollmentProvenance(
        id=uuid4(),
        tenant_id=tenant_id,
        enrollment_id=first.id,
        person_id=person_id,
        actor_person_id=person_id,
        program_version_id=version_id,
        command_idempotency_id=uuid4(),
        source="free_self",
    )
    entitlement = Entitlement(
        id=uuid4(),
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=first.id,
        provenance_id=provenance.id,
        program_version_id=version_id,
    )

    await repository.save_records(first, provenance, entitlement)
    with pytest.raises(UniqueConstraintViolation):
        await repository.save_records(second, provenance, entitlement)
