from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from ac_platform.certificates import (
    COURSE_COMPLETION_CERTIFICATE_TYPE,
    ActivityCompletion,
    CertificateAuthorizationRequiredError,
    CertificateEventType,
    CertificateScopeMismatchError,
    CompletionIncompleteError,
    CourseCompletionCertificateService,
    InMemoryCertificateStore,
    ModuleDefinition,
    PinnedCourseVersion,
    evaluate_course_completion,
)
from ac_platform.certificates.services import (
    ActiveEntitlementSnapshot,
    CertificateAuthorityRequiredError,
    CertificateSnapshotIntegrityError,
    ImmutableProgramVersionSnapshot,
    InMemoryCertificateAuthority,
)


def _ids() -> tuple[UUID, UUID, UUID, UUID, UUID, UUID, UUID]:
    return tuple(uuid4() for _ in range(7))  # type: ignore[return-value]


def _pinned_course(
    *,
    tenant_id: UUID,
    person_id: UUID,
    first_completed: bool = True,
    second_completed: bool = True,
    enrollment_id: UUID | None = None,
    program_id: UUID | None = None,
    program_version_id: UUID | None = None,
    program_scope: str = "tenant",
    program_tenant_id: UUID | None = None,
) -> PinnedCourseVersion:
    (
        generated_program_id,
        generated_version_id,
        first_module_id,
        second_module_id,
        first_id,
        second_id,
        optional_id,
    ) = _ids()
    return PinnedCourseVersion(
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id or uuid4(),
        program_id=program_id or generated_program_id,
        program_version_id=program_version_id or generated_version_id,
        program_scope=program_scope,
        program_tenant_id=program_tenant_id,
        modules=(
            ModuleDefinition(
                module_id=second_module_id,
                prerequisite_module_ids=(first_module_id,),
            ),
            ModuleDefinition(module_id=first_module_id),
        ),
        activities=(
            ActivityCompletion(
                activity_id=optional_id,
                module_id=second_module_id,
                required=False,
                completed=False,
            ),
            ActivityCompletion(
                activity_id=second_id,
                module_id=second_module_id,
                completed=second_completed,
            ),
            ActivityCompletion(
                activity_id=first_id,
                module_id=first_module_id,
                completed=first_completed,
            ),
        ),
    )


def _authority_for(
    progress: PinnedCourseVersion,
    *,
    permissions: tuple[tuple[UUID, UUID, str], ...] = (),
) -> InMemoryCertificateAuthority:
    assert progress.enrollment_id is not None
    assert progress.program_owner_key is not None
    entitlement = ActiveEntitlementSnapshot(
        tenant_id=progress.tenant_id,
        person_id=progress.person_id,
        enrollment_id=progress.enrollment_id,
        program_id=progress.program_id,
        program_version_id=progress.program_version_id,
        program_scope=progress.program_scope,
        program_tenant_id=progress.program_tenant_id,
        program_owner_key=progress.program_owner_key,
    )
    version = ImmutableProgramVersionSnapshot(
        program_id=progress.program_id,
        program_version_id=progress.program_version_id,
        program_scope=progress.program_scope,
        program_tenant_id=progress.program_tenant_id,
        program_owner_key=progress.program_owner_key,
        published=True,
        immutable=True,
    )
    return InMemoryCertificateAuthority(
        entitlement=entitlement,
        version=version,
        progress=progress,
        permissions=permissions,
    )


def test_completion_is_deterministic_and_persists_the_required_denominator() -> None:
    tenant_id, person_id, *_ = _ids()
    pinned = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    captured_at = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)

    first = evaluate_course_completion(pinned, now=captured_at)
    second = evaluate_course_completion(
        PinnedCourseVersion(
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=pinned.enrollment_id,
            program_id=pinned.program_id,
            program_version_id=pinned.program_version_id,
            program_scope=pinned.program_scope,
            program_tenant_id=pinned.program_tenant_id,
            program_owner_key=pinned.program_owner_key,
            modules=tuple(reversed(pinned.modules)),
            activities=tuple(reversed(pinned.activities)),
        ),
        now=captured_at,
    )

    assert first.is_complete is True
    assert first.denominator == 2
    assert first.completed_activity_count == 2
    assert first.canonical_payload() == second.canonical_payload()
    assert first.snapshot_hash == second.snapshot_hash
    assert [result.is_complete for result in first.module_results] == [True, True]


