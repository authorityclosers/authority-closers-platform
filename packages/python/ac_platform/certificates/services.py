"""Pure completion evaluation and application services for course certificates."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransactionOrigin

from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.models import GLOBAL_CATALOG_OWNER_KEY
from ac_platform.certificates.digests import canonical_sha256
from ac_platform.certificates.models import (
    COURSE_COMPLETION_CERTIFICATE_TYPE,
    CertificateCommandIdempotency,
    CertificateCommandStatus,
    CertificateEvent,
    CertificateEventType,
    CourseCompletionCertificate,
)
from ac_platform.certificates.models import (
    CompletionSnapshot as CompletionSnapshotRecord,
)
from ac_platform.enrollment.models import EnrollmentStatus, Entitlement, EntitlementStatus
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    ResourceConflict,
    ResourceNotFound,
)
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.repository import OutboxRepository
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

COMPLETION_PREDICATE_VERSION = "g1-v1"
CERTIFICATE_CORRECT_PERMISSION = "certificate_correct"
CERTIFICATE_REVOKE_PERMISSION = "certificate_revoke"
CERTIFICATE_ISSUE_OPERATION = "certificate_issue"
CERTIFICATE_CORRECT_OPERATION = "certificate_correct"
CERTIFICATE_REVOKE_OPERATION = "certificate_revoke"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now(value: datetime | None) -> datetime:
    return _as_utc(value or datetime.now(UTC))


def _required_text(value: str, field_name: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} must be at most {maximum} characters")
    return normalized


def _sorted_unique_ids(values: Iterable[UUID], field_name: str) -> tuple[UUID, ...]:
    result = tuple(sorted(values, key=str))
    if len(result) != len(set(result)):
        raise InvalidCompletionConfigurationError(f"{field_name} must not contain duplicates")
    return result


class CertificateServiceError(DomainError):
    """Base exception for expected certificate-domain failures."""


class InvalidCompletionConfigurationError(CertificateServiceError):
    """The pinned version does not contain a deterministic course graph."""


class CompletionIncompleteError(CertificateServiceError):
    """A completion snapshot does not satisfy all required course predicates."""


class EmptyCompletionError(CompletionIncompleteError):
    """A certificate cannot claim completion for a course with no requirements."""


class CertificateAuthorityRequiredError(CertificateServiceError):
    """Issuance must use server-owned entitlement, version, and progress data."""


class ActiveEntitlementRequiredError(CertificateServiceError):
    """The learner has no active entitlement for the requested enrollment."""


class ImmutableProgramVersionRequiredError(CertificateServiceError):
    """The requested catalog version is not an immutable published snapshot."""


class AuthoritativeProgressRequiredError(CertificateServiceError):
    """The certificate issuer could not load authoritative course progress."""


class CertificateSnapshotIntegrityError(CertificateServiceError):
    """A snapshot hash or server-evaluated snapshot does not match its facts."""


class CertificateAuthorizationRequiredError(CertificateServiceError):
    """A certificate change lacks the required subject or active admin permission."""


class CertificateScopeMismatchError(AuthorizationDenied):
    """A snapshot, certificate, actor, or tenant crosses an ownership boundary."""


class CertificateNotFoundError(ResourceNotFound):
    """The requested certificate is not visible in the selected scope."""


class CertificateStateConflictError(ResourceConflict):
    """An append-only certificate event would not extend the current chain."""


class CertificateIdempotencyConflictError(CertificateStateConflictError):
    """An idempotency key was reused with a different certificate request."""


class CertificateAlreadyRevokedError(CertificateStateConflictError):
    """A revoked certificate cannot be corrected through the correction seam."""


class CertificateTransactionRequiredError(CertificateServiceError):
    """A production command was called outside a caller-owned transaction."""


class CertificateCommandInProgressError(CertificateStateConflictError):
    """A concurrent transaction owns the same certificate command key."""


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    """One pinned module and its explicit prerequisite configuration."""

    module_id: UUID
    prerequisite_module_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "prerequisite_module_ids",
            _sorted_unique_ids(self.prerequisite_module_ids, "prerequisite_module_ids"),
        )


@dataclass(frozen=True, slots=True)
class ActivityCompletion:
    """Server-derived completion state for one activity in a pinned version."""

    activity_id: UUID
    module_id: UUID
    required: bool = True
    completed: bool = False


@dataclass(frozen=True, slots=True)
class PinnedCourseVersion:
    """The complete, version-pinned input to the deterministic predicate."""

    tenant_id: UUID
    person_id: UUID
    program_id: UUID
    program_version_id: UUID
    modules: tuple[ModuleDefinition, ...]
    activities: tuple[ActivityCompletion, ...]
    enrollment_id: UUID | None = None
    program_scope: str = "tenant"
    program_tenant_id: UUID | None = None
    program_owner_key: UUID | None = None

    def __post_init__(self) -> None:
        if self.program_scope not in {"global", "tenant"}:
            raise InvalidCompletionConfigurationError("program scope is unsupported")
        program_tenant_id = self.program_tenant_id
        if self.program_scope == "tenant":
            if program_tenant_id is None:
                program_tenant_id = self.tenant_id
            if program_tenant_id != self.tenant_id:
                raise InvalidCompletionConfigurationError(
                    "tenant-owned course versions must match the learner tenant"
                )
        else:
            program_tenant_id = None
        expected_owner = (
            GLOBAL_CATALOG_OWNER_KEY if self.program_scope == "global" else program_tenant_id
        )
        if expected_owner is None:
            raise InvalidCompletionConfigurationError("tenant course versions require an owner")
        if self.program_owner_key is not None and self.program_owner_key != expected_owner:
            raise InvalidCompletionConfigurationError("program owner key is inconsistent")
        object.__setattr__(self, "program_tenant_id", program_tenant_id)
        object.__setattr__(self, "program_owner_key", expected_owner)
        modules = tuple(self.modules)
        activities = tuple(self.activities)
        module_ids = _sorted_unique_ids((module.module_id for module in modules), "modules")
        _sorted_unique_ids((activity.activity_id for activity in activities), "activities")
        module_by_id = {module.module_id: module for module in modules}
        if set(module_ids) != set(module_by_id):
            raise InvalidCompletionConfigurationError("module IDs must be unique")
        for activity in activities:
            if activity.module_id not in module_by_id:
                raise InvalidCompletionConfigurationError(
                    "every activity must belong to a pinned module"
                )
        for module in modules:
            unknown = set(module.prerequisite_module_ids) - set(module_ids)
            if unknown:
                raise InvalidCompletionConfigurationError(
                    "module prerequisites must refer to the pinned version"
                )
        object.__setattr__(
            self,
            "modules",
            tuple(sorted(modules, key=lambda item: str(item.module_id))),
        )
        object.__setattr__(
            self,
            "activities",
            tuple(sorted(activities, key=lambda item: str(item.activity_id))),
        )


def _snapshot_hash(snapshot: CompletionSnapshot) -> str:
    encoded = json.dumps(
        snapshot.canonical_payload(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ModuleCompletion:
    """Explainable result for one module in a completion snapshot."""

    module_id: UUID
    prerequisite_module_ids: tuple[UUID, ...]
    required_activity_ids: tuple[UUID, ...]
    completed_activity_ids: tuple[UUID, ...]
    prerequisites_satisfied: bool
    is_complete: bool

    def __post_init__(self) -> None:
        prerequisite_ids = _sorted_unique_ids(
            self.prerequisite_module_ids, "prerequisite_module_ids"
        )
        required_ids = _sorted_unique_ids(self.required_activity_ids, "required_activity_ids")
        completed_ids = _sorted_unique_ids(self.completed_activity_ids, "completed_activity_ids")
        if set(completed_ids) - set(required_ids):
            raise InvalidCompletionConfigurationError(
                "completed module activities must be required activities"
            )
        expected_complete = self.prerequisites_satisfied and len(required_ids) == len(completed_ids)
        if self.is_complete != expected_complete:
            raise InvalidCompletionConfigurationError(
                "module completion must match its prerequisites and activity counts"
            )
        object.__setattr__(self, "prerequisite_module_ids", prerequisite_ids)
        object.__setattr__(self, "required_activity_ids", required_ids)
        object.__setattr__(self, "completed_activity_ids", completed_ids)

    @property
    def required_activity_count(self) -> int:
        return len(self.required_activity_ids)

    @property
    def completed_activity_count(self) -> int:
        return len(self.completed_activity_ids)


@dataclass(frozen=True, slots=True)
class CompletionSnapshot:
    """Immutable result of evaluating one person against one pinned version."""

    tenant_id: UUID
    person_id: UUID
    program_id: UUID
    program_version_id: UUID
    predicate_version: str
    required_activity_ids: tuple[UUID, ...]
    completed_activity_ids: tuple[UUID, ...]
    module_results: tuple[ModuleCompletion, ...]
    required_activity_count: int
    completed_activity_count: int
    is_complete: bool
    captured_at: datetime
    id: UUID = field(default_factory=uuid4)
    supersedes_snapshot_id: UUID | None = None
    enrollment_id: UUID | None = None
    program_scope: str = "tenant"
    program_tenant_id: UUID | None = None
    program_owner_key: UUID | None = None
    snapshot_hash: str | None = None

    def __post_init__(self) -> None:
        if self.program_scope not in {"global", "tenant"}:
            raise InvalidCompletionConfigurationError("program scope is unsupported")
        program_tenant_id = self.program_tenant_id
        if self.program_scope == "tenant":
            if program_tenant_id is None:
                program_tenant_id = self.tenant_id
            if program_tenant_id != self.tenant_id:
                raise InvalidCompletionConfigurationError(
                    "tenant-owned snapshots must match the learner tenant"
                )
        else:
            program_tenant_id = None
        expected_owner = (
            GLOBAL_CATALOG_OWNER_KEY if self.program_scope == "global" else program_tenant_id
        )
        if expected_owner is None:
            raise InvalidCompletionConfigurationError("tenant snapshots require an owner")
        if self.program_owner_key is not None and self.program_owner_key != expected_owner:
            raise InvalidCompletionConfigurationError("snapshot owner key is inconsistent")
        object.__setattr__(self, "program_tenant_id", program_tenant_id)
        object.__setattr__(self, "program_owner_key", expected_owner)
        required_ids = _sorted_unique_ids(self.required_activity_ids, "required_activity_ids")
        completed_ids = _sorted_unique_ids(self.completed_activity_ids, "completed_activity_ids")
        module_results = tuple(sorted(self.module_results, key=lambda item: str(item.module_id)))
        module_ids = _sorted_unique_ids(
            (module.module_id for module in module_results), "module_results"
        )
        if set(completed_ids) - set(required_ids):
            raise InvalidCompletionConfigurationError(
                "completed activities must be a subset of required activities"
            )
        if self.required_activity_count != len(required_ids):
            raise InvalidCompletionConfigurationError(
                "required_activity_count must match required_activity_ids"
            )
        if self.completed_activity_count != len(completed_ids):
            raise InvalidCompletionConfigurationError(
                "completed_activity_count must match completed_activity_ids"
            )
        if len(module_ids) != len(module_results):
            raise InvalidCompletionConfigurationError("module results must be unique")
        module_required_ids = tuple(
            sorted(
                {
                    activity_id
                    for module in module_results
                    for activity_id in module.required_activity_ids
                },
                key=str,
            )
        )
        module_completed_ids = tuple(
            sorted(
                {
                    activity_id
                    for module in module_results
                    for activity_id in module.completed_activity_ids
                },
                key=str,
            )
        )
        if module_required_ids != required_ids or module_completed_ids != completed_ids:
            raise InvalidCompletionConfigurationError(
                "snapshot activity IDs must match its module results"
            )
        expected_complete = all(module.is_complete for module in module_results)
        if self.is_complete != expected_complete:
            raise InvalidCompletionConfigurationError(
                "is_complete must match the module completion results"
            )
        if self.is_complete and self.completed_activity_count != self.required_activity_count:
            raise InvalidCompletionConfigurationError(
                "a complete snapshot must satisfy its activity denominator"
            )
        object.__setattr__(self, "required_activity_ids", required_ids)
        object.__setattr__(self, "completed_activity_ids", completed_ids)
        object.__setattr__(self, "module_results", module_results)
        object.__setattr__(
            self,
            "predicate_version",
            _required_text(self.predicate_version, "predicate_version", 64),
        )
        object.__setattr__(self, "captured_at", _as_utc(self.captured_at))
        expected_hash = _snapshot_hash(self)
        if self.snapshot_hash is not None and self.snapshot_hash != expected_hash:
            raise CertificateSnapshotIntegrityError("snapshot_hash does not match snapshot facts")
        object.__setattr__(self, "snapshot_hash", expected_hash)

    @property
    def denominator(self) -> int:
        """The persisted, explainable number of required activities."""

        return self.required_activity_count

    @property
    def pinned_version_id(self) -> UUID:
        """Alias that makes the version-pinning boundary explicit to callers."""

        return self.program_version_id

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "tenant_id": str(self.tenant_id),
            "person_id": str(self.person_id),
            "program_id": str(self.program_id),
            "program_version_id": str(self.program_version_id),
            "enrollment_id": str(self.enrollment_id) if self.enrollment_id is not None else None,
            "program_scope": self.program_scope,
            "program_tenant_id": (
                str(self.program_tenant_id) if self.program_tenant_id is not None else None
            ),
            "program_owner_key": str(self.program_owner_key),
            "predicate_version": self.predicate_version,
            "required_activity_ids": [str(value) for value in self.required_activity_ids],
            "completed_activity_ids": [str(value) for value in self.completed_activity_ids],
            "module_results": [
                {
                    "module_id": str(module.module_id),
                    "prerequisite_module_ids": [
                        str(value) for value in module.prerequisite_module_ids
                    ],
                    "required_activity_ids": [str(value) for value in module.required_activity_ids],
                    "completed_activity_ids": [
                        str(value) for value in module.completed_activity_ids
                    ],
                    "prerequisites_satisfied": module.prerequisites_satisfied,
                    "is_complete": module.is_complete,
                }
                for module in self.module_results
            ],
            "required_activity_count": self.required_activity_count,
            "completed_activity_count": self.completed_activity_count,
            "is_complete": self.is_complete,
        }

    @property
    def computed_snapshot_hash(self) -> str:
        """Recompute the integrity value without trusting the stored field."""

        return _snapshot_hash(self)


def evaluate_course_completion(
    pinned: PinnedCourseVersion,
    *,
    now: datetime | None = None,
    predicate_version: str = COMPLETION_PREDICATE_VERSION,
) -> CompletionSnapshot:
    """Evaluate completion deterministically from a server-derived version snapshot.

    Required activities are the denominator.  A module is complete only when
    its required activities are complete and all explicitly configured module
    prerequisites are complete.  The graph is evaluated recursively and cycles
    are rejected as invalid content configuration.
    """

    module_by_id = {module.module_id: module for module in pinned.modules}
    activities_by_module: dict[UUID, list[ActivityCompletion]] = {
        module_id: [] for module_id in module_by_id
    }
    for activity in pinned.activities:
        activities_by_module[activity.module_id].append(activity)

    results: dict[UUID, ModuleCompletion] = {}
    visiting: set[UUID] = set()

    def evaluate_module(module_id: UUID) -> ModuleCompletion:
        if module_id in results:
            return results[module_id]
        if module_id in visiting:
            raise InvalidCompletionConfigurationError("module prerequisites must be acyclic")
        visiting.add(module_id)
        module = module_by_id[module_id]
        prerequisite_results = tuple(
            evaluate_module(prerequisite_id) for prerequisite_id in module.prerequisite_module_ids
        )
        module_activities = tuple(activities_by_module[module_id])
        required_ids = tuple(
            sorted(
                (activity.activity_id for activity in module_activities if activity.required),
                key=str,
            )
        )
        completed_ids = tuple(
            sorted(
                (
                    activity.activity_id
                    for activity in module_activities
                    if activity.required and activity.completed
                ),
                key=str,
            )
        )
        prerequisites_satisfied = all(result.is_complete for result in prerequisite_results)
        result = ModuleCompletion(
            module_id=module_id,
            prerequisite_module_ids=module.prerequisite_module_ids,
            required_activity_ids=required_ids,
            completed_activity_ids=completed_ids,
            prerequisites_satisfied=prerequisites_satisfied,
            is_complete=prerequisites_satisfied and len(required_ids) == len(completed_ids),
        )
        visiting.remove(module_id)
        results[module_id] = result
        return result

    for module_id in sorted(module_by_id, key=str):
        evaluate_module(module_id)

    module_results = tuple(results[module_id] for module_id in sorted(results, key=str))
    required_ids = tuple(
        sorted(
            (activity.activity_id for activity in pinned.activities if activity.required),
            key=str,
        )
    )
    completed_ids = tuple(
        sorted(
            (
                activity.activity_id
                for activity in pinned.activities
                if activity.required and activity.completed
            ),
            key=str,
        )
    )
    return CompletionSnapshot(
        tenant_id=pinned.tenant_id,
        person_id=pinned.person_id,
        program_id=pinned.program_id,
        program_version_id=pinned.program_version_id,
        predicate_version=predicate_version,
        required_activity_ids=required_ids,
        completed_activity_ids=completed_ids,
        module_results=module_results,
        required_activity_count=len(required_ids),
        completed_activity_count=len(completed_ids),
        is_complete=all(module.is_complete for module in module_results),
        captured_at=_now(now),
        enrollment_id=pinned.enrollment_id,
        program_scope=pinned.program_scope,
        program_tenant_id=pinned.program_tenant_id,
        program_owner_key=pinned.program_owner_key,
    )


class CourseCompletionService:
    """Pure service facade for the pinned-version completion predicate."""

    def evaluate(
        self,
        pinned: PinnedCourseVersion,
        *,
        now: datetime | None = None,
        predicate_version: str = COMPLETION_PREDICATE_VERSION,
    ) -> CompletionSnapshot:
        return evaluate_course_completion(
            pinned,
            now=now,
            predicate_version=predicate_version,
        )


@dataclass(frozen=True, slots=True)
class CourseCompletionCertificateData:
    """Immutable application view of an issued course-completion certificate."""

    id: UUID
    tenant_id: UUID
    person_id: UUID
    program_id: UUID
    program_version_id: UUID
    certificate_type: str
    original_completion_snapshot_id: UUID
    issued_at: datetime
    created_at: datetime
    idempotency_key: str | None = None
    enrollment_id: UUID | None = None
    program_scope: str = "tenant"
    program_tenant_id: UUID | None = None
    program_owner_key: UUID | None = None


@dataclass(frozen=True, slots=True)
class CertificateEventData:
    """Immutable application view of one append-only certificate event."""

    id: UUID
    certificate_id: UUID
    tenant_id: UUID
    person_id: UUID
    event_type: CertificateEventType
    completion_snapshot_id: UUID | None
    supersedes_event_id: UUID | None
    actor_person_id: UUID | None
    reason: str | None
    provenance: Mapping[str, Any]
    occurred_at: datetime
    idempotency_key: str | None = None
    request_digest: str | None = None
    sequence_no: int | None = None
    enrollment_id: UUID | None = None
    program_id: UUID | None = None
    program_version_id: UUID | None = None
    program_scope: str = "tenant"
    program_tenant_id: UUID | None = None
    program_owner_key: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_type", CertificateEventType(self.event_type))
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))
        object.__setattr__(self, "occurred_at", _as_utc(self.occurred_at))
        if self.request_digest is None:
            object.__setattr__(self, "request_digest", _event_request_digest(self))
        _validate_event_request_digest(self)


def _event_request_digest(event: CertificateEventData) -> str:
    payload = {
        "certificate_id": str(event.certificate_id),
        "tenant_id": str(event.tenant_id),
        "person_id": str(event.person_id),
        "enrollment_id": str(event.enrollment_id) if event.enrollment_id is not None else None,
        "program_id": str(event.program_id) if event.program_id is not None else None,
        "program_version_id": (
            str(event.program_version_id) if event.program_version_id is not None else None
        ),
        "program_scope": event.program_scope,
        "program_tenant_id": (
            str(event.program_tenant_id) if event.program_tenant_id is not None else None
        ),
        "program_owner_key": (
            str(event.program_owner_key) if event.program_owner_key is not None else None
        ),
        "event_type": event.event_type.value,
        "completion_snapshot_id": (
            str(event.completion_snapshot_id) if event.completion_snapshot_id is not None else None
        ),
        "supersedes_event_id": (
            str(event.supersedes_event_id) if event.supersedes_event_id is not None else None
        ),
        "actor_person_id": (
            str(event.actor_person_id) if event.actor_person_id is not None else None
        ),
        "reason": event.reason,
        "provenance": dict(event.provenance),
        "idempotency_key": event.idempotency_key,
    }
    return canonical_sha256(payload)


def _validate_event_request_digest(event: CertificateEventData) -> None:
    digest = event.request_digest
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise CertificateSnapshotIntegrityError(
            "certificate request digest must be lowercase SHA-256 hex"
        )
    if digest != _event_request_digest(event):
        raise CertificateSnapshotIntegrityError(
            "certificate request digest does not match canonical event contents"
        )


def _issued_event(
    certificate: CourseCompletionCertificateData,
    snapshot: CompletionSnapshot,
    *,
    captured_at: datetime,
    idempotency_key: str | None,
) -> CertificateEventData:
    return CertificateEventData(
        id=uuid4(),
        certificate_id=certificate.id,
        tenant_id=certificate.tenant_id,
        person_id=certificate.person_id,
        event_type=CertificateEventType.ISSUED,
        completion_snapshot_id=snapshot.id,
        supersedes_event_id=None,
        actor_person_id=None,
        reason=None,
        provenance={
            "source": "completion-service",
            "predicate_version": snapshot.predicate_version,
            "snapshot_hash": snapshot.snapshot_hash,
        },
        occurred_at=captured_at,
        idempotency_key=idempotency_key,
        enrollment_id=certificate.enrollment_id,
        program_id=certificate.program_id,
        program_version_id=certificate.program_version_id,
        program_scope=certificate.program_scope,
        program_tenant_id=certificate.program_tenant_id,
        program_owner_key=certificate.program_owner_key,
        request_digest=None,
        sequence_no=1,
    )


@dataclass(frozen=True, slots=True)
class CertificateIssueResult:
    certificate: CourseCompletionCertificateData
    event: CertificateEventData
    created: bool


@dataclass(frozen=True, slots=True)
class IssueCertificateCommand:
    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_id: UUID
    program_version_id: UUID
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CorrectCertificateCommand:
    certificate_id: UUID
    tenant_id: UUID
    subject_person_id: UUID
    reason: str
    idempotency_key: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RevokeCertificateCommand:
    certificate_id: UUID
    tenant_id: UUID
    subject_person_id: UUID
    reason: str
    idempotency_key: str
    provenance: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CertificateView:
    certificate: CourseCompletionCertificateData
    original_completion: CompletionSnapshot
    current_completion: CompletionSnapshot
    current_event: CertificateEventData

    @property
    def status(self) -> CertificateEventType:
        return self.current_event.event_type


class CertificateStore(Protocol):
    """Persistence port for the application certificate service."""

    def get_certificate(
        self,
        tenant_id: UUID,
        person_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
    ) -> CourseCompletionCertificateData | None: ...

    def get_certificate_by_id(
        self, certificate_id: UUID
    ) -> CourseCompletionCertificateData | None: ...

    def lock_certificate(self, certificate_id: UUID) -> CourseCompletionCertificateData | None: ...

    def save_snapshot(self, snapshot: CompletionSnapshot) -> None: ...

    def get_snapshot(self, snapshot_id: UUID) -> CompletionSnapshot | None: ...

    def save_certificate(self, certificate: CourseCompletionCertificateData) -> None: ...

    def append_event(self, event: CertificateEventData) -> CertificateEventData: ...

    def get_event_by_id(self, event_id: UUID) -> CertificateEventData | None: ...

    def get_latest_event(self, certificate_id: UUID) -> CertificateEventData | None: ...

    def get_event_by_idempotency_key(
        self, certificate_id: UUID, idempotency_key: str
    ) -> CertificateEventData | None: ...


@dataclass(frozen=True, slots=True)
class ActiveEntitlementSnapshot:
    """Server-loaded active entitlement used as the issuance root of trust."""

    tenant_id: UUID
    person_id: UUID
    enrollment_id: UUID
    program_id: UUID
    program_version_id: UUID
    program_scope: str
    program_tenant_id: UUID | None
    program_owner_key: UUID


@dataclass(frozen=True, slots=True)
class ImmutableProgramVersionSnapshot:
    """Server-loaded immutable catalog identity."""

    program_id: UUID
    program_version_id: UUID
    program_scope: str
    program_tenant_id: UUID | None
    program_owner_key: UUID
    published: bool
    immutable: bool


class CertificateAuthority(Protocol):
    """Authority port for entitlement, catalog version, and progress facts."""

    def load_active_entitlement(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
        enrollment_id: UUID | None = None,
    ) -> ActiveEntitlementSnapshot | None: ...

    def load_immutable_program_version(
        self,
        *,
        program_id: UUID,
        program_version_id: UUID,
        program_scope: str,
        program_owner_key: UUID,
    ) -> ImmutableProgramVersionSnapshot | None: ...

    def load_authoritative_progress(
        self,
        entitlement: ActiveEntitlementSnapshot,
        version: ImmutableProgramVersionSnapshot,
    ) -> PinnedCourseVersion | None: ...

    def has_active_permission(
        self, *, actor_person_id: UUID, tenant_id: UUID, permission: str
    ) -> bool: ...


class InMemoryCertificateAuthority:
    """Explicit authority fixture; it never derives facts from caller snapshots."""

    def __init__(
        self,
        *,
        entitlement: ActiveEntitlementSnapshot,
        version: ImmutableProgramVersionSnapshot,
        progress: PinnedCourseVersion,
        permissions: Iterable[tuple[UUID, UUID, str]] = (),
    ) -> None:
        self.entitlement = entitlement
        self.version = version
        self.progress = progress
        self.permissions = set(permissions)

    def load_active_entitlement(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
        enrollment_id: UUID | None = None,
    ) -> ActiveEntitlementSnapshot | None:
        item = self.entitlement
        if (
            item.tenant_id != tenant_id
            or item.person_id != person_id
            or item.program_version_id != program_version_id
            or (enrollment_id is not None and item.enrollment_id != enrollment_id)
        ):
            return None
        return item

    def load_immutable_program_version(
        self,
        *,
        program_id: UUID,
        program_version_id: UUID,
        program_scope: str,
        program_owner_key: UUID,
    ) -> ImmutableProgramVersionSnapshot | None:
        item = self.version
        if (
            item.program_id != program_id
            or item.program_version_id != program_version_id
            or item.program_scope != program_scope
            or item.program_owner_key != program_owner_key
        ):
            return None
        return item

    def load_authoritative_progress(
        self,
        entitlement: ActiveEntitlementSnapshot,
        version: ImmutableProgramVersionSnapshot,
    ) -> PinnedCourseVersion | None:
        if entitlement != self.entitlement or version != self.version:
            return None
        return self.progress

    def has_active_permission(
        self, *, actor_person_id: UUID, tenant_id: UUID, permission: str
    ) -> bool:
        return (actor_person_id, tenant_id, permission) in self.permissions


class InMemoryCertificateStore:
    """Deterministic append-only certificate port for unit and application tests."""

    def __init__(
        self,
        snapshots: Iterable[CompletionSnapshot] = (),
        certificates: Iterable[CourseCompletionCertificateData] = (),
        events: Iterable[CertificateEventData] = (),
    ) -> None:
        self.snapshots: dict[UUID, CompletionSnapshot] = {}
        self.certificates: dict[UUID, CourseCompletionCertificateData] = {}
        self.events: dict[UUID, CertificateEventData] = {}
        self._event_order: dict[UUID, list[UUID]] = {}
        for snapshot in snapshots:
            self.save_snapshot(snapshot)
        for certificate in certificates:
            self.save_certificate(certificate)
        for certificate_event in events:
            self.append_event(certificate_event)

    def get_certificate(
        self,
        tenant_id: UUID,
        person_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
    ) -> CourseCompletionCertificateData | None:
        return next(
            (
                certificate
                for certificate in self.certificates.values()
                if (
                    certificate.tenant_id == tenant_id
                    and certificate.person_id == person_id
                    and certificate.program_id == program_id
                    and certificate.program_version_id == program_version_id
                    and certificate.certificate_type == COURSE_COMPLETION_CERTIFICATE_TYPE
                )
            ),
            None,
        )

    def get_certificate_by_id(self, certificate_id: UUID) -> CourseCompletionCertificateData | None:
        return self.certificates.get(certificate_id)

    def lock_certificate(self, certificate_id: UUID) -> CourseCompletionCertificateData | None:
        return self.get_certificate_by_id(certificate_id)

    def save_snapshot(self, snapshot: CompletionSnapshot) -> None:
        if snapshot.computed_snapshot_hash != snapshot.snapshot_hash:
            raise CertificateSnapshotIntegrityError("snapshot hash does not match snapshot facts")
        existing = self.snapshots.get(snapshot.id)
        if existing is not None:
            if existing != snapshot:
                raise CertificateStateConflictError("completion snapshots are immutable")
            return
        if snapshot.supersedes_snapshot_id is not None:
            previous = self.snapshots.get(snapshot.supersedes_snapshot_id)
            if previous is None:
                raise CertificateStateConflictError("superseded snapshot does not exist")
            _require_same_scope(snapshot, previous)
            _require_same_version(snapshot, previous)
        self.snapshots[snapshot.id] = snapshot

    def get_snapshot(self, snapshot_id: UUID) -> CompletionSnapshot | None:
        return self.snapshots.get(snapshot_id)

    def save_certificate(self, certificate: CourseCompletionCertificateData) -> None:
        if certificate.certificate_type != COURSE_COMPLETION_CERTIFICATE_TYPE:
            raise CertificateServiceError("only course-completion certificates are supported")
        if certificate.id in self.certificates:
            raise CertificateStateConflictError("certificate records are immutable")
        if (
            self.get_certificate(
                certificate.tenant_id,
                certificate.person_id,
                certificate.program_id,
                certificate.program_version_id,
            )
            is not None
        ):
            raise CertificateStateConflictError("course-completion certificate already exists")
        snapshot = self.snapshots.get(certificate.original_completion_snapshot_id)
        if snapshot is None:
            raise CertificateStateConflictError("original completion snapshot does not exist")
        _require_same_scope(certificate, snapshot)
        _require_same_version(certificate, snapshot)
        _require_same_identity(certificate, snapshot)
        self.certificates[certificate.id] = certificate

    def append_event(self, event: CertificateEventData) -> CertificateEventData:
        _validate_event_request_digest(event)
        if event.id in self.events:
            raise CertificateStateConflictError("certificate events are append-only")
        certificate = self.certificates.get(event.certificate_id)
        if certificate is None:
            raise CertificateNotFoundError("certificate does not exist")
        _require_same_scope(certificate, event)
        _require_same_version(certificate, event)
        _require_same_identity(certificate, event)
        if event.completion_snapshot_id is not None:
            snapshot = self.snapshots.get(event.completion_snapshot_id)
            if snapshot is None:
                raise CertificateStateConflictError("event completion snapshot does not exist")
            _require_same_scope(certificate, snapshot)
            _require_same_version(certificate, snapshot)
            _require_same_identity(certificate, snapshot)
        existing_key = (
            self.get_event_by_idempotency_key(event.certificate_id, event.idempotency_key)
            if event.idempotency_key is not None
            else None
        )
        if existing_key is not None:
            if existing_key.request_digest == event.request_digest:
                return existing_key
            raise CertificateIdempotencyConflictError(
                "certificate event idempotency key was reused for another request"
            )
        order = self._event_order.setdefault(event.certificate_id, [])
        latest = self.events[order[-1]] if order else None
        if latest is None:
            if event.event_type is not CertificateEventType.ISSUED:
                raise CertificateStateConflictError("a certificate chain must start with issued")
            if event.supersedes_event_id is not None:
                raise CertificateStateConflictError(
                    "the issued event cannot supersede another event"
                )
        elif event.supersedes_event_id != latest.id:
            raise CertificateStateConflictError(
                "event does not supersede the current certificate state"
            )
        if event.sequence_no is None:
            event = dataclass_replace(event, sequence_no=len(order) + 1)
        elif event.sequence_no != len(order) + 1:
            raise CertificateStateConflictError("certificate event sequence is not append-only")
        self.events[event.id] = event
        order.append(event.id)
        return event

    def get_event_by_id(self, event_id: UUID) -> CertificateEventData | None:
        return self.events.get(event_id)

    def get_latest_event(self, certificate_id: UUID) -> CertificateEventData | None:
        order = self._event_order.get(certificate_id, [])
        return self.events[order[-1]] if order else None

    def get_event_by_idempotency_key(
        self, certificate_id: UUID, idempotency_key: str
    ) -> CertificateEventData | None:
        return next(
            (
                event
                for event in self.events.values()
                if (
                    event.certificate_id == certificate_id
                    and event.idempotency_key == idempotency_key
                )
            ),
            None,
        )

    def list_events(self, certificate_id: UUID) -> Sequence[CertificateEventData]:
        return tuple(
            self.events[event_id] for event_id in self._event_order.get(certificate_id, [])
        )


def _snapshot_from_record(row: CompletionSnapshotRecord) -> CompletionSnapshot:
    module_results = tuple(
        ModuleCompletion(
            module_id=UUID(str(item["module_id"])),
            prerequisite_module_ids=tuple(
                UUID(str(value)) for value in item["prerequisite_module_ids"]
            ),
            required_activity_ids=tuple(
                UUID(str(value)) for value in item["required_activity_ids"]
            ),
            completed_activity_ids=tuple(
                UUID(str(value)) for value in item["completed_activity_ids"]
            ),
            prerequisites_satisfied=bool(item["prerequisites_satisfied"]),
            is_complete=bool(item["is_complete"]),
        )
        for item in row.module_results
    )
    return CompletionSnapshot(
        id=row.id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_id=row.program_id,
        program_version_id=row.program_version_id,
        program_scope=row.program_scope,
        program_tenant_id=row.program_tenant_id,
        program_owner_key=row.program_owner_key,
        predicate_version=row.predicate_version,
        required_activity_ids=tuple(UUID(str(value)) for value in row.required_activity_ids),
        completed_activity_ids=tuple(UUID(str(value)) for value in row.completed_activity_ids),
        module_results=module_results,
        required_activity_count=row.required_activity_count,
        completed_activity_count=row.completed_activity_count,
        is_complete=row.is_complete,
        captured_at=_as_utc(row.captured_at),
        supersedes_snapshot_id=row.supersedes_snapshot_id,
        snapshot_hash=row.snapshot_hash,
    )


def _certificate_from_record(row: CourseCompletionCertificate) -> CourseCompletionCertificateData:
    return CourseCompletionCertificateData(
        id=row.id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        enrollment_id=row.enrollment_id,
        program_id=row.program_id,
        program_version_id=row.program_version_id,
        program_scope=row.program_scope,
        program_tenant_id=row.program_tenant_id,
        program_owner_key=row.program_owner_key,
        certificate_type=row.certificate_type,
        original_completion_snapshot_id=row.original_completion_snapshot_id,
        issued_at=_as_utc(row.issued_at),
        created_at=_as_utc(row.created_at),
        idempotency_key=row.idempotency_key,
    )


def _event_from_record(row: CertificateEvent) -> CertificateEventData:
    return CertificateEventData(
        id=row.id,
        certificate_id=row.certificate_id,
        tenant_id=row.tenant_id,
        person_id=row.person_id,
        event_type=CertificateEventType(row.event_type),
        completion_snapshot_id=row.completion_snapshot_id,
        supersedes_event_id=row.supersedes_event_id,
        actor_person_id=row.actor_person_id,
        reason=row.reason,
        provenance=row.provenance,
        occurred_at=_as_utc(row.occurred_at),
        idempotency_key=row.idempotency_key,
        request_digest=row.request_digest,
        sequence_no=row.sequence_no,
        enrollment_id=row.enrollment_id,
        program_id=row.program_id,
        program_version_id=row.program_version_id,
        program_scope=row.program_scope,
        program_tenant_id=row.program_tenant_id,
        program_owner_key=row.program_owner_key,
    )


class SqlAlchemyCertificateRepository:
    """Durable certificate store and authority backed by one sync SQL UoW."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_certificate(
        self,
        tenant_id: UUID,
        person_id: UUID,
        program_id: UUID,
        program_version_id: UUID,
    ) -> CourseCompletionCertificateData | None:
        row = self._session.scalar(
            select(CourseCompletionCertificate).where(
                CourseCompletionCertificate.tenant_id == tenant_id,
                CourseCompletionCertificate.person_id == person_id,
                CourseCompletionCertificate.program_id == program_id,
                CourseCompletionCertificate.program_version_id == program_version_id,
            )
        )
        return _certificate_from_record(row) if row is not None else None

    def get_certificate_by_id(self, certificate_id: UUID) -> CourseCompletionCertificateData | None:
        row = self._session.get(CourseCompletionCertificate, certificate_id)
        return _certificate_from_record(row) if row is not None else None

    def lock_certificate(self, certificate_id: UUID) -> CourseCompletionCertificateData | None:
        row = self._session.scalar(
            select(CourseCompletionCertificate)
            .where(CourseCompletionCertificate.id == certificate_id)
            .with_for_update()
        )
        return _certificate_from_record(row) if row is not None else None

    def save_snapshot(self, snapshot: CompletionSnapshot) -> None:
        _require_durable_snapshot(snapshot)
        if snapshot.computed_snapshot_hash != snapshot.snapshot_hash:
            raise CertificateSnapshotIntegrityError("snapshot hash does not match snapshot facts")
        row = CompletionSnapshotRecord(
            id=snapshot.id,
            tenant_id=snapshot.tenant_id,
            person_id=snapshot.person_id,
            enrollment_id=cast(UUID, snapshot.enrollment_id),
            program_id=snapshot.program_id,
            program_version_id=snapshot.program_version_id,
            program_scope=snapshot.program_scope,
            program_tenant_id=snapshot.program_tenant_id,
            program_owner_key=cast(UUID, snapshot.program_owner_key),
            predicate_version=snapshot.predicate_version,
            required_activity_count=snapshot.required_activity_count,
            completed_activity_count=snapshot.completed_activity_count,
            is_complete=snapshot.is_complete,
            required_activity_ids=[str(value) for value in snapshot.required_activity_ids],
            completed_activity_ids=[str(value) for value in snapshot.completed_activity_ids],
            module_results=[
                {
                    "module_id": str(module.module_id),
                    "prerequisite_module_ids": [
                        str(value) for value in module.prerequisite_module_ids
                    ],
                    "required_activity_ids": [str(value) for value in module.required_activity_ids],
                    "completed_activity_ids": [
                        str(value) for value in module.completed_activity_ids
                    ],
                    "prerequisites_satisfied": module.prerequisites_satisfied,
                    "is_complete": module.is_complete,
                }
                for module in snapshot.module_results
            ],
            snapshot_hash=snapshot.snapshot_hash,
            captured_at=snapshot.captured_at,
            supersedes_snapshot_id=snapshot.supersedes_snapshot_id,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            existing = self._session.get(CompletionSnapshotRecord, snapshot.id)
            if existing is not None and existing.snapshot_hash == snapshot.snapshot_hash:
                return
            raise CertificateStateConflictError(
                "completion snapshot violates its immutable identity"
            ) from exc

    def get_snapshot(self, snapshot_id: UUID) -> CompletionSnapshot | None:
        row = self._session.get(CompletionSnapshotRecord, snapshot_id)
        return _snapshot_from_record(row) if row is not None else None

    def save_certificate(self, certificate: CourseCompletionCertificateData) -> None:
        _require_durable_certificate(certificate)
        row = CourseCompletionCertificate(
            id=certificate.id,
            tenant_id=certificate.tenant_id,
            person_id=certificate.person_id,
            enrollment_id=cast(UUID, certificate.enrollment_id),
            program_id=certificate.program_id,
            program_version_id=certificate.program_version_id,
            program_scope=certificate.program_scope,
            program_tenant_id=certificate.program_tenant_id,
            program_owner_key=certificate.program_owner_key,
            certificate_type=certificate.certificate_type,
            original_completion_snapshot_id=certificate.original_completion_snapshot_id,
            idempotency_key=certificate.idempotency_key,
            issued_at=certificate.issued_at,
            created_at=certificate.created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            raise CertificateStateConflictError("certificate identity already exists") from exc

    def append_event(self, event: CertificateEventData) -> CertificateEventData:
        _validate_event_request_digest(event)
        certificate_row = self._session.scalar(
            select(CourseCompletionCertificate)
            .where(CourseCompletionCertificate.id == event.certificate_id)
            .with_for_update()
        )
        if certificate_row is None:
            raise CertificateNotFoundError("certificate does not exist")
        certificate = _certificate_from_record(certificate_row)
        _require_same_scope(certificate, event)
        _require_same_version(certificate, event)
        _require_same_identity(certificate, event)
        if event.idempotency_key is not None:
            existing = self._session.scalar(
                select(CertificateEvent).where(
                    CertificateEvent.certificate_id == event.certificate_id,
                    CertificateEvent.idempotency_key == event.idempotency_key,
                )
            )
            if existing is not None:
                existing_data = _event_from_record(existing)
                if existing_data.request_digest == event.request_digest:
                    return existing_data
                raise CertificateIdempotencyConflictError(
                    "certificate event idempotency key was reused for another request"
                )
        latest_row = self._session.scalar(
            select(CertificateEvent)
            .where(CertificateEvent.certificate_id == event.certificate_id)
            .order_by(CertificateEvent.sequence_no.desc())
            .with_for_update()
        )
        latest = _event_from_record(latest_row) if latest_row is not None else None
        if latest is None:
            if (
                event.event_type is not CertificateEventType.ISSUED
                or event.supersedes_event_id is not None
            ):
                raise CertificateStateConflictError("a certificate chain must start with issued")
            sequence_no = 1
        else:
            if event.supersedes_event_id != latest.id:
                raise CertificateStateConflictError(
                    "event does not supersede the current certificate state"
                )
            sequence_no = (latest.sequence_no or 0) + 1
        if event.sequence_no is not None and event.sequence_no != sequence_no:
            raise CertificateStateConflictError("certificate event sequence is not append-only")
        row = CertificateEvent(
            id=event.id,
            certificate_id=event.certificate_id,
            tenant_id=event.tenant_id,
            person_id=event.person_id,
            enrollment_id=cast(UUID, event.enrollment_id),
            program_id=cast(UUID, event.program_id),
            program_version_id=cast(UUID, event.program_version_id),
            program_scope=event.program_scope,
            program_tenant_id=event.program_tenant_id,
            program_owner_key=cast(UUID, event.program_owner_key),
            sequence_no=sequence_no,
            event_type=event.event_type.value,
            completion_snapshot_id=event.completion_snapshot_id,
            supersedes_event_id=event.supersedes_event_id,
            actor_person_id=event.actor_person_id,
            reason=event.reason,
            provenance=dict(event.provenance),
            idempotency_key=event.idempotency_key,
            request_digest=cast(str, event.request_digest),
            occurred_at=event.occurred_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as exc:
            if event.idempotency_key is not None:
                existing = self._session.scalar(
                    select(CertificateEvent).where(
                        CertificateEvent.certificate_id == event.certificate_id,
                        CertificateEvent.idempotency_key == event.idempotency_key,
                    )
                )
                if existing is not None:
                    existing_data = _event_from_record(existing)
                    if existing_data.request_digest == event.request_digest:
                        return existing_data
                    raise CertificateIdempotencyConflictError(
                        "certificate event idempotency key was reused for another request"
                    ) from exc
            raise CertificateStateConflictError("certificate event append conflicted") from exc
        return _event_from_record(row)

    def get_event_by_id(self, event_id: UUID) -> CertificateEventData | None:
        row = self._session.get(CertificateEvent, event_id)
        return _event_from_record(row) if row is not None else None

    def get_latest_event(self, certificate_id: UUID) -> CertificateEventData | None:
        row = self._session.scalar(
            select(CertificateEvent)
            .where(CertificateEvent.certificate_id == certificate_id)
            .order_by(CertificateEvent.sequence_no.desc())
        )
        return _event_from_record(row) if row is not None else None

    def get_event_by_idempotency_key(
        self, certificate_id: UUID, idempotency_key: str
    ) -> CertificateEventData | None:
        row = self._session.scalar(
            select(CertificateEvent).where(
                CertificateEvent.certificate_id == certificate_id,
                CertificateEvent.idempotency_key == idempotency_key,
            )
        )
        return _event_from_record(row) if row is not None else None

    def load_active_entitlement(
        self,
        *,
        tenant_id: UUID,
        person_id: UUID,
        program_version_id: UUID,
        enrollment_id: UUID | None = None,
    ) -> ActiveEntitlementSnapshot | None:
        from ac_platform.enrollment.models import Enrollment

        row = self._session.scalar(
            select(Entitlement)
            .join(Enrollment, Enrollment.id == Entitlement.enrollment_id)
            .where(
                Entitlement.tenant_id == tenant_id,
                Entitlement.person_id == person_id,
                Entitlement.program_version_id == program_version_id,
                Entitlement.status == EntitlementStatus.ACTIVE.value,
                Enrollment.status == EnrollmentStatus.ACTIVE.value,
                *(
                    [Entitlement.enrollment_id == enrollment_id]
                    if enrollment_id is not None
                    else []
                ),
            )
            .with_for_update()
        )
        if row is None:
            return None
        return ActiveEntitlementSnapshot(
            tenant_id=row.tenant_id,
            person_id=row.person_id,
            enrollment_id=row.enrollment_id,
            program_id=row.program_id,
            program_version_id=row.program_version_id,
            program_scope=row.program_scope,
            program_tenant_id=row.program_tenant_id,
            program_owner_key=row.program_owner_key,
        )

    def load_immutable_program_version(
        self,
        *,
        program_id: UUID,
        program_version_id: UUID,
        program_scope: str,
        program_owner_key: UUID,
    ) -> ImmutableProgramVersionSnapshot | None:
        from ac_platform.catalog.models import IMMUTABLE_VERSION_STATUSES, ProgramVersion

        row = self._session.scalar(
            select(ProgramVersion)
            .where(
                ProgramVersion.id == program_version_id,
                ProgramVersion.program_id == program_id,
                ProgramVersion.scope == program_scope,
                ProgramVersion.owner_key == program_owner_key,
                ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES),
            )
            .with_for_update()
        )
        if row is None:
            return None
        return ImmutableProgramVersionSnapshot(
            program_id=row.program_id,
            program_version_id=row.id,
            program_scope=row.scope,
            program_tenant_id=row.tenant_id,
            program_owner_key=row.owner_key,
            published=row.status in IMMUTABLE_VERSION_STATUSES,
            immutable=row.status in IMMUTABLE_VERSION_STATUSES,
        )

    def load_authoritative_progress(
        self,
        entitlement: ActiveEntitlementSnapshot,
        version: ImmutableProgramVersionSnapshot,
    ) -> PinnedCourseVersion | None:
        from ac_platform.catalog.models import Activity, Module, ModulePrerequisite
        from ac_platform.learning.models import ActivityProgress, ActivityState
        from ac_platform.learning.services import (
            ActivityDefinition,
            SqlAlchemyLearningRepository,
            authoritative_progress,
        )

        modules = list(
            self._session.scalars(
                select(Module)
                .where(
                    Module.program_version_id == version.program_version_id,
                    Module.program_id == version.program_id,
                    Module.scope == version.program_scope,
                    Module.owner_key == version.program_owner_key,
                )
                .order_by(Module.position.asc(), Module.id.asc())
                .with_for_update()
            ).all()
        )
        activities = list(
            self._session.scalars(
                select(Activity)
                .where(
                    Activity.program_version_id == version.program_version_id,
                    Activity.program_id == version.program_id,
                    Activity.scope == version.program_scope,
                    Activity.owner_key == version.program_owner_key,
                )
                .order_by(Activity.position.asc(), Activity.id.asc())
                .with_for_update()
            ).all()
        )
        edges = list(
            self._session.scalars(
                select(ModulePrerequisite)
                .where(
                    ModulePrerequisite.program_version_id == version.program_version_id,
                    ModulePrerequisite.program_id == version.program_id,
                    ModulePrerequisite.scope == version.program_scope,
                    ModulePrerequisite.owner_key == version.program_owner_key,
                )
                .with_for_update()
            ).all()
        )
        _locked_progress = self._session.scalars(
            select(ActivityProgress)
            .where(
                ActivityProgress.tenant_id == entitlement.tenant_id,
                ActivityProgress.person_id == entitlement.person_id,
                ActivityProgress.enrollment_id == entitlement.enrollment_id,
                ActivityProgress.program_version_id == entitlement.program_version_id,
            )
            .with_for_update()
        ).all()
        # Completion is a derived fact, not a trusted value on the mutable
        # progress row.  Reuse the learner evidence authority so certificate
        # issuance requires the same pinned activity version and
        # evidence/submission/review (or playback) chain as learner reads.
        completed_ids: set[UUID] = set()
        if activities:

            def activity_definition(row: object, _version: object) -> ActivityDefinition:
                return ActivityDefinition(
                    id=row.id,  # type: ignore[attr-defined]
                    kind=row.kind,  # type: ignore[attr-defined]
                    module_id=row.module_id,  # type: ignore[attr-defined]
                    program_version_id=row.program_version_id,  # type: ignore[attr-defined]
                    program_id=row.program_id,  # type: ignore[attr-defined]
                    program_scope=row.scope,  # type: ignore[attr-defined]
                    program_owner_key=row.owner_key,  # type: ignore[attr-defined]
                    title=row.title,  # type: ignore[attr-defined]
                    order=row.position,  # type: ignore[attr-defined]
                    required=row.is_required,  # type: ignore[attr-defined]
                    version=f"activity:{row.id}",  # type: ignore[attr-defined]
                    tenant_id=row.tenant_id,  # type: ignore[attr-defined]
                )

            learning_repository = SqlAlchemyLearningRepository(
                self._session,
                activity_resolver=activity_definition,
                reviewer_resolver=lambda _access: None,
            )
            try:
                access = learning_repository.resolve_scope(
                    tenant_id=entitlement.tenant_id,
                    person_id=entitlement.person_id,
                    enrollment_id=entitlement.enrollment_id,
                    program_version_id=entitlement.program_version_id,
                    activity_id=activities[0].id,
                )
                validated_progress = authoritative_progress(learning_repository, access)
            except DomainError:
                # A malformed or no-longer-authorized learner scope must fail
                # closed for issuance.  The caller turns ``None`` into the
                # existing authoritative-progress gate.
                return None
            completed_ids = {
                item.activity_id
                for item in validated_progress.values()
                if item.state is ActivityState.COMPLETED
            }
        prerequisites: dict[UUID, list[UUID]] = {module.id: [] for module in modules}
        for edge in edges:
            prerequisites.setdefault(edge.module_id, []).append(edge.prerequisite_module_id)
        module_definitions = tuple(
            ModuleDefinition(
                module_id=module.id,
                prerequisite_module_ids=tuple(prerequisites.get(module.id, ())),
            )
            for module in modules
        )
        activity_completions = tuple(
            ActivityCompletion(
                activity_id=activity.id,
                module_id=activity.module_id,
                required=activity.is_required,
                completed=activity.id in completed_ids,
            )
            for activity in activities
        )
        return PinnedCourseVersion(
            tenant_id=entitlement.tenant_id,
            person_id=entitlement.person_id,
            program_id=entitlement.program_id,
            program_version_id=entitlement.program_version_id,
            modules=module_definitions,
            activities=activity_completions,
            enrollment_id=entitlement.enrollment_id,
            program_scope=entitlement.program_scope,
            program_tenant_id=entitlement.program_tenant_id,
            program_owner_key=entitlement.program_owner_key,
        )

    def has_active_permission(
        self, *, actor_person_id: UUID, tenant_id: UUID, permission: str
    ) -> bool:
        if permission not in {CERTIFICATE_CORRECT_PERMISSION, CERTIFICATE_REVOKE_PERMISSION}:
            return False
        person = self._session.scalar(
            select(Person).where(Person.id == actor_person_id).with_for_update()
        )
        tenant = self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = self._session.scalar(
            select(Membership)
            .where(
                Membership.person_id == actor_person_id,
                Membership.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        return bool(
            person is not None
            and person.status == PersonStatus.ACTIVE.value
            and tenant is not None
            and tenant.status == TenantStatus.ACTIVE.value
            and membership is not None
            and membership.role in {"admin", "owner"}
            and membership.status == MembershipStatus.ACTIVE.value
            and membership.ended_at is None
        )


class SqlAlchemyCertificateUnitOfWork:
    """Certificate UoW over one explicit caller-owned AsyncSession transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit_repository = AuditRepository(session)
        self.outbox_repository = OutboxRepository(session)
        self._committed = False

    async def __aenter__(self) -> SqlAlchemyCertificateUnitOfWork:
        transaction = self.session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CertificateTransactionRequiredError(
                "certificate commands require an explicit caller-owned AsyncSession transaction"
            )
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_type, exc_value, traceback

    async def run_sync(self, operation: Callable[[Session], Any]) -> Any:
        return await self.session.run_sync(operation)

    async def commit(self) -> None:
        await self.session.flush()
        self._committed = True

    async def rollback(self) -> None:
        self._committed = False


def _require_same_scope(left: Any, right: Any) -> None:
    if left.tenant_id != right.tenant_id or left.person_id != right.person_id:
        raise CertificateScopeMismatchError("certificate data crosses a tenant or person boundary")


def _require_same_version(left: Any, right: Any) -> None:
    if left.program_id != right.program_id or left.program_version_id != right.program_version_id:
        raise CertificateScopeMismatchError(
            "certificate data crosses a program or pinned version boundary"
        )


def _require_same_identity(left: Any, right: Any) -> None:
    """Check the complete enrollment/catalog owner identity when present."""

    left_enrollment = getattr(left, "enrollment_id", None)
    right_enrollment = getattr(right, "enrollment_id", None)
    if (left_enrollment is not None or right_enrollment is not None) and (
        left_enrollment != right_enrollment
    ):
        raise CertificateScopeMismatchError("certificate data crosses an enrollment boundary")
    for attribute in ("program_scope", "program_tenant_id", "program_owner_key"):
        left_value = getattr(left, attribute, None)
        right_value = getattr(right, attribute, None)
        if left_value is not None and right_value is not None and left_value != right_value:
            raise CertificateScopeMismatchError("certificate data crosses a catalog owner boundary")


def _require_durable_snapshot(snapshot: CompletionSnapshot) -> None:
    if snapshot.enrollment_id is None or snapshot.program_owner_key is None:
        raise CertificateScopeMismatchError(
            "durable certificate snapshots require enrollment and catalog owner identity"
        )


def _require_durable_certificate(certificate: CourseCompletionCertificateData) -> None:
    if certificate.enrollment_id is None or certificate.program_owner_key is None:
        raise CertificateScopeMismatchError(
            "durable certificates require enrollment and catalog owner identity"
        )


def _issue_request_digest(
    certificate: CourseCompletionCertificateData,
    snapshot: CompletionSnapshot,
    idempotency_key: str | None,
) -> str:
    return _hash_request(
        {
            "operation": "certificate_issue",
            "tenant_id": str(certificate.tenant_id),
            "person_id": str(certificate.person_id),
            "enrollment_id": str(certificate.enrollment_id),
            "program_id": str(certificate.program_id),
            "program_version_id": str(certificate.program_version_id),
            "program_scope": certificate.program_scope,
            "program_owner_key": str(certificate.program_owner_key),
            "snapshot_hash": snapshot.snapshot_hash,
            "idempotency_key": idempotency_key,
        }
    )


def _change_request_digest(
    *,
    operation: str,
    certificate: CourseCompletionCertificateData,
    actor_person_id: UUID,
    subject_person_id: UUID,
    reason: str,
    provenance: Mapping[str, Any],
    completion: CompletionSnapshot | None,
    idempotency_key: str | None,
) -> str:
    return _hash_request(
        {
            "operation": operation,
            "certificate_id": str(certificate.id),
            "tenant_id": str(certificate.tenant_id),
            "person_id": str(certificate.person_id),
            "enrollment_id": str(certificate.enrollment_id),
            "program_id": str(certificate.program_id),
            "program_version_id": str(certificate.program_version_id),
            "program_scope": certificate.program_scope,
            "program_owner_key": str(certificate.program_owner_key),
            "actor_person_id": str(actor_person_id),
            "subject_person_id": str(subject_person_id),
            "reason": reason,
            "provenance": dict(provenance),
            "snapshot_hash": completion.snapshot_hash if completion is not None else None,
            "idempotency_key": idempotency_key,
        }
    )


def _hash_request(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class CourseCompletionCertificateService:
    """Issue, read, correct, and revoke immutable course-completion records."""

    def __init__(
        self,
        store: CertificateStore,
        clock: Callable[[], datetime] | None = None,
        authority: CertificateAuthority | None = None,
        permission_checker: Callable[[UUID, UUID, str], bool] | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        candidate = authority or store
        self._authority = (
            cast(CertificateAuthority, candidate)
            if all(
                callable(getattr(candidate, name, None))
                for name in (
                    "load_active_entitlement",
                    "load_immutable_program_version",
                    "load_authoritative_progress",
                )
            )
            else None
        )
        self._permission_checker = permission_checker

    def issue(
        self,
        completion: CompletionSnapshot | None = None,
        *,
        tenant_id: UUID | None = None,
        person_id: UUID | None = None,
        program_id: UUID | None = None,
        program_version_id: UUID | None = None,
        enrollment_id: UUID | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> CertificateIssueResult:
        """Issue from server-owned entitlement, version, and progress facts."""

        requested_tenant = tenant_id or (completion.tenant_id if completion is not None else None)
        requested_person = person_id or (completion.person_id if completion is not None else None)
        requested_program = program_id or (
            completion.program_id if completion is not None else None
        )
        requested_version = program_version_id or (
            completion.program_version_id if completion is not None else None
        )
        requested_enrollment = enrollment_id or (
            completion.enrollment_id if completion is not None else None
        )
        if None in {
            requested_tenant,
            requested_person,
            requested_program,
            requested_version,
            requested_enrollment,
        }:
            raise CertificateAuthorityRequiredError(
                "certificate issuance requires tenant, subject, enrollment, and version identity"
            )
        if self._authority is None:
            raise CertificateAuthorityRequiredError(
                "certificate issuance requires an authority-backed repository"
            )
        authority = self._authority
        entitlement = authority.load_active_entitlement(
            tenant_id=cast(UUID, requested_tenant),
            person_id=cast(UUID, requested_person),
            program_version_id=cast(UUID, requested_version),
            enrollment_id=cast(UUID, requested_enrollment),
        )
        if entitlement is None:
            raise ActiveEntitlementRequiredError("an active entitlement is required for issuance")
        if (
            entitlement.program_id != requested_program
            or entitlement.program_version_id != requested_version
            or entitlement.enrollment_id != requested_enrollment
        ):
            raise CertificateScopeMismatchError("entitlement identity does not match the request")
        version = authority.load_immutable_program_version(
            program_id=entitlement.program_id,
            program_version_id=entitlement.program_version_id,
            program_scope=entitlement.program_scope,
            program_owner_key=entitlement.program_owner_key,
        )
        if version is None or not version.published or not version.immutable:
            raise ImmutableProgramVersionRequiredError(
                "issuance requires the immutable published catalog version"
            )
        if (
            version.program_id != entitlement.program_id
            or version.program_version_id != entitlement.program_version_id
            or version.program_scope != entitlement.program_scope
            or version.program_owner_key != entitlement.program_owner_key
        ):
            raise CertificateScopeMismatchError(
                "catalog version identity does not match entitlement"
            )
        captured_at = _now(now or self._clock())
        pinned = authority.load_authoritative_progress(entitlement, version)
        if pinned is None:
            raise AuthoritativeProgressRequiredError(
                "authoritative course progress is required for issuance"
            )
        if (
            pinned.tenant_id != entitlement.tenant_id
            or pinned.person_id != entitlement.person_id
            or pinned.enrollment_id != entitlement.enrollment_id
            or pinned.program_id != entitlement.program_id
            or pinned.program_version_id != entitlement.program_version_id
            or pinned.program_scope != entitlement.program_scope
            or pinned.program_owner_key != entitlement.program_owner_key
        ):
            raise CertificateScopeMismatchError(
                "authoritative progress crosses the entitlement scope"
            )
        evaluated = evaluate_course_completion(pinned, now=captured_at)
        _require_complete(evaluated)
        if completion is not None:
            if (
                completion.canonical_payload() != evaluated.canonical_payload()
                or completion.snapshot_hash != evaluated.snapshot_hash
            ):
                raise CertificateSnapshotIntegrityError(
                    "caller completion facts do not match authoritative server evaluation"
                )
            completion = dataclass_replace(evaluated, id=completion.id)
        else:
            completion = evaluated
        normalized_key = (
            _required_text(idempotency_key, "idempotency_key", 200)
            if idempotency_key is not None
            else None
        )
        existing = self._store.get_certificate(
            completion.tenant_id,
            completion.person_id,
            completion.program_id,
            completion.program_version_id,
        )
        if existing is not None:
            issued_event = self._store.get_latest_event(existing.id)
            if issued_event is None:
                raise CertificateStateConflictError("certificate has no issued event")
            first_event = issued_event
            while first_event.supersedes_event_id is not None:
                previous = self._store.get_event_by_id(first_event.supersedes_event_id)
                if previous is None:
                    raise CertificateStateConflictError("certificate event chain is incomplete")
                first_event = previous
            if existing.idempotency_key != normalized_key:
                raise CertificateStateConflictError(
                    "certificate identity already exists under another idempotency key"
                )
            expected_event = _issued_event(
                existing,
                completion,
                captured_at=captured_at,
                idempotency_key=normalized_key,
            )
            if first_event.request_digest != expected_event.request_digest:
                raise CertificateIdempotencyConflictError(
                    "certificate issue idempotency key was reused for another request"
                )
            return CertificateIssueResult(
                certificate=existing,
                event=first_event,
                created=False,
            )

        certificate = CourseCompletionCertificateData(
            id=uuid4(),
            tenant_id=completion.tenant_id,
            person_id=completion.person_id,
            enrollment_id=completion.enrollment_id,
            program_id=completion.program_id,
            program_version_id=completion.program_version_id,
            program_scope=completion.program_scope,
            program_tenant_id=completion.program_tenant_id,
            program_owner_key=completion.program_owner_key,
            certificate_type=COURSE_COMPLETION_CERTIFICATE_TYPE,
            original_completion_snapshot_id=completion.id,
            issued_at=captured_at,
            created_at=captured_at,
            idempotency_key=normalized_key,
        )
        issued_event = _issued_event(
            certificate,
            completion,
            captured_at=captured_at,
            idempotency_key=normalized_key,
        )
        self._store.save_snapshot(completion)
        self._store.save_certificate(certificate)
        appended = self._store.append_event(issued_event)
        return CertificateIssueResult(
            certificate=certificate,
            event=appended or issued_event,
            created=True,
        )

    def read(
        self,
        certificate_id: UUID,
        *,
        actor_person_id: UUID,
        tenant_id: UUID,
    ) -> CertificateView:
        certificate = self._store.get_certificate_by_id(certificate_id)
        if certificate is None:
            raise CertificateNotFoundError("certificate does not exist")
        if certificate.person_id != actor_person_id or certificate.tenant_id != tenant_id:
            raise CertificateScopeMismatchError(
                "certificate is outside the actor's tenant and person scope"
            )
        return self._view(certificate)

    def correct(
        self,
        certificate_id: UUID,
        corrected_completion: CompletionSnapshot | None = None,
        *,
        actor_person_id: UUID,
        tenant_id: UUID,
        subject_person_id: UUID | None = None,
        reason: str,
        provenance: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> CertificateEventData:
        """Append a corrected snapshot while retaining the original snapshot."""

        certificate = self._require_actor_tenant(certificate_id, actor_person_id, tenant_id)
        self._authorize_change(
            certificate,
            actor_person_id=actor_person_id,
            tenant_id=tenant_id,
            subject_person_id=subject_person_id,
            permission=CERTIFICATE_CORRECT_PERMISSION,
        )
        latest = self._latest_for_change(certificate.id)
        if latest.event_type is CertificateEventType.REVOKED:
            raise CertificateAlreadyRevokedError("a revoked certificate cannot be corrected")
        captured_at = _now(now or self._clock())
        evaluated = self._authoritative_completion(
            certificate,
            captured_at=captured_at,
            require_complete=True,
        )
        if corrected_completion is not None and (
            corrected_completion.canonical_payload() != evaluated.canonical_payload()
            or corrected_completion.snapshot_hash != evaluated.snapshot_hash
        ):
            raise CertificateSnapshotIntegrityError(
                "caller correction facts do not match authoritative server evaluation"
            )
        corrected_completion = dataclass_replace(
            evaluated,
            id=(corrected_completion.id if corrected_completion is not None else evaluated.id),
            supersedes_snapshot_id=latest.completion_snapshot_id,
        )
        _require_same_scope(certificate, corrected_completion)
        _require_durable_snapshot(corrected_completion)
        normalized_reason = _required_text(reason, "reason", 500)
        normalized_key = (
            _required_text(idempotency_key, "idempotency_key", 200)
            if idempotency_key is not None
            else None
        )
        normalized_provenance = {
            **dict(provenance or {}),
            "source": "certificate-correction",
            "authoritative_snapshot_hash": corrected_completion.snapshot_hash,
        }
        correction = CertificateEventData(
            id=uuid4(),
            certificate_id=certificate.id,
            tenant_id=certificate.tenant_id,
            person_id=certificate.person_id,
            event_type=CertificateEventType.CORRECTED,
            completion_snapshot_id=corrected_completion.id,
            supersedes_event_id=latest.id,
            actor_person_id=actor_person_id,
            reason=normalized_reason,
            provenance=normalized_provenance,
            occurred_at=captured_at,
            idempotency_key=normalized_key,
            enrollment_id=certificate.enrollment_id,
            program_id=certificate.program_id,
            program_version_id=certificate.program_version_id,
            program_scope=certificate.program_scope,
            program_tenant_id=certificate.program_tenant_id,
            program_owner_key=certificate.program_owner_key,
            request_digest=None,
        )
        if normalized_key is not None:
            existing = self._store.get_event_by_idempotency_key(certificate.id, normalized_key)
            if existing is not None:
                if existing.request_digest != correction.request_digest:
                    raise CertificateIdempotencyConflictError(
                        "certificate correction idempotency key was reused for another request"
                    )
                return existing
        self._store.save_snapshot(corrected_completion)
        return self._store.append_event(correction) or correction

    def revoke(
        self,
        certificate_id: UUID,
        *,
        actor_person_id: UUID,
        tenant_id: UUID,
        subject_person_id: UUID | None = None,
        reason: str,
        provenance: Mapping[str, Any] | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> CertificateEventData:
        """Append a revocation event without modifying the original certificate."""

        certificate = self._require_actor_tenant(certificate_id, actor_person_id, tenant_id)
        self._authorize_change(
            certificate,
            actor_person_id=actor_person_id,
            tenant_id=tenant_id,
            subject_person_id=subject_person_id,
            permission=CERTIFICATE_REVOKE_PERMISSION,
        )
        latest = self._latest_for_change(certificate.id)
        captured_at = _now(now or self._clock())
        evaluated = self._authoritative_completion(
            certificate,
            captured_at=captured_at,
            require_complete=False,
        )
        normalized_reason = _required_text(reason, "reason", 500)
        normalized_key = (
            _required_text(idempotency_key, "idempotency_key", 200)
            if idempotency_key is not None
            else None
        )
        normalized_provenance = {
            **dict(provenance or {}),
            "source": "certificate-revocation",
            "authoritative_snapshot_hash": evaluated.snapshot_hash,
            "authoritative_complete": evaluated.is_complete,
        }
        revocation = CertificateEventData(
            id=uuid4(),
            certificate_id=certificate.id,
            tenant_id=certificate.tenant_id,
            person_id=certificate.person_id,
            event_type=CertificateEventType.REVOKED,
            completion_snapshot_id=None,
            supersedes_event_id=latest.id,
            actor_person_id=actor_person_id,
            reason=normalized_reason,
            provenance=normalized_provenance,
            occurred_at=captured_at,
            idempotency_key=normalized_key,
            enrollment_id=certificate.enrollment_id,
            program_id=certificate.program_id,
            program_version_id=certificate.program_version_id,
            program_scope=certificate.program_scope,
            program_tenant_id=certificate.program_tenant_id,
            program_owner_key=certificate.program_owner_key,
            request_digest=None,
        )
        if normalized_key is not None:
            existing = self._store.get_event_by_idempotency_key(certificate.id, normalized_key)
            if existing is not None:
                if existing.request_digest != revocation.request_digest:
                    raise CertificateIdempotencyConflictError(
                        "certificate revocation idempotency key was reused for another request"
                    )
                return existing
        if latest.event_type is CertificateEventType.REVOKED:
            return latest
        return self._store.append_event(revocation) or revocation

    def _require_actor_tenant(
        self, certificate_id: UUID, actor_person_id: UUID, tenant_id: UUID
    ) -> CourseCompletionCertificateData:
        certificate = self._store.lock_certificate(certificate_id)
        if certificate is None:
            raise CertificateNotFoundError("certificate does not exist")
        if certificate.tenant_id != tenant_id:
            raise CertificateScopeMismatchError("certificate is outside the selected tenant")
        if actor_person_id is None:
            raise CertificateScopeMismatchError("certificate changes require an attributable actor")
        return certificate

    def _authorize_change(
        self,
        certificate: CourseCompletionCertificateData,
        *,
        actor_person_id: UUID,
        tenant_id: UUID,
        subject_person_id: UUID | None,
        permission: str,
    ) -> UUID:
        if subject_person_id is None or subject_person_id != certificate.person_id:
            raise CertificateAuthorizationRequiredError(
                "certificate changes must explicitly identify the certificate subject"
            )
        checker = self._permission_checker
        if checker is None and self._authority is not None:
            authority_checker = getattr(self._authority, "has_active_permission", None)
            if callable(authority_checker):

                def authority_permission_checker(actor: UUID, tenant: UUID, action: str) -> bool:
                    return bool(
                        authority_checker(
                            actor_person_id=actor,
                            tenant_id=tenant,
                            permission=action,
                        )
                    )

                checker = authority_permission_checker
        if checker is None or not checker(actor_person_id, tenant_id, permission):
            raise CertificateAuthorizationRequiredError(
                "administrative certificate changes require authoritative active permission"
            )
        return subject_person_id

    def _authoritative_completion(
        self,
        certificate: CourseCompletionCertificateData,
        *,
        captured_at: datetime,
        require_complete: bool,
    ) -> CompletionSnapshot:
        authority = self._authority
        if authority is None:
            raise CertificateAuthorityRequiredError(
                "certificate changes require an authority-backed repository"
            )
        entitlement = authority.load_active_entitlement(
            tenant_id=certificate.tenant_id,
            person_id=certificate.person_id,
            program_version_id=certificate.program_version_id,
            enrollment_id=certificate.enrollment_id,
        )
        if entitlement is None:
            raise ActiveEntitlementRequiredError(
                "certificate changes require the active bound entitlement"
            )
        if (
            entitlement.enrollment_id != certificate.enrollment_id
            or entitlement.program_id != certificate.program_id
            or entitlement.program_scope != certificate.program_scope
            or entitlement.program_owner_key != certificate.program_owner_key
        ):
            raise CertificateScopeMismatchError(
                "certificate entitlement identity changed since issuance"
            )
        version = authority.load_immutable_program_version(
            program_id=certificate.program_id,
            program_version_id=certificate.program_version_id,
            program_scope=certificate.program_scope,
            program_owner_key=certificate.program_owner_key,
        )
        if version is None or not version.published or not version.immutable:
            raise ImmutableProgramVersionRequiredError(
                "certificate changes require the immutable issued catalog version"
            )
        pinned = authority.load_authoritative_progress(entitlement, version)
        if pinned is None:
            raise AuthoritativeProgressRequiredError(
                "certificate changes require authoritative course progress"
            )
        if (
            pinned.tenant_id != certificate.tenant_id
            or pinned.person_id != certificate.person_id
            or pinned.enrollment_id != certificate.enrollment_id
            or pinned.program_id != certificate.program_id
            or pinned.program_version_id != certificate.program_version_id
            or pinned.program_scope != certificate.program_scope
            or pinned.program_owner_key != certificate.program_owner_key
        ):
            raise CertificateScopeMismatchError(
                "authoritative progress crosses the issued certificate identity"
            )
        evaluated = evaluate_course_completion(pinned, now=captured_at)
        if require_complete:
            _require_complete(evaluated)
        return evaluated

    def _latest_for_change(self, certificate_id: UUID) -> CertificateEventData:
        latest = self._store.get_latest_event(certificate_id)
        if latest is None:
            raise CertificateStateConflictError("certificate has no current event")
        return latest

    def _view(self, certificate: CourseCompletionCertificateData) -> CertificateView:
        original = self._store.get_snapshot(certificate.original_completion_snapshot_id)
        latest = self._store.get_latest_event(certificate.id)
        if original is None or latest is None:
            raise CertificateStateConflictError("certificate evidence is incomplete")
        current = original
        event = latest
        visited_events: set[UUID] = set()
        while event.completion_snapshot_id is None and event.supersedes_event_id is not None:
            if event.id in visited_events:
                raise CertificateStateConflictError("certificate event chain contains a cycle")
            visited_events.add(event.id)
            previous = self._store.get_event_by_id(event.supersedes_event_id)
            if previous is None:
                raise CertificateStateConflictError("certificate event chain is incomplete")
            event = previous
        if event.completion_snapshot_id is not None:
            current_snapshot = self._store.get_snapshot(event.completion_snapshot_id)
            if current_snapshot is None:
                raise CertificateStateConflictError("current certificate snapshot is missing")
            current = current_snapshot
        return CertificateView(
            certificate=certificate,
            original_completion=original,
            current_completion=current,
            current_event=latest,
        )


class AsyncCertificateApplication:
    """Transactional certificate commands with authoritative locks and side effects."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        sync_transaction = None if transaction is None else transaction.sync_transaction
        if (
            sync_transaction is None
            or sync_transaction.origin is not SessionTransactionOrigin.BEGIN
        ):
            raise CertificateTransactionRequiredError(
                "certificate commands require an explicit caller-owned AsyncSession transaction"
            )

    async def _lock_actor(
        self,
        actor: ActorContext,
        *,
        tenant_id: UUID,
        subject_person_id: UUID,
        permission: str | None,
    ) -> None:
        if actor.tenant_id != tenant_id:
            raise CertificateAuthorizationRequiredError(
                "certificate command requires the selected tenant"
            )
        if permission is None:
            if actor.person_id != subject_person_id:
                raise CertificateAuthorizationRequiredError("certificate issuance is self-only")
        elif permission not in actor.permissions:
            raise CertificateAuthorizationRequiredError(
                f"certificate command requires {permission}"
            )
        person = await self._session.scalar(
            select(Person).where(Person.id == actor.person_id).with_for_update()
        )
        tenant = await self._session.scalar(
            select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        membership = await self._session.scalar(
            select(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.person_id == actor.person_id,
            )
            .with_for_update()
        )
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or tenant is None
            or tenant.status != TenantStatus.ACTIVE.value
            or membership is None
            or membership.status != MembershipStatus.ACTIVE.value
            or membership.ended_at is not None
        ):
            raise CertificateAuthorizationRequiredError(
                "certificate command requires an active canonical actor membership"
            )
        if permission is not None and membership.role not in {"admin", "owner"}:
            raise CertificateAuthorizationRequiredError(
                "certificate changes are restricted to active administrators"
            )

    async def _find_command(
        self,
        *,
        tenant_id: UUID,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
        for_update: bool,
    ) -> CertificateCommandIdempotency | None:
        statement = select(CertificateCommandIdempotency).where(
            CertificateCommandIdempotency.tenant_id == tenant_id,
            CertificateCommandIdempotency.actor_person_id == actor_person_id,
            CertificateCommandIdempotency.operation == operation,
            CertificateCommandIdempotency.idempotency_key == idempotency_key,
        )
        if for_update:
            statement = statement.with_for_update()
        return cast(
            CertificateCommandIdempotency | None,
            await self._session.scalar(statement),
        )

    async def _claim_command(
        self,
        command: CertificateCommandIdempotency,
    ) -> tuple[CertificateCommandIdempotency, bool]:
        existing = await self._find_command(
            tenant_id=command.tenant_id,
            actor_person_id=command.actor_person_id,
            operation=command.operation,
            idempotency_key=command.idempotency_key,
            for_update=True,
        )
        if existing is not None:
            return existing, False
        try:
            async with self._session.begin_nested():
                self._session.add(command)
                await self._session.flush()
        except IntegrityError as exc:
            existing = await self._find_command(
                tenant_id=command.tenant_id,
                actor_person_id=command.actor_person_id,
                operation=command.operation,
                idempotency_key=command.idempotency_key,
                for_update=True,
            )
            if existing is None:
                raise CertificateStateConflictError(
                    "certificate idempotency claim conflicted without a canonical row"
                ) from exc
            return existing, False
        return command, True

    async def _replay(
        self,
        command: CertificateCommandIdempotency,
        request_digest: str,
    ) -> tuple[
        CourseCompletionCertificateData,
        CompletionSnapshot | None,
        CertificateEventData,
    ]:
        if command.request_digest != request_digest:
            raise CertificateIdempotencyConflictError(
                "certificate idempotency key was reused for another canonical request"
            )
        if command.status == CertificateCommandStatus.PENDING.value:
            raise CertificateCommandInProgressError(
                "certificate command is owned by an unfinished transaction"
            )
        if (
            command.status != CertificateCommandStatus.COMPLETED.value
            or command.result_certificate_id is None
            or command.result_event_id is None
        ):
            raise CertificateStateConflictError(
                "completed certificate command has incomplete result identifiers"
            )
        certificate_row = await self._session.scalar(
            select(CourseCompletionCertificate).where(
                CourseCompletionCertificate.id == command.result_certificate_id,
                CourseCompletionCertificate.tenant_id == command.tenant_id,
                CourseCompletionCertificate.person_id == command.person_id,
                CourseCompletionCertificate.enrollment_id == command.enrollment_id,
                CourseCompletionCertificate.program_id == command.program_id,
                CourseCompletionCertificate.program_version_id == command.program_version_id,
                CourseCompletionCertificate.program_scope == command.program_scope,
                CourseCompletionCertificate.program_owner_key == command.program_owner_key,
            )
        )
        event_row = await self._session.scalar(
            select(CertificateEvent).where(
                CertificateEvent.id == command.result_event_id,
                CertificateEvent.certificate_id == command.result_certificate_id,
                CertificateEvent.tenant_id == command.tenant_id,
                CertificateEvent.person_id == command.person_id,
                CertificateEvent.enrollment_id == command.enrollment_id,
                CertificateEvent.program_id == command.program_id,
                CertificateEvent.program_version_id == command.program_version_id,
                CertificateEvent.program_scope == command.program_scope,
                CertificateEvent.program_owner_key == command.program_owner_key,
            )
        )
        snapshot: CompletionSnapshot | None = None
        if command.result_snapshot_id is not None:
            snapshot_row = await self._session.scalar(
                select(CompletionSnapshotRecord).where(
                    CompletionSnapshotRecord.id == command.result_snapshot_id,
                    CompletionSnapshotRecord.tenant_id == command.tenant_id,
                    CompletionSnapshotRecord.person_id == command.person_id,
                    CompletionSnapshotRecord.enrollment_id == command.enrollment_id,
                    CompletionSnapshotRecord.program_id == command.program_id,
                    CompletionSnapshotRecord.program_version_id == command.program_version_id,
                    CompletionSnapshotRecord.program_scope == command.program_scope,
                    CompletionSnapshotRecord.program_owner_key == command.program_owner_key,
                )
            )
            if snapshot_row is not None:
                snapshot = _snapshot_from_record(snapshot_row)
        if certificate_row is None or event_row is None:
            raise CertificateStateConflictError(
                "certificate command result identifiers do not resolve to their bound identity"
            )
        if command.operation != CERTIFICATE_REVOKE_OPERATION and snapshot is None:
            raise CertificateStateConflictError(
                "certificate command result snapshot does not resolve to its bound identity"
            )
        event = _event_from_record(event_row)
        expected_event_type = {
            CERTIFICATE_ISSUE_OPERATION: CertificateEventType.ISSUED,
            CERTIFICATE_CORRECT_OPERATION: CertificateEventType.CORRECTED,
            CERTIFICATE_REVOKE_OPERATION: CertificateEventType.REVOKED,
        }[command.operation]
        if event.event_type is not expected_event_type:
            raise CertificateStateConflictError(
                "certificate command result event has the wrong operation type"
            )
        return _certificate_from_record(certificate_row), snapshot, event

    @staticmethod
    def _new_command(
        *,
        actor_person_id: UUID,
        operation: str,
        idempotency_key: str,
        request_digest: str,
        identity: ActiveEntitlementSnapshot | CourseCompletionCertificateData,
    ) -> CertificateCommandIdempotency:
        return CertificateCommandIdempotency(
            id=uuid4(),
            tenant_id=identity.tenant_id,
            actor_person_id=actor_person_id,
            person_id=identity.person_id,
            enrollment_id=cast(UUID, identity.enrollment_id),
            program_id=identity.program_id,
            program_version_id=identity.program_version_id,
            program_scope=identity.program_scope,
            program_tenant_id=identity.program_tenant_id,
            program_owner_key=cast(UUID, identity.program_owner_key),
            operation=operation,
            idempotency_key=idempotency_key,
            request_digest=request_digest,
            status=CertificateCommandStatus.PENDING.value,
        )

    async def _record_side_effects(
        self,
        transaction: SqlAlchemyCertificateUnitOfWork,
        *,
        actor: ActorContext,
        command: CertificateCommandIdempotency,
        certificate: CourseCompletionCertificateData,
        event: CertificateEventData,
    ) -> None:
        action = f"audit.certificate.{event.event_type.value}.v1"
        payload = {
            "certificate_id": str(certificate.id),
            "certificate_event_id": str(event.id),
            "subject_person_id": str(certificate.person_id),
            "enrollment_id": str(certificate.enrollment_id),
            "program_id": str(certificate.program_id),
            "program_version_id": str(certificate.program_version_id),
            "command_idempotency_id": str(command.id),
        }
        await transaction.audit_repository.append(
            tenant_id=certificate.tenant_id,
            actor_person_id=actor.person_id,
            action=action,
            resource_type="course_completion_certificate",
            resource_id=certificate.id,
            payload=payload,
            session_id=actor.session_id,
            reason=event.reason,
            request_id=str(command.id),
            now=event.occurred_at,
        )
        await transaction.outbox_repository.enqueue(
            EventEnvelope(
                name=f"certificate.{event.event_type.value}.v1",
                category=EventCategory.DOMAIN_FACT,
                aggregate_type="course_completion_certificate",
                aggregate_id=certificate.id,
                tenant_id=certificate.tenant_id,
                payload=payload,
                occurred_at=event.occurred_at,
            ),
            dedupe_key=f"certificate-command:{command.id}",
        )

    async def issue(
        self,
        command: IssueCertificateCommand,
        *,
        actor: ActorContext,
    ) -> CertificateIssueResult:
        self._require_transaction()
        async with self._session.begin_nested():
            return await self._issue(command, actor=actor)

    async def _issue(
        self,
        command: IssueCertificateCommand,
        *,
        actor: ActorContext,
    ) -> CertificateIssueResult:
        self._require_transaction()
        normalized_key = _required_text(command.idempotency_key, "idempotency_key", 200)
        await self._lock_actor(
            actor,
            tenant_id=command.tenant_id,
            subject_person_id=command.person_id,
            permission=None,
        )
        transaction = SqlAlchemyCertificateUnitOfWork(self._session)
        async with transaction:

            def load_identity(sync_session: Session) -> ActiveEntitlementSnapshot | None:
                return SqlAlchemyCertificateRepository(sync_session).load_active_entitlement(
                    tenant_id=command.tenant_id,
                    person_id=command.person_id,
                    program_version_id=command.program_version_id,
                    enrollment_id=command.enrollment_id,
                )

            entitlement = cast(
                ActiveEntitlementSnapshot | None,
                await transaction.run_sync(load_identity),
            )
            if entitlement is None or entitlement.program_id != command.program_id:
                raise ActiveEntitlementRequiredError(
                    "certificate issuance requires the active canonical entitlement"
                )
            request_digest = _hash_request(
                {
                    "operation": CERTIFICATE_ISSUE_OPERATION,
                    "actor_person_id": str(actor.person_id),
                    "tenant_id": str(command.tenant_id),
                    "person_id": str(command.person_id),
                    "enrollment_id": str(command.enrollment_id),
                    "program_id": str(command.program_id),
                    "program_version_id": str(command.program_version_id),
                    "idempotency_key": normalized_key,
                }
            )
            claimed, created_claim = await self._claim_command(
                self._new_command(
                    actor_person_id=actor.person_id,
                    operation=CERTIFICATE_ISSUE_OPERATION,
                    idempotency_key=normalized_key,
                    request_digest=request_digest,
                    identity=entitlement,
                )
            )
            if not created_claim:
                certificate, _, event = await self._replay(claimed, request_digest)
                return CertificateIssueResult(certificate=certificate, event=event, created=False)

            def issue_sync(sync_session: Session) -> CertificateIssueResult:
                repository = SqlAlchemyCertificateRepository(sync_session)
                return CourseCompletionCertificateService(
                    repository,
                    clock=self._clock,
                    authority=repository,
                ).issue(
                    tenant_id=command.tenant_id,
                    person_id=command.person_id,
                    program_id=command.program_id,
                    program_version_id=command.program_version_id,
                    enrollment_id=command.enrollment_id,
                    idempotency_key=normalized_key,
                )

            result = cast(CertificateIssueResult, await transaction.run_sync(issue_sync))
            claimed.status = CertificateCommandStatus.COMPLETED.value
            claimed.result_certificate_id = result.certificate.id
            claimed.result_snapshot_id = result.certificate.original_completion_snapshot_id
            claimed.result_event_id = result.event.id
            claimed.completed_at = _now(self._clock())
            if result.created:
                await self._record_side_effects(
                    transaction,
                    actor=actor,
                    command=claimed,
                    certificate=result.certificate,
                    event=result.event,
                )
            await transaction.commit()
            return result

    async def correct(
        self,
        command: CorrectCertificateCommand,
        *,
        actor: ActorContext,
    ) -> CertificateEventData:
        self._require_transaction()
        async with self._session.begin_nested():
            return await self._change(
                command=command,
                actor=actor,
                operation=CERTIFICATE_CORRECT_OPERATION,
                permission=CERTIFICATE_CORRECT_PERMISSION,
            )

    async def revoke(
        self,
        command: RevokeCertificateCommand,
        *,
        actor: ActorContext,
    ) -> CertificateEventData:
        self._require_transaction()
        async with self._session.begin_nested():
            return await self._change(
                command=command,
                actor=actor,
                operation=CERTIFICATE_REVOKE_OPERATION,
                permission=CERTIFICATE_REVOKE_PERMISSION,
            )

    async def _change(
        self,
        *,
        command: CorrectCertificateCommand | RevokeCertificateCommand,
        actor: ActorContext,
        operation: str,
        permission: str,
    ) -> CertificateEventData:
        self._require_transaction()
        normalized_key = _required_text(command.idempotency_key, "idempotency_key", 200)
        normalized_reason = _required_text(command.reason, "reason", 500)
        await self._lock_actor(
            actor,
            tenant_id=command.tenant_id,
            subject_person_id=command.subject_person_id,
            permission=permission,
        )
        transaction = SqlAlchemyCertificateUnitOfWork(self._session)
        async with transaction:

            def lock_certificate(sync_session: Session) -> CourseCompletionCertificateData | None:
                return SqlAlchemyCertificateRepository(sync_session).lock_certificate(
                    command.certificate_id
                )

            certificate = cast(
                CourseCompletionCertificateData | None,
                await transaction.run_sync(lock_certificate),
            )
            if certificate is None:
                raise CertificateNotFoundError("certificate does not exist")
            if (
                certificate.tenant_id != command.tenant_id
                or certificate.person_id != command.subject_person_id
            ):
                raise CertificateScopeMismatchError(
                    "certificate change crosses the selected tenant or subject"
                )
            provenance = dict(command.provenance)
            request_digest = _hash_request(
                {
                    "operation": operation,
                    "certificate_id": str(certificate.id),
                    "actor_person_id": str(actor.person_id),
                    "subject_person_id": str(command.subject_person_id),
                    "tenant_id": str(command.tenant_id),
                    "reason": normalized_reason,
                    "provenance": provenance,
                    "idempotency_key": normalized_key,
                }
            )
            claimed, created_claim = await self._claim_command(
                self._new_command(
                    actor_person_id=actor.person_id,
                    operation=operation,
                    idempotency_key=normalized_key,
                    request_digest=request_digest,
                    identity=certificate,
                )
            )
            if not created_claim:
                _, _, event = await self._replay(claimed, request_digest)
                return event

            def change_sync(sync_session: Session) -> CertificateEventData:
                repository = SqlAlchemyCertificateRepository(sync_session)
                service = CourseCompletionCertificateService(
                    repository,
                    clock=self._clock,
                    authority=repository,
                )
                if operation == CERTIFICATE_CORRECT_OPERATION:
                    return service.correct(
                        certificate.id,
                        actor_person_id=actor.person_id,
                        tenant_id=command.tenant_id,
                        subject_person_id=command.subject_person_id,
                        reason=normalized_reason,
                        provenance=provenance,
                        idempotency_key=normalized_key,
                    )
                return service.revoke(
                    certificate.id,
                    actor_person_id=actor.person_id,
                    tenant_id=command.tenant_id,
                    subject_person_id=command.subject_person_id,
                    reason=normalized_reason,
                    provenance=provenance,
                    idempotency_key=normalized_key,
                )

            event = cast(CertificateEventData, await transaction.run_sync(change_sync))
            claimed.status = CertificateCommandStatus.COMPLETED.value
            claimed.result_certificate_id = certificate.id
            claimed.result_snapshot_id = event.completion_snapshot_id
            claimed.result_event_id = event.id
            claimed.completed_at = _now(self._clock())
            await self._record_side_effects(
                transaction,
                actor=actor,
                command=claimed,
                certificate=certificate,
                event=event,
            )
            await transaction.commit()
            return event


def _require_complete(completion: CompletionSnapshot) -> None:
    if completion.required_activity_count <= 0:
        raise EmptyCompletionError(
            "a course-completion certificate requires at least one required activity"
        )
    if not completion.is_complete:
        raise CompletionIncompleteError(
            "all required activities and module prerequisites must be complete before issuance"
        )


__all__ = [
    "ActivityCompletion",
    "ActiveEntitlementRequiredError",
    "AsyncCertificateApplication",
    "AuthoritativeProgressRequiredError",
    "CERTIFICATE_CORRECT_PERMISSION",
    "CERTIFICATE_ISSUE_OPERATION",
    "CERTIFICATE_REVOKE_PERMISSION",
    "CERTIFICATE_REVOKE_OPERATION",
    "CertificateAlreadyRevokedError",
    "CertificateAuthorizationRequiredError",
    "CertificateCommandInProgressError",
    "CertificateEventData",
    "CertificateIssueResult",
    "CertificateIdempotencyConflictError",
    "CertificateNotFoundError",
    "CertificateScopeMismatchError",
    "CertificateServiceError",
    "CertificateStateConflictError",
    "CertificateStore",
    "CertificateTransactionRequiredError",
    "CertificateView",
    "CompletionIncompleteError",
    "CompletionSnapshot",
    "COMPLETION_PREDICATE_VERSION",
    "CourseCompletionCertificateData",
    "CourseCompletionService",
    "CourseCompletionCertificateService",
    "CorrectCertificateCommand",
    "EmptyCompletionError",
    "ImmutableProgramVersionRequiredError",
    "IssueCertificateCommand",
    "InMemoryCertificateStore",
    "InvalidCompletionConfigurationError",
    "ModuleCompletion",
    "ModuleDefinition",
    "PinnedCourseVersion",
    "RevokeCertificateCommand",
    "SqlAlchemyCertificateRepository",
    "SqlAlchemyCertificateUnitOfWork",
    "evaluate_course_completion",
]
