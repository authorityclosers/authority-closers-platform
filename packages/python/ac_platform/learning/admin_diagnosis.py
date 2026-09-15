"""Narrow, read-only learner lookup and diagnosis for the admin surface.

This module deliberately does not create an admin read model.  It resolves an
active learner inside one selected tenant and projects the existing canonical
enrollment and learning records into a redacted support response.  Draft and
evidence payloads are never returned.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ac_platform.catalog.models import (
    IMMUTABLE_VERSION_STATUSES,
    Program,
    ProgramVersion,
)
from ac_platform.catalog.models import (
    Activity as CatalogActivity,
)
from ac_platform.community.application import normalize_username
from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.enrollment.models import Enrollment, Entitlement
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.password_auth import normalize_email
from ac_platform.kernel.errors import DomainError, ResourceNotFound
from ac_platform.learning.catalog_activity import resolve_catalog_activity
from ac_platform.learning.models import ActivityDraft, EvidenceSubmission, LearningEvidence
from ac_platform.learning.services import (
    ActivityDefinition,
    ActivityStateExplanation,
    ProgressProjector,
    SqlAlchemyLearningRepository,
    authoritative_progress,
)
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

LOOKUP_LIMIT = 25
MAX_LOOKUP_QUERY_LENGTH = 320
MAX_ENROLLMENTS = 25
MAX_ACTIVITY_STATES = 500
MAX_DRAFTS = 500
MAX_EVIDENCE = 500
REDACTION_VERSION = "admin-learner-v1"

_UUID_QUERY = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class DiagnosisPurpose(StrEnum):
    LEARNER_SUPPORT = "learner_support"
    SAFEGUARDING_REVIEW = "safeguarding_review"
    ACCESSIBILITY_REVIEW = "accessibility_review"


DIAGNOSIS_PURPOSES = frozenset(item.value for item in DiagnosisPurpose)


class DiagnosisLookupInvalid(DomainError):
    """The lookup query cannot identify a learner through an approved key."""

    code = "admin_learner_lookup_invalid"
    title = "Learner lookup is invalid"
    status = 422


class LearnerDiagnosisUnavailable(ResourceNotFound):
    """The requested learner is outside the selected tenant's safe scope."""

    code = "admin_learner_unavailable"
    title = "Learner unavailable"


@dataclass(frozen=True, slots=True)
class LearnerLookupCandidate:
    person_id: UUID
    display_name: str
    username: str | None
    masked_email: str
    membership_status: str
    membership_role: str


