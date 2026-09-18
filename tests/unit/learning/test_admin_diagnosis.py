from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ac_platform.catalog.models import (
    Activity as CatalogActivity,
)
from ac_platform.catalog.models import (
    ActivityKind,
    CatalogScope,
    Module,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.db.models import model_metadata
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.password_auth import normalize_email as normalize_registered_email
from ac_platform.kernel.authz import ActorContext
from ac_platform.learning.admin_diagnosis import (
    _normalize_lookup_query,
    _scoped_evidence,
    diagnose_learner,
    lookup_learners,
)
from ac_platform.learning.models import ActivityState, EvidenceSubmission, LearningEvidence
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityProgressSnapshot,
    InMemoryLearningStore,
    LearningAccessContext,
    MembershipResolution,
    ModuleDefinition,
    ProgramDefinition,
    ProgressProjector,
    authoritative_progress,
)
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

NOW = datetime(2026, 9, 13, 12, tzinfo=UTC)


@pytest.fixture
def database() -> Session:
    engine = create_engine("sqlite:///:memory:")
    model_metadata().create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _person(person_id, *, email: str, status: str = PersonStatus.ACTIVE.value) -> Person:
    return Person(
        id=person_id,
        email=email,
        display_name="Support-visible learner",
        status=status,
        email_verified_at=NOW,
    )


def test_lookup_email_normalization_matches_password_registration_for_unicode_input() -> None:
    raw = "\u00c9xample.User@EXAMPLE.TEST"

    assert _normalize_lookup_query(raw) == normalize_registered_email(raw)