def test_incomplete_course_cannot_issue_a_course_completion_certificate() -> None:
    tenant_id, person_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(
        tenant_id=tenant_id,
        person_id=person_id,
        first_completed=True,
        second_completed=False,
    )
    incomplete = evaluate_course_completion(
        progress,
        now=captured_at,
    )
    store = InMemoryCertificateStore()
    service = CourseCompletionCertificateService(store, authority=_authority_for(progress))

    with pytest.raises(CompletionIncompleteError):
        service.issue(incomplete, now=captured_at)

    assert store.snapshots == {}
    assert store.certificates == {}
    assert store.events == {}


def test_issue_is_idempotent_for_the_same_person_and_pinned_version() -> None:
    tenant_id, person_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    completion = evaluate_course_completion(progress, now=captured_at)
    store = InMemoryCertificateStore()
    with pytest.raises(CertificateAuthorityRequiredError):
        CourseCompletionCertificateService(store).issue(completion, now=captured_at)

    service = CourseCompletionCertificateService(store, authority=_authority_for(progress))
    fabricated_progress = _pinned_course(
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=progress.enrollment_id,
        program_id=progress.program_id,
        program_version_id=progress.program_version_id,
    )
    fabricated = evaluate_course_completion(fabricated_progress, now=captured_at)
    with pytest.raises(CertificateSnapshotIntegrityError):
        service.issue(fabricated, idempotency_key="fabricated", now=captured_at)

    first = service.issue(completion, idempotency_key="completion-1", now=captured_at)
    replay = service.issue(completion, idempotency_key="completion-1", now=captured_at)

    assert first.created is True
    assert replay.created is False
    assert replay.certificate.id == first.certificate.id
    assert replay.event.id == first.event.id
    assert replay.certificate.certificate_type == COURSE_COMPLETION_CERTIFICATE_TYPE
    assert len(store.snapshots) == 1
    assert len(store.certificates) == 1
    assert len(store.events) == 1


def test_certificate_event_digest_is_lowercase_content_bound_at_model_and_store_boundaries() -> (
    None
):
    tenant_id, person_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    completion = evaluate_course_completion(progress, now=captured_at)
    store = InMemoryCertificateStore()
    service = CourseCompletionCertificateService(store, authority=_authority_for(progress))
    issued = service.issue(completion, now=captured_at)

    with pytest.raises(CertificateSnapshotIntegrityError, match="lowercase SHA-256"):
        replace(issued.event, request_digest="Z" * 64)
    with pytest.raises(CertificateSnapshotIntegrityError, match="does not match"):
        replace(issued.event, request_digest="0" * 64)

    tampered = replace(
        issued.event,
        id=uuid4(),
        idempotency_key="tampered-event",
        request_digest=None,
    )
    object.__setattr__(tampered, "request_digest", "0" * 64)
    with pytest.raises(CertificateSnapshotIntegrityError, match="does not match"):
        store.append_event(tampered)


def test_read_rejects_cross_person_and_cross_tenant_access() -> None:
    tenant_id, person_id, other_person_id, other_tenant_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    completion = evaluate_course_completion(progress, now=captured_at)
    service = CourseCompletionCertificateService(
        InMemoryCertificateStore(), authority=_authority_for(progress)
    )
    issued = service.issue(completion, now=captured_at)

    with pytest.raises(CertificateScopeMismatchError):
        service.read(
            issued.certificate.id,
            actor_person_id=other_person_id,
            tenant_id=tenant_id,
        )
    with pytest.raises(CertificateScopeMismatchError):
        service.read(
            issued.certificate.id,
            actor_person_id=person_id,
            tenant_id=other_tenant_id,
        )


def test_correction_and_revocation_append_events_without_rewriting_the_original() -> None:
    tenant_id, person_id, actor_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    completion = evaluate_course_completion(progress, now=captured_at)
    authority = _authority_for(
        progress,
        permissions=(
            (actor_id, tenant_id, "certificate_correct"),
            (actor_id, tenant_id, "certificate_revoke"),
        ),
    )
    store = InMemoryCertificateStore()
    service = CourseCompletionCertificateService(store, authority=authority)
    issued = service.issue(completion, now=captured_at)
    corrected = replace(
        completion,
        id=uuid4(),
        captured_at=datetime(2026, 8, 30, 13, 0, tzinfo=UTC),
        supersedes_snapshot_id=completion.id,
        snapshot_hash=None,
    )

    correction = service.correct(
        issued.certificate.id,
        corrected,
        actor_person_id=actor_id,
        tenant_id=tenant_id,
        subject_person_id=person_id,
        reason="The completion record was re-evaluated from the pinned version.",
        provenance={"source": "admin-correction", "case_id": "case-1"},
    )
    revocation = service.revoke(
        issued.certificate.id,
        actor_person_id=actor_id,
        tenant_id=tenant_id,
        subject_person_id=person_id,
        reason="The issued record requires review.",
        provenance={"source": "admin-review", "case_id": "case-2"},
    )
    view = service.read(
        issued.certificate.id,
        actor_person_id=person_id,
        tenant_id=tenant_id,
    )

    assert issued.certificate.original_completion_snapshot_id == completion.id
    assert store.snapshots[completion.id] == completion
    assert correction.supersedes_event_id == issued.event.id
    assert revocation.supersedes_event_id == correction.id
    assert view.certificate.original_completion_snapshot_id == completion.id
    assert view.current_event.event_type is CertificateEventType.REVOKED
    assert view.current_completion.id == corrected.id
    assert [event.event_type for event in store.list_events(issued.certificate.id)] == [
        CertificateEventType.ISSUED,
        CertificateEventType.CORRECTED,
        CertificateEventType.REVOKED,
    ]