@dataclass(frozen=True, slots=True)
class LearnerLookupResult:
    tenant_id: UUID
    redaction_version: str
    candidates: tuple[LearnerLookupCandidate, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class ActivityStateMetadata:
    activity_id: UUID
    title: str
    kind: str
    state: str
    required: bool
    reason: str
    missing_activity_ids: tuple[UUID, ...]
    missing_module_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class ProgressMetadata:
    projection_version: str
    denominator: int
    completed_count: int
    percentage: float
    next_activity_id: UUID | None
    activity_states: tuple[ActivityStateMetadata, ...]
    activity_states_truncated: bool


@dataclass(frozen=True, slots=True)
class DraftMetadata:
    activity_id: UUID
    present: bool
    revision: int
    saved_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceMetadata:
    activity_id: UUID
    evidence_type: str
    submission_status: str | None
    captured_at: datetime
    submitted_at: datetime | None


@dataclass(frozen=True, slots=True)
class EnrollmentMetadata:
    enrollment_id: UUID
    program_id: UUID
    program_title: str
    program_version_id: UUID
    version_number: int
    enrollment_status: str
    entitlement_status: str
    progress: ProgressMetadata | None
    truncated: bool
    drafts_truncated: bool
    drafts: tuple[DraftMetadata, ...]
    evidence_truncated: bool
    evidence: tuple[EvidenceMetadata, ...]


@dataclass(frozen=True, slots=True)
class LearnerDiagnosis:
    tenant_id: UUID
    person_id: UUID
    display_name: str
    username: str | None
    masked_email: str
    purpose: str
    redaction_version: str
    as_of: datetime
    membership_status: str
    membership_role: str
    enrollments: tuple[EnrollmentMetadata, ...]
    truncated: bool


def _normalize_lookup_query(value: str) -> str:
    if not isinstance(value, str):
        raise DiagnosisLookupInvalid("lookup query must be text")
    normalized = value.strip()
    if not normalized:
        raise DiagnosisLookupInvalid("lookup query is required")
    if len(normalized) > MAX_LOOKUP_QUERY_LENGTH:
        raise DiagnosisLookupInvalid("lookup query is too long")
    if _UUID_QUERY.fullmatch(normalized):
        raise DiagnosisLookupInvalid("raw UUID lookup is not supported")
    try:
        if "@" in normalized:
            # Identity comparisons lower-case both sides; retain the canonical
            # helper's validation/IDNA behavior before making that comparison.
            return normalize_email(normalized).casefold()
        return normalize_username(normalized)
    except (DomainError, ValueError) as error:
        raise DiagnosisLookupInvalid(
            "lookup query must be an exact email or public username"
        ) from error


def _mask_email(email: str | None) -> str:
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if not local or not domain:
        return "***"
    return f"{local[0]}***@{domain}"


def _display_name(person: Person) -> str:
    return (person.display_name or person.first_name or "Learner").strip()


def _active_target(
    session: Session,
    *,
    tenant_id: UUID,
    person_id: UUID,
) -> tuple[Person, Membership, str | None] | None:
    row = session.execute(
        select(
            Person,
            Membership,
            CohorvaPublicProfile.username,
        )
        .select_from(Membership)
        .join(Person, Person.id == Membership.person_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .outerjoin(CohorvaPublicProfile, CohorvaPublicProfile.person_id == Membership.person_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.person_id == person_id,
            Membership.role == "learner",
            Membership.status == MembershipStatus.ACTIVE.value,
            Membership.ended_at.is_(None),
            Person.status == PersonStatus.ACTIVE.value,
            Tenant.status == TenantStatus.ACTIVE.value,
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2])


def lookup_learners(
    session: Session,
    *,
    tenant_id: UUID,
    query: str,
) -> LearnerLookupResult:
    """Resolve an active learner by exact normalized email or public username.

    Public usernames are read from the canonical community profile tables.  A
    UUID is explicitly rejected to keep target resolution server-owned.
    """

    normalized = _normalize_lookup_query(query)
    rows = session.execute(
        select(
            Person,
            Membership,
            CohorvaPublicProfile.username,
        )
        .select_from(Membership)
        .join(Person, Person.id == Membership.person_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .outerjoin(CohorvaPublicProfile, CohorvaPublicProfile.person_id == Membership.person_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role == "learner",
            Membership.status == MembershipStatus.ACTIVE.value,
            Membership.ended_at.is_(None),
            Person.status == PersonStatus.ACTIVE.value,
            Tenant.status == TenantStatus.ACTIVE.value,
            (
                func.lower(Person.email) == normalized
                if "@" in normalized
                else (func.lower(CohorvaPublicProfile.username) == normalized)
            ),
        )
        .order_by(Person.id)
        .limit(LOOKUP_LIMIT + 1)
    ).all()
    candidates = tuple(
        LearnerLookupCandidate(
            person_id=person.id,
            display_name=_display_name(person),
            username=username,
            masked_email=_mask_email(person.email),
            membership_status=membership.status,
            membership_role=membership.role,
        )
        for person, membership, username in rows[:LOOKUP_LIMIT]
    )
    return LearnerLookupResult(
        tenant_id=tenant_id,
        redaction_version=REDACTION_VERSION,
        candidates=candidates,
        truncated=len(rows) > LOOKUP_LIMIT,
    )


def _activity_state_metadata(
    item: ActivityStateExplanation,
    *,
    activity_labels: dict[UUID, tuple[str, str]],
) -> ActivityStateMetadata:
    title, kind = activity_labels[item.activity_id]
    return ActivityStateMetadata(
        activity_id=item.activity_id,
        title=title,
        kind=kind,
        state=item.state.value,
        required=item.required,
        reason=item.reason,
        missing_activity_ids=item.missing_activity_ids[:MAX_ACTIVITY_STATES],
        missing_module_ids=item.missing_module_ids[:MAX_ACTIVITY_STATES],
    )


def _scoped_evidence(
    session: Session,
    *,
    tenant_id: UUID,
    person_id: UUID,
    enrollment_id: UUID,
    program_version_id: UUID,
    program_id: UUID,
    program_scope: str,
    program_owner_key: UUID,
) -> tuple[tuple[EvidenceMetadata, ...], bool]:
    # Project only the metadata columns needed by this boundary.  Selecting
    # the ORM entity would hydrate the private evidence payload even though it
    # is never serialized.
    evidence_rows = tuple(
        session.execute(
            select(
                LearningEvidence.id.label("evidence_id"),
                LearningEvidence.activity_id,
                LearningEvidence.evidence_type,
                LearningEvidence.captured_at,
            )
            .where(
                LearningEvidence.tenant_id == tenant_id,
                LearningEvidence.person_id == person_id,
                LearningEvidence.enrollment_id == enrollment_id,
                LearningEvidence.program_version_id == program_version_id,
                LearningEvidence.program_id == program_id,
                LearningEvidence.program_scope == program_scope,
                LearningEvidence.program_owner_key == program_owner_key,
            )
            .order_by(LearningEvidence.captured_at, LearningEvidence.id)
            .limit(MAX_EVIDENCE + 1)
        ).all()
    )
    evidence_ids = tuple(row.evidence_id for row in evidence_rows[:MAX_EVIDENCE])
    latest_submission: dict[UUID, tuple[str, datetime]] = {}
    if evidence_ids:
        submission_rank = (
            func.row_number()
            .over(
                partition_by=EvidenceSubmission.evidence_id,
                order_by=(EvidenceSubmission.submitted_at.desc(), EvidenceSubmission.id.desc()),
            )
            .label("submission_rank")
        )
        latest_submissions = (
            select(
                EvidenceSubmission.evidence_id,
                EvidenceSubmission.status,
                EvidenceSubmission.submitted_at,
                submission_rank,
            )
            .where(
                EvidenceSubmission.tenant_id == tenant_id,
                EvidenceSubmission.person_id == person_id,
                EvidenceSubmission.enrollment_id == enrollment_id,
                EvidenceSubmission.program_version_id == program_version_id,
                EvidenceSubmission.program_id == program_id,
                EvidenceSubmission.program_scope == program_scope,
                EvidenceSubmission.program_owner_key == program_owner_key,
                EvidenceSubmission.evidence_id.in_(evidence_ids),
            )
            .subquery()
        )
        submission_rows = session.execute(
            select(
                latest_submissions.c.evidence_id,
                latest_submissions.c.status,
                latest_submissions.c.submitted_at,
            ).where(latest_submissions.c.submission_rank == 1)
        ).all()
        for submission in submission_rows:
            latest_submission.setdefault(
                submission.evidence_id,
                (submission.status, submission.submitted_at),
            )

    truncated = len(evidence_rows) > MAX_EVIDENCE
    return tuple(
        EvidenceMetadata(
            activity_id=evidence.activity_id,
            evidence_type=evidence.evidence_type,
            submission_status=(
                latest_submission[evidence.evidence_id][0]
                if evidence.evidence_id in latest_submission
                else None
            ),
            captured_at=evidence.captured_at,
            submitted_at=(
                latest_submission[evidence.evidence_id][1]
                if evidence.evidence_id in latest_submission
                else None
            ),
        )
        for evidence in evidence_rows[:MAX_EVIDENCE]
    ), truncated


def _scoped_drafts(
    session: Session,
    *,
    tenant_id: UUID,
    person_id: UUID,
    enrollment_id: UUID,
    program_version_id: UUID,
    program_id: UUID,
    program_scope: str,
    program_owner_key: UUID,
) -> tuple[tuple[DraftMetadata, ...], bool]:
    # Keep the learner's draft body out of the support transaction entirely;
    # presence, revision, and save time are the only approved diagnostics.
    rows = tuple(
        session.execute(
            select(ActivityDraft.activity_id, ActivityDraft.revision, ActivityDraft.saved_at)
            .where(
                ActivityDraft.tenant_id == tenant_id,
                ActivityDraft.person_id == person_id,
                ActivityDraft.enrollment_id == enrollment_id,
                ActivityDraft.program_version_id == program_version_id,
                ActivityDraft.program_id == program_id,
                ActivityDraft.program_scope == program_scope,
                ActivityDraft.program_owner_key == program_owner_key,
            )
            .order_by(ActivityDraft.activity_id)
            .limit(MAX_DRAFTS + 1)
        ).all()
    )
    truncated = len(rows) > MAX_DRAFTS
    return tuple(
        DraftMetadata(
            activity_id=row.activity_id,
            present=True,
            revision=row.revision,
            saved_at=row.saved_at,
        )
        for row in rows[:MAX_DRAFTS]
    ), truncated


def diagnose_learner(
    session: Session,
    *,
    tenant_id: UUID,
    person_id: UUID,
    purpose: str,
    now: datetime | None = None,
    activity_resolver: Callable[[object, object], ActivityDefinition] = resolve_catalog_activity,
) -> LearnerDiagnosis:
    """Build a redacted diagnosis from one active learner tenant scope."""

    if purpose not in DIAGNOSIS_PURPOSES:
        raise DiagnosisLookupInvalid("diagnosis purpose is not supported")
    as_of = now or datetime.now(UTC)
    as_of = as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of.astimezone(UTC)
    target = _active_target(session, tenant_id=tenant_id, person_id=person_id)
    if target is None:
        raise LearnerDiagnosisUnavailable("The learner is unavailable in this tenant.")
    person, membership, username = target

    rows = session.execute(
        select(Enrollment, Entitlement, ProgramVersion, Program)
        .select_from(Enrollment)
        .outerjoin(
            Entitlement,
            (Entitlement.tenant_id == Enrollment.tenant_id)
            & (Entitlement.enrollment_id == Enrollment.id)
            & (Entitlement.person_id == Enrollment.person_id)
            & (Entitlement.program_version_id == Enrollment.program_version_id)
            & (Entitlement.program_id == Enrollment.program_id)
            & (Entitlement.program_scope == Enrollment.program_scope)
            & (Entitlement.program_owner_key == Enrollment.program_owner_key),
        )
        .join(
            ProgramVersion,
            (ProgramVersion.id == Enrollment.program_version_id)
            & (ProgramVersion.program_id == Enrollment.program_id)
            & (ProgramVersion.scope == Enrollment.program_scope)
            & (ProgramVersion.owner_key == Enrollment.program_owner_key),
        )
        .join(
            Program,
            (Program.id == Enrollment.program_id)
            & (Program.scope == Enrollment.program_scope)
            & (Program.owner_key == Enrollment.program_owner_key),
        )
        .where(
            Enrollment.tenant_id == tenant_id,
            Enrollment.person_id == person_id,
            ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES),
        )
        .order_by(Enrollment.enrolled_at, Enrollment.id)
        .limit(MAX_ENROLLMENTS + 1)
    ).all()
    enrollments_truncated = len(rows) > MAX_ENROLLMENTS

    repository = SqlAlchemyLearningRepository(
        session,
        activity_resolver=activity_resolver,
        reviewer_resolver=lambda _access: None,
    )
    enrollment_metadata: list[EnrollmentMetadata] = []
    for enrollment, entitlement, version, program in rows[:MAX_ENROLLMENTS]:
        activities = session.scalars(
            select(CatalogActivity)
            .where(
                CatalogActivity.program_version_id == version.id,
                CatalogActivity.program_id == version.program_id,
                CatalogActivity.scope == version.scope,
                CatalogActivity.owner_key == version.owner_key,
                CatalogActivity.tenant_id.is_(None) | (CatalogActivity.tenant_id == tenant_id),
            )
            .order_by(CatalogActivity.module_id, CatalogActivity.position, CatalogActivity.id)
        ).all()
        drafts, drafts_truncated = _scoped_drafts(
            session,
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_owner_key=version.owner_key,
        )
        evidence, evidence_truncated = _scoped_evidence(
            session,
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            program_id=program.id,
            program_scope=version.scope,
            program_owner_key=version.owner_key,
        )
        accessible = (
            enrollment.status == "active"
            and entitlement is not None
            and entitlement.status == "active"
        )
        if not activities or not accessible:
            enrollment_metadata.append(
                EnrollmentMetadata(
                    enrollment_id=enrollment.id,
                    program_id=program.id,
                    program_title=program.title,
                    program_version_id=version.id,
                    version_number=version.version_number,
                    enrollment_status=enrollment.status,
                    entitlement_status=("missing" if entitlement is None else entitlement.status),
                    progress=None,
                    truncated=drafts_truncated or evidence_truncated,
                    drafts_truncated=drafts_truncated,
                    drafts=drafts,
                    evidence_truncated=evidence_truncated,
                    evidence=evidence,
                )
            )
            continue

        assert entitlement is not None
        access = repository.resolve_scope(
            tenant_id=tenant_id,
            person_id=person_id,
            enrollment_id=enrollment.id,
            program_version_id=version.id,
            activity_id=activities[0].id,
        )
        canonical_progress = authoritative_progress(repository, access)
        projection = ProgressProjector(access.program.projection_version).project(
            access.program,
            canonical_progress,
        )
        activity_labels = {
            activity.id: (
                activity.title,
                str(activity.kind.value if hasattr(activity.kind, "value") else activity.kind),
            )
            for module in access.program.modules
            for activity in module.activities
        }
        activity_states_truncated = len(projection.activity_states) > MAX_ACTIVITY_STATES
        progress = ProgressMetadata(
            projection_version=projection.projection_version,
            denominator=projection.denominator,
            completed_count=projection.completed_count,
            percentage=projection.percentage,
            next_activity_id=projection.next_activity_id,
            activity_states=tuple(
                _activity_state_metadata(item, activity_labels=activity_labels)
                for item in projection.activity_states[:MAX_ACTIVITY_STATES]
            ),
            activity_states_truncated=activity_states_truncated,
        )
        enrollment_metadata.append(
            EnrollmentMetadata(
                enrollment_id=enrollment.id,
                program_id=program.id,
                program_title=program.title,
                program_version_id=version.id,
                version_number=version.version_number,
                enrollment_status=enrollment.status,
                entitlement_status=entitlement.status,
                progress=progress,
                truncated=(activity_states_truncated or drafts_truncated or evidence_truncated),
                drafts_truncated=drafts_truncated,
                drafts=drafts,
                evidence_truncated=evidence_truncated,
                evidence=evidence,
            )
        )

    return LearnerDiagnosis(
        tenant_id=tenant_id,
        person_id=person.id,
        display_name=_display_name(person),
        username=username,
        masked_email=_mask_email(person.email),
        purpose=purpose,
        redaction_version=REDACTION_VERSION,
        as_of=as_of,
        membership_status=membership.status,
        membership_role=membership.role,
        enrollments=tuple(enrollment_metadata),
        truncated=enrollments_truncated,
    )


__all__ = [
    "DIAGNOSIS_PURPOSES",
    "DiagnosisPurpose",
    "DiagnosisLookupInvalid",
    "LearnerDiagnosisUnavailable",
    "LearnerLookupCandidate",
    "LearnerLookupResult",
    "LearnerDiagnosis",
    "lookup_learners",
    "diagnose_learner",
    "REDACTION_VERSION",
]