def test_lookup_is_exact_and_excludes_other_tenant_role_and_lifecycle(
    database,
) -> None:
    tenant_id, other_tenant_id = uuid4(), uuid4()
    selected = uuid4()
    hidden_role, hidden_membership, hidden_person = uuid4(), uuid4(), uuid4()
    other_tenant = uuid4()
    database.add_all(
        [
            Tenant(id=tenant_id, slug=f"selected-{tenant_id.hex[:10]}", name="Selected"),
            Tenant(
                id=other_tenant_id,
                slug=f"other-{other_tenant_id.hex[:10]}",
                name="Other",
                status=TenantStatus.ACTIVE.value,
            ),
            _person(selected, email="selected@example.test"),
            _person(hidden_role, email="support@example.test"),
            _person(hidden_membership, email="inactive@example.test"),
            _person(
                hidden_person, email="suspended@example.test", status=PersonStatus.SUSPENDED.value
            ),
            _person(other_tenant, email="other@example.test"),
            Membership(tenant_id=tenant_id, person_id=selected, role="learner"),
            Membership(tenant_id=tenant_id, person_id=hidden_role, role="support"),
            Membership(
                tenant_id=tenant_id,
                person_id=hidden_membership,
                role="learner",
                status=MembershipStatus.INACTIVE.value,
                ended_at=NOW,
            ),
            Membership(tenant_id=tenant_id, person_id=hidden_person, role="learner"),
            Membership(tenant_id=other_tenant_id, person_id=other_tenant, role="learner"),
            CohorvaPublicProfile(
                person_id=selected,
                username="selected_learner",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
            CohorvaPublicProfile(
                person_id=hidden_role,
                username="tutor_person",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
            CohorvaPublicProfile(
                person_id=hidden_membership,
                username="inactive_learner",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
            CohorvaPublicProfile(
                person_id=hidden_person,
                username="suspended_learner",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
            CohorvaPublicProfile(
                person_id=other_tenant,
                username="other_learner",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
        ]
    )
    database.commit()

    result = lookup_learners(database, tenant_id=tenant_id, query=" SELECTED_LEARNER ")
    assert [candidate.person_id for candidate in result.candidates] == [selected]
    assert result.candidates[0].username == "selected_learner"
    assert result.candidates[0].masked_email == "s***@example.test"
    for unavailable in (
        "tutor_person",
        "inactive_learner",
        "suspended_learner",
        "other_learner",
    ):
        assert lookup_learners(database, tenant_id=tenant_id, query=unavailable).candidates == ()


def test_diagnosis_keeps_missing_entitlement_enrollment_visible(database) -> None:
    tenant_id, person_id = uuid4(), uuid4()
    program_id, version_id, module_id, activity_id, enrollment_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    database.add_all(
        [
            Tenant(id=tenant_id, slug=f"diagnosis-{tenant_id.hex[:10]}", name="Diagnosis"),
            _person(person_id, email="diagnosis@example.test"),
            Membership(tenant_id=tenant_id, person_id=person_id, role="learner"),
            CohorvaPublicProfile(
                person_id=person_id,
                username="diagnosis_learner",
                claim_source="legacy_0027",
                legacy_profile_count=1,
            ),
            Program(
                id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                slug=f"program-{program_id.hex[:10]}",
                title="Support program",
            ),
            ProgramVersion(
                id=version_id,
                program_id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                version_number=1,
                status=ProgramVersionStatus.PUBLISHED.value,
                published_at=NOW,
            ),
            Module(
                id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                title="Support module",
            ),
            CatalogActivity(
                id=activity_id,
                module_id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                scope=CatalogScope.TENANT.value,
                owner_key=tenant_id,
                tenant_id=tenant_id,
                position=1,
                kind=ActivityKind.REFLECTION.value,
                title="Support activity",
                prompt="Describe the support case.",
                is_required=True,
            ),
            Enrollment(
                id=enrollment_id,
                tenant_id=tenant_id,
                person_id=person_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                source="manual_grant",
                status="active",
                enrolled_at=NOW,
            ),
        ]
    )
    database.commit()

    result = diagnose_learner(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        purpose="learner_support",
        now=NOW,
    )
    assert len(result.enrollments) == 1
    enrollment = result.enrollments[0]
    assert enrollment.enrollment_id == enrollment_id
    assert enrollment.enrollment_status == "active"
    assert enrollment.entitlement_status == "missing"
    assert enrollment.progress is None


def test_scoped_evidence_returns_latest_submission_metadata_without_payload(
    database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, other_tenant_id, person_id = uuid4(), uuid4(), uuid4()
    enrollment_id, other_enrollment_id = uuid4(), uuid4()
    version_id, program_id, module_id, activity_id = uuid4(), uuid4(), uuid4(), uuid4()
    other_activity_id = uuid4()
    reviewer_id = uuid4()
    later = datetime(2026, 9, 13, 12, 5, tzinfo=UTC)
    database.add_all(
        [
            Tenant(id=tenant_id, slug=f"evidence-{tenant_id.hex[:10]}", name="Evidence"),
            Tenant(
                id=other_tenant_id,
                slug=f"other-evidence-{other_tenant_id.hex[:10]}",
                name="Other Evidence",
            ),
            _person(person_id, email="evidence@example.test"),
            _person(reviewer_id, email="reviewer@example.test"),
            Membership(tenant_id=tenant_id, person_id=person_id, role="learner"),
            Membership(tenant_id=tenant_id, person_id=reviewer_id, role="support"),
            Membership(tenant_id=other_tenant_id, person_id=person_id, role="learner"),
            Enrollment(
                id=enrollment_id,
                tenant_id=tenant_id,
                person_id=person_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=tenant_id,
                program_owner_key=tenant_id,
                source="manual_grant",
                status="active",
                enrolled_at=NOW,
            ),
            Enrollment(
                id=other_enrollment_id,
                tenant_id=other_tenant_id,
                person_id=person_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_tenant_id=other_tenant_id,
                program_owner_key=other_tenant_id,
                source="manual_grant",
                status="active",
                enrolled_at=NOW,
            ),
        ]
    )
    selected_evidence_id, selected_second_id, wrong_evidence_id = uuid4(), uuid4(), uuid4()
    database.add_all(
        [
            LearningEvidence(
                id=selected_evidence_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=tenant_id,
                module_id=module_id,
                activity_id=activity_id,
                evidence_type="reflection",
                activity_version=f"activity:{activity_id}",
                policy_version="human-review-v1",
                idempotency_key="selected-evidence-1",
                payload={"private": "should never be loaded by this read"},
                captured_at=NOW,
            ),
            LearningEvidence(
                id=selected_second_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=tenant_id,
                module_id=module_id,
                activity_id=other_activity_id,
                evidence_type="implementation",
                activity_version=f"activity:{other_activity_id}",
                policy_version="human-review-v1",
                idempotency_key="selected-evidence-2",
                payload={"private": "also bounded out"},
                captured_at=later,
            ),
            LearningEvidence(
                id=wrong_evidence_id,
                tenant_id=other_tenant_id,
                person_id=person_id,
                enrollment_id=other_enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=other_tenant_id,
                module_id=module_id,
                activity_id=activity_id,
                evidence_type="review",
                activity_version=f"activity:{activity_id}",
                policy_version="human-review-v1",
                idempotency_key="wrong-scope-evidence",
                payload={"private": "wrong scope"},
                captured_at=NOW,
            ),
        ]
    )
    database.add_all(
        [
            EvidenceSubmission(
                id=uuid4(),
                evidence_id=selected_evidence_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=tenant_id,
                module_id=module_id,
                activity_id=activity_id,
                submitted_by_person_id=person_id,
                assigned_reviewer_id=None,
                idempotency_key="selected-submission-old",
                status="recorded",
                submitted_at=NOW,
            ),
            EvidenceSubmission(
                id=uuid4(),
                evidence_id=selected_evidence_id,
                tenant_id=tenant_id,
                person_id=person_id,
                enrollment_id=enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=tenant_id,
                module_id=module_id,
                activity_id=activity_id,
                submitted_by_person_id=person_id,
                assigned_reviewer_id=reviewer_id,
                idempotency_key="selected-submission-new",
                status="awaiting_review",
                submitted_at=later,
            ),
            EvidenceSubmission(
                id=uuid4(),
                evidence_id=wrong_evidence_id,
                tenant_id=other_tenant_id,
                person_id=person_id,
                enrollment_id=other_enrollment_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope=CatalogScope.TENANT.value,
                program_owner_key=other_tenant_id,
                module_id=module_id,
                activity_id=activity_id,
                submitted_by_person_id=person_id,
                assigned_reviewer_id=None,
                idempotency_key="wrong-scope-submission",
                status="recorded",
                submitted_at=later,
            ),
        ]
    )
    database.commit()

    monkeypatch.setattr("ac_platform.learning.admin_diagnosis.MAX_EVIDENCE", 1)
    evidence, truncated = _scoped_evidence(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_version_id=version_id,
        program_id=program_id,
        program_scope=CatalogScope.TENANT.value,
        program_owner_key=tenant_id,
    )

    assert truncated is True
    assert len(evidence) == 1
    item = evidence[0]
    assert item.activity_id == activity_id
    assert item.evidence_type == "reflection"
    assert item.submission_status == "awaiting_review"
    assert item.submitted_at is not None
    assert item.submitted_at.replace(tzinfo=UTC) == later
    assert not hasattr(item, "payload")


def test_stale_completion_is_excluded_from_authoritative_projection() -> None:
    tenant_id, person_id, enrollment_id, program_id, version_id, module_id, activity_id = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    activity = ActivityDefinition(
        id=activity_id,
        kind=ActivityKind.REFLECTION,
        module_id=module_id,
        program_version_id=version_id,
        program_id=program_id,
        program_scope="tenant",
        program_owner_key=tenant_id,
        tenant_id=tenant_id,
        title="Current activity",
        order=1,
        required=True,
        version="activity:current",
    )
    program = ProgramDefinition(
        id=program_id,
        program_version_id=version_id,
        program_scope="tenant",
        program_owner_key=tenant_id,
        version="program:current",
        modules=(
            ModuleDefinition(
                id=module_id,
                program_version_id=version_id,
                program_id=program_id,
                program_scope="tenant",
                program_owner_key=tenant_id,
                activities=(activity,),
            ),
        ),
    )
    actor = ActorContext(person_id=person_id, session_id=uuid4(), tenant_id=tenant_id)
    access = LearningAccessContext(
        actor=actor,
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_version_id=version_id,
        activity=activity,
        program=program,
        membership=MembershipResolution(
            tenant_id=tenant_id,
            person_id=person_id,
            role="learner",
            active=True,
            tenant_active=True,
        ),
        enrollment_active=True,
        entitlement_active=True,
        catalog_version_active=True,
        catalog_version_immutable=True,
        assigned_reviewer_id=None,
    )
    stale = ActivityProgressSnapshot(
        tenant_id=tenant_id,
        person_id=person_id,
        enrollment_id=enrollment_id,
        program_version_id=version_id,
        program_id=program_id,
        program_scope="tenant",
        program_owner_key=tenant_id,
        module_id=module_id,
        activity_id=activity_id,
        state=ActivityState.COMPLETED,
        activity_version="activity:stale",
        policy_version="human-review-v1",
        revision=1,
        completed_at=NOW,
        completion_evidence_id=uuid4(),
        updated_at=NOW,
    )
    store = InMemoryLearningStore(activities=[activity], access_contexts=[access], progress=[stale])

    authoritative = authoritative_progress(store, access)
    projection = ProgressProjector().project(program, authoritative)

    assert activity_id not in authoritative
    assert projection.completed_count == 0
    assert projection.activity_states[0].state is ActivityState.AVAILABLE
    assert projection.activity_states[0].reason == "available"