def test_correction_rejects_caller_snapshots_outside_the_authoritative_scope() -> None:
    tenant_id, person_id, actor_id, other_person_id, other_tenant_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    completion = evaluate_course_completion(progress, now=captured_at)
    authority = _authority_for(
        progress,
        permissions=((actor_id, tenant_id, "certificate_correct"),),
    )
    store = InMemoryCertificateStore()
    service = CourseCompletionCertificateService(store, authority=authority)
    issued = service.issue(completion, now=captured_at)
    other_person_completion = evaluate_course_completion(
        _pinned_course(tenant_id=tenant_id, person_id=other_person_id),
        now=captured_at,
    )
    other_tenant_completion = evaluate_course_completion(
        _pinned_course(tenant_id=other_tenant_id, person_id=person_id),
        now=captured_at,
    )

    with pytest.raises(CertificateSnapshotIntegrityError):
        service.correct(
            issued.certificate.id,
            other_person_completion,
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            subject_person_id=person_id,
            reason="Wrong person must be rejected.",
        )
    with pytest.raises(CertificateSnapshotIntegrityError):
        service.correct(
            issued.certificate.id,
            other_tenant_completion,
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            subject_person_id=person_id,
            reason="Wrong tenant must be rejected.",
        )

    assert len(store.events) == 1
    assert len(store.snapshots) == 1


def test_changes_require_subject_exact_admin_permission_and_rechecked_progress() -> None:
    tenant_id, person_id, actor_id, *_ = _ids()
    captured_at = datetime(2026, 8, 30, tzinfo=UTC)
    progress = _pinned_course(tenant_id=tenant_id, person_id=person_id)
    authority = _authority_for(
        progress,
        permissions=((actor_id, tenant_id, "certificate_revoke"),),
    )
    store = InMemoryCertificateStore()
    service = CourseCompletionCertificateService(store, authority=authority)
    issued = service.issue(
        evaluate_course_completion(progress, now=captured_at),
        idempotency_key="authoritative-issue",
        now=captured_at,
    )

    with pytest.raises(CertificateAuthorizationRequiredError):
        service.correct(
            issued.certificate.id,
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            reason="Missing explicit subject.",
        )
    with pytest.raises(CertificateAuthorizationRequiredError):
        service.correct(
            issued.certificate.id,
            actor_person_id=person_id,
            tenant_id=tenant_id,
            subject_person_id=person_id,
            reason="Self-service cannot mutate a certificate.",
        )
    with pytest.raises(CertificateAuthorizationRequiredError):
        service.correct(
            issued.certificate.id,
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            subject_person_id=person_id,
            reason="Revocation permission is not correction permission.",
        )

    authority.permissions.add((actor_id, tenant_id, "certificate_correct"))
    authority.progress = _pinned_course(
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=progress.enrollment_id,
        program_id=progress.program_id,
        program_version_id=progress.program_version_id,
        first_completed=True,
        second_completed=False,
    )
    with pytest.raises(CompletionIncompleteError):
        service.correct(
            issued.certificate.id,
            actor_person_id=actor_id,
            tenant_id=tenant_id,
            subject_person_id=person_id,
            reason="Canonical progress is no longer complete.",
        )

    revocation = service.revoke(
        issued.certificate.id,
        actor_person_id=actor_id,
        tenant_id=tenant_id,
        subject_person_id=person_id,
        reason="Canonical progress was re-evaluated before revocation.",
        idempotency_key="authoritative-revoke",
    )
    assert revocation.provenance["authoritative_complete"] is False
