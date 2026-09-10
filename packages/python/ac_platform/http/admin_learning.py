"""Narrow G1 admin catalog, enrollment, and learning HTTP commands.

This adapter deliberately composes existing domain applications.  It does not
create a second transaction, derive policy from request fields, or provide a
generic admin read model.  The learner-diagnosis route is therefore not
registered: the current learning repository has no canonical admin query that
enumerates a learner's scopes and returns a redacted, purpose-bound diagnosis.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from json import dumps
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.authorization.models import STUDIO_CAPABILITIES
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.authorization.studio import StudioAccess, StudioAuthorization
from ac_platform.catalog.models import (
    IMMUTABLE_VERSION_STATUSES,
    Activity,
    CatalogPublishCommand,
    CatalogScope,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogAccessDeniedError,
    CatalogConflictError,
    CatalogDraftPreconditionError,
    CatalogNotFoundError,
    CatalogPublicationPreconditionError,
    CatalogPublicationReadiness,
    CatalogService,
    CatalogServiceError,
    CatalogValidationError,
    DraftOperation,
    DraftRequiredError,
    ProgramVersionSnapshot,
    SqlAlchemyCatalogStore,
    SupersessionRequiredError,
)
from ac_platform.enrollment.services import (
    ENROLLMENT_GRANT_PERMISSION,
    AsyncEnrollmentApplication,
    EnrollmentPolicyInput,
    ManualEnrollmentGrantCommand,
)
from ac_platform.http.auth import (
    ROLE_PERMISSIONS,
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    ResourceConflict,
    ResourceNotFound,
)
from ac_platform.learning.services import (
    ActivityDefinition,
    EvidenceCorrectionSnapshot,
    LearningAccessContext,
    LearningCommandBundle,
    ReviewDecision,
    SqlAlchemyLearningRepository,
    VideoEvidencePolicy,
)
from ac_platform.tenancy.models import Membership, MembershipStatus, Tenant, TenantStatus

MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_AUDIT_REASON_LENGTH = 500
_SUBMISSION_ETAG_PATTERN = re.compile(r'^"submission-revision-(?P<revision>0|[1-9][0-9]*)"$')
_PROGRAM_VERSION_ETAG_PATTERN = re.compile(r'^"program-version-[0-9a-f]{64}"$')
STUDIO_COLLECTION_LIMIT = 100
STUDIO_IMMUTABLE_VERSION_LIMIT = 50
_CATALOG_PUBLISH_COMMAND_UNIQUE_CONSTRAINT = "uq_catalog_publish_commands_actor_key"
_CATALOG_PUBLISH_COMMAND_VERSION_FK = (
    "fk_catalog_publish_commands_program_version_id_program_versions"
)

ActivityResolver = Callable[[object, object], ActivityDefinition]
ReviewerResolver = Callable[[LearningAccessContext], UUID | None]


class AdminTenantContextRequired(AuthorizationDenied):
    """The authenticated actor has not selected an active tenant."""

    code = "admin_tenant_context_required"
    title = "A tenant context is required"


class AdminAuthorizationDenied(AuthorizationDenied):
    """The current actor is not an active named admin in the selected tenant."""

    code = "admin_authorization_denied"
    title = "Admin authorization denied"


class MissingAdminIdempotencyKey(DomainError):
    """A replay-safe admin command was sent without its command key."""

    code = "admin_idempotency_key_required"
    title = "An idempotency key is required"
    status = 428


class InvalidAdminETag(DomainError):
    """The correction target was not addressed with its canonical revision."""

    code = "admin_invalid_if_match"
    title = "The If-Match value is invalid"
    status = 400


class MissingAdminETag(DomainError):
    """Correction must use optimistic concurrency."""

    code = "admin_if_match_required"
    title = "An If-Match value is required"
    status = 428


class CatalogPublicationRejected(DomainError):
    """A catalog service rejected publication without leaking internal detail."""

    code = "catalog_publication_rejected"
    title = "The program version could not be published"


class CatalogPublicationPreconditionFailed(DomainError):
    """The reviewed draft representation changed before publication."""

    code = "catalog_publication_precondition_failed"
    title = "The program version changed"
    status = 412


class CatalogPublicationIdempotencyConflict(DomainError):
    """A publication command key was reused for different intent."""

    code = "catalog_publication_idempotency_conflict"
    title = "The idempotency key is already in use"
    status = 409


class PublishRequest(BaseModel):
    """Human reason captured alongside the immutable publication fact."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=MAX_AUDIT_REASON_LENGTH)


class StudioDraftPreconditionFailed(DomainError):
    code = "studio_draft_precondition_failed"
    title = "The draft has changed"
    status = 412


class StudioDraftConflict(DomainError):
    code = "studio_draft_conflict"
    title = "The draft command conflicts with saved state"
    status = 409


class StudioDraftInvalid(DomainError):
    code = "studio_draft_invalid"
    title = "The draft command is invalid"
    status = 422


class StudioModuleWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)


class StudioActivityWriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=240)
    prompt: str | None = Field(min_length=1, max_length=2000)


class StudioActivityCreateRequest(StudioActivityWriteRequest):
    kind: Literal["VIDEO", "REFLECTION", "IMPLEMENTATION_CHALLENGE", "REVIEW", "IMPROVE"]
    is_required: bool = Field(strict=True)


class CorrectionRequest(BaseModel):
    """Strict append-only correction input; actor and tenant are server-owned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    submission_id: UUID
    decision: Literal["approved", "rejected", "needs_revision"]
    reason: str = Field(min_length=1, max_length=MAX_AUDIT_REASON_LENGTH)


class EnrollmentGrantRequest(BaseModel):
    """Strict manual-grant input; live policy facts come from the domain service."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    person_id: UUID
    program_version_id: UUID
    reason: str = Field(min_length=1, max_length=MAX_AUDIT_REASON_LENGTH)


class ProgramVersionPublishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    program_id: UUID
    version_number: int
    status: Literal["published"]
    supersedes_version_id: UUID | None
    published_at: datetime
    replayed: bool


class StudioUnavailableMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["unavailable"] = "unavailable"
    value: None = None
    reason: str


class StudioCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission: Literal[
        "catalog_read", "catalog_write", "catalog_publish", "learner_diagnose", "learning_review"
    ]
    scope_kind: Literal["tenant", "program"]
    tenant_id: UUID
    program_id: UUID | None


class AdminAccessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    session_id: UUID
    tenant_id: UUID
    studio_capabilities: list[StudioCapabilityResponse]


class StudioDraftReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: UUID
    program_title: str
    program_version_id: UUID
    version_number: int
    created_at: datetime
    age_seconds: int
    etag: str
    ready: bool
    blockers: list[str]


class StudioReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    draft_backlog_count: int
    as_of: datetime
    oldest_draft_created_at: datetime | None
    oldest_draft_age_seconds: int | None
    drafts: list[StudioDraftReadinessResponse]
    truncated: bool
    arrival_rate: StudioUnavailableMetric
    service_rate: StudioUnavailableMetric
    planned_capacity: StudioUnavailableMetric


class StudioProgramVersionSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version_number: int
    status: Literal["draft", "published", "superseded"]
    created_at: datetime
    published_at: datetime | None


class StudioProgramSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    title: str
    scope: Literal["tenant", "global"]
    access: Literal["selected_tenant", "global_read_only"]
    version_count: int
    draft_count: int
    current_published_version_id: UUID | None
    latest_version: StudioProgramVersionSummaryResponse | None


class StudioProgramsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    programs: list[StudioProgramSummaryResponse]
    truncated: bool


class StudioActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    kind: str
    title: str
    prompt: str | None
    is_required: bool


class StudioModuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    title: str
    prerequisite_module_ids: list[UUID]
    activities: list[StudioActivityResponse]


class StudioProgramVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    version_number: int
    status: Literal["draft", "published", "superseded"]
    supersedes_version_id: UUID | None
    created_at: datetime
    published_at: datetime | None
    content_source_ref: str | None
    content_reviewed_by: str | None
    content_reviewed_at: datetime | None
    release_id: str | None
    content_seed_kind: str | None
    content_digest: str | None
    etag: str | None
    readiness: Literal["ready", "blocked", "immutable", "global_read_only"]
    blockers: list[str]
    modules: list[StudioModuleResponse]


class StudioProgramDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    id: UUID
    slug: str
    title: str
    scope: Literal["tenant", "global"]
    access: Literal["selected_tenant", "global_read_only"]
    versions: list[StudioProgramVersionResponse]
    versions_truncated: bool


class StudioDraftWriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    program: StudioProgramDetailResponse
    resource_id: UUID
    replayed: bool


class StudioRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CorrectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correction_id: UUID
    submission_id: UUID
    decision: Literal["approved", "rejected", "needs_revision"]
    correction_sequence: int
    supersedes_correction_id: UUID | None


class EnrollmentGrantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    entitlement_id: UUID
    provenance_id: UUID
    command_idempotency_id: UUID
    created: bool
    replayed: bool


def _default_activity_resolver(row: object, _version: object) -> ActivityDefinition:
    """Resolve only catalog facts already loaded by the learning repository."""

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


def _missing_policy(_access: LearningAccessContext) -> VideoEvidencePolicy:
    raise DomainError("No server-owned playback policy is configured for this deployment.")


def _bundle(
    database: Session,
    *,
    activity_resolver: ActivityResolver,
    reviewer_resolver: ReviewerResolver,
) -> LearningCommandBundle:
    repository = SqlAlchemyLearningRepository(
        database,
        activity_resolver=activity_resolver,
        reviewer_resolver=reviewer_resolver,
    )
    return LearningCommandBundle(
        repository,
        clock=lambda: datetime.now(UTC),
        policy_resolver=_missing_policy,
    )


async def _run_in_auth_transaction[ResultT](
    auth: AuthenticatedTransaction,
    operation: Callable[[Session], ResultT],
) -> ResultT:
    """Run sync learning code on the authenticated transaction's session."""

    return cast(ResultT, await auth.database.run_sync(operation))


async def _require_named_admin(
    auth: AuthenticatedTransaction,
    *,
    permission: str,
    lock: bool = True,
    program_id: UUID | None = None,
) -> tuple[ActorContext, UUID]:
    """Revalidate the selected tenant and canonical membership under row locks."""

    actor = auth.resolved.actor
    tenant_id = actor.tenant_id
    if tenant_id is None:
        raise AdminTenantContextRequired("Select an active tenant before using admin commands.")
    if permission in STUDIO_CAPABILITIES:
        try:
            await StudioAuthorization(auth.database).require(
                actor, permission, program_id=program_id
            )
        except CapabilityDenied as error:
            # Preserve the admin problem contract; a denial never selects a fallback policy.
            raise AdminAuthorizationDenied(error.detail) from error
        return actor, tenant_id
    if "admin_surface" not in actor.permissions or permission not in actor.permissions:
        raise AdminAuthorizationDenied(f"The actor lacks the {permission} permission.")

    statement = (
        select(Person, Tenant, Membership)
        .select_from(Membership)
        .join(Person, Person.id == Membership.person_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.person_id == actor.person_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    result = await auth.database.execute(statement)
    row = result.one_or_none()
    if row is None:
        raise AdminAuthorizationDenied("The actor has no active admin membership in this tenant.")
    person, tenant, membership = row
    if (
        person.status != PersonStatus.ACTIVE.value
        or tenant.status != TenantStatus.ACTIVE.value
        or membership.status != MembershipStatus.ACTIVE.value
        or membership.ended_at is not None
        or not _role_allows_permission(membership.role, permission)
    ):
        raise AdminAuthorizationDenied("The actor has no active admin membership in this tenant.")
    return actor, tenant_id


def _role_allows_permission(role: str, permission: str) -> bool:
    """Apply the same named-permission policy used to build actor contexts."""

    role_permissions = ROLE_PERMISSIONS.get(role, frozenset())
    return "admin_surface" in role_permissions and permission in role_permissions


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) and value else None


def _no_store(response: Response, *, submission_revision: int | None = None) -> None:
    response.headers["cache-control"] = "no-store"
    response.headers["pragma"] = "no-cache"
    if submission_revision is not None:
        response.headers["etag"] = f'"submission-revision-{submission_revision}"'


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise MissingAdminIdempotencyKey("This admin command requires Idempotency-Key.")
    return value.strip()


def _submission_revision(if_match: str | None) -> int:
    if if_match is None:
        raise MissingAdminETag("Admin corrections require If-Match.")
    match = _SUBMISSION_ETAG_PATTERN.fullmatch(if_match.strip())
    if match is None:
        raise InvalidAdminETag("If-Match must be the canonical submission revision ETag.")
    return int(match.group("revision"))


def _program_version_etag(if_match: str | None) -> str:
    if if_match is None:
        raise MissingAdminETag("Catalog publication requires If-Match.")
    value = if_match.strip()
    if _PROGRAM_VERSION_ETAG_PATTERN.fullmatch(value) is None:
        raise InvalidAdminETag("If-Match must be the canonical program-version ETag.")
    return value


def _catalog_problem(error: CatalogServiceError) -> DomainError:
    if isinstance(error, CatalogNotFoundError):
        return ResourceNotFound("The program version is unavailable.")
    if isinstance(error, CatalogAccessDeniedError):
        return AdminAuthorizationDenied("The program version is outside the selected tenant scope.")
    if isinstance(error, CatalogPublicationPreconditionError):
        return CatalogPublicationPreconditionFailed(
            "Refresh the program version and review the current readiness state before retrying."
        )
    if isinstance(error, CatalogConflictError | DraftRequiredError | SupersessionRequiredError):
        return ResourceConflict("The program version cannot be published in its current state.")
    if isinstance(error, CatalogValidationError):
        return CatalogPublicationRejected("The program version failed catalog validation.")
    return CatalogPublicationRejected("The program version could not be published.")


def _publish_response(
    version: ProgramVersionSnapshot,
    *,
    replayed: bool,
) -> ProgramVersionPublishResponse:
    if version.status != "published" or version.published_at is None:
        raise CatalogPublicationRejected("The catalog service returned a non-published version.")
    return ProgramVersionPublishResponse(
        id=version.id,
        program_id=version.program_id,
        version_number=version.version_number,
        status="published",
        supersedes_version_id=version.supersedes_version_id,
        published_at=version.published_at,
        replayed=replayed,
    )


def _placeholder_policy(
    *,
    subject_person_id: UUID,
    tenant_id: UUID,
    program_version_id: UUID,
) -> EnrollmentPolicyInput:
    """Build a fail-closed placeholder replaced by the live grant service.

    ``ManualEnrollmentGrantCommand`` carries a policy value for the domain
    command shape, but ``AsyncEnrollmentApplication.grant_manual`` reloads and
    replaces it from locked canonical rows before validation or persistence.
    The deliberately false placeholder must never authorize anything itself.
    """

    return EnrollmentPolicyInput.for_free_enrollment(
        subject_person_id=subject_person_id,
        tenant_id=tenant_id,
        program_version_id=program_version_id,
        age_gate_passed=None,
        eligibility_passed=None,
        prerequisites_satisfied=None,
        membership_active=False,
        tenant_active=False,
        membership_role=None,
        program_version_published=False,
        program_version_immutable=False,
    )


async def _append_admin_audit(
    auth: AuthenticatedTransaction,
    *,
    actor: ActorContext,
    action: str,
    resource_type: str,
    resource_id: UUID,
    payload: dict[str, Any],
    reason: str,
    request: Request,
) -> Any:
    return await AuditRepository(auth.database).append_for_actor(
        actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        reason=reason,
        request_id=_request_id(request),
    )


async def _studio_access(
    auth: AuthenticatedTransaction, *, permission: str = "catalog_read"
) -> StudioAccess:
    if auth.resolved.actor.tenant_id is None:
        raise AdminTenantContextRequired("Select an active tenant before using Studio.")
    try:
        return await StudioAuthorization(auth.database).access(auth.resolved.actor, permission)
    except CapabilityDenied as error:
        raise AdminAuthorizationDenied(error.detail) from error


def _studio_visibility(access: StudioAccess) -> Any:
    tenant_programs = and_(
        Program.scope == CatalogScope.TENANT.value,
        Program.tenant_id == access.tenant_id,
    )
    if not access.all_programs:
        tenant_programs = and_(tenant_programs, Program.id.in_(access.program_ids))
    if not access.include_global:
        return tenant_programs
    immutable_global_version = (
        exists()
        .where(
            ProgramVersion.program_id == Program.id,
            ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES),
        )
        .correlate(Program)
    )
    return or_(
        tenant_programs,
        and_(
            Program.scope == CatalogScope.GLOBAL.value,
            Program.tenant_id.is_(None),
            immutable_global_version,
        ),
    )


def _visible_versions(
    database: Session,
    program: Program,
    *,
    limit: int,
) -> tuple[ProgramVersion, ...]:
    statement = (
        select(ProgramVersion)
        .where(ProgramVersion.program_id == program.id)
        .order_by(ProgramVersion.version_number.desc(), ProgramVersion.id.asc())
    )
    if program.scope == CatalogScope.GLOBAL.value:
        statement = statement.where(ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES))
    return tuple(database.scalars(statement.limit(limit)).all())


def _visible_version_counts(database: Session, program: Program) -> tuple[int, int]:
    statement = select(
        func.count(ProgramVersion.id),
        func.count(ProgramVersion.id).filter(
            ProgramVersion.status == ProgramVersionStatus.DRAFT.value
        ),
    ).where(ProgramVersion.program_id == program.id)
    if program.scope == CatalogScope.GLOBAL.value:
        statement = statement.where(ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES))
    version_count, draft_count = database.execute(statement).one()
    return int(version_count), int(draft_count)


def _studio_detail_versions(
    database: Session,
    program: Program,
) -> tuple[tuple[ProgramVersion, ...], bool]:
    """Return every tenant draft and only a bounded immutable history."""

    immutable_statement = (
        select(ProgramVersion)
        .where(
            ProgramVersion.program_id == program.id,
            ProgramVersion.status.in_(IMMUTABLE_VERSION_STATUSES),
        )
        .order_by(ProgramVersion.version_number.desc(), ProgramVersion.id.asc())
        .limit(STUDIO_IMMUTABLE_VERSION_LIMIT + 1)
    )
    immutable_versions = tuple(database.scalars(immutable_statement).all())
    retained_immutable = immutable_versions[:STUDIO_IMMUTABLE_VERSION_LIMIT]
    immutable_truncated = len(immutable_versions) > STUDIO_IMMUTABLE_VERSION_LIMIT
    if program.scope == CatalogScope.GLOBAL.value:
        return retained_immutable, immutable_truncated

    drafts = tuple(
        database.scalars(
            select(ProgramVersion)
            .where(
                ProgramVersion.program_id == program.id,
                ProgramVersion.status == ProgramVersionStatus.DRAFT.value,
            )
            .order_by(ProgramVersion.version_number.desc(), ProgramVersion.id.asc())
        ).all()
    )
    visible_versions = tuple(
        sorted(
            (*drafts, *retained_immutable),
            key=lambda version: (-version.version_number, version.id.hex),
        )
    )
    return visible_versions, immutable_truncated


def _studio_programs_response(database: Session, access: StudioAccess) -> StudioProgramsResponse:
    rows = tuple(
        database.scalars(
            select(Program)
            .where(_studio_visibility(access))
            .order_by(Program.scope.desc(), Program.title.asc(), Program.id.asc())
            .limit(STUDIO_COLLECTION_LIMIT + 1)
        ).all()
    )
    programs: list[StudioProgramSummaryResponse] = []
    for program in rows[:STUDIO_COLLECTION_LIMIT]:
        versions = _visible_versions(database, program, limit=1)
        version_count, draft_count = _visible_version_counts(database, program)
        latest = versions[0] if versions else None
        current = database.scalar(
            select(ProgramVersion)
            .where(
                ProgramVersion.program_id == program.id,
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
            )
            .order_by(ProgramVersion.version_number.desc(), ProgramVersion.id.asc())
            .limit(1)
        )
        programs.append(
            StudioProgramSummaryResponse(
                id=program.id,
                slug=program.slug,
                title=program.title,
                scope=cast(Literal["tenant", "global"], program.scope),
                access=(
                    "global_read_only"
                    if program.scope == CatalogScope.GLOBAL.value
                    else "selected_tenant"
                ),
                version_count=version_count,
                draft_count=draft_count,
                current_published_version_id=current.id if current is not None else None,
                latest_version=(
                    StudioProgramVersionSummaryResponse(
                        id=latest.id,
                        version_number=latest.version_number,
                        status=cast(Literal["draft", "published", "superseded"], latest.status),
                        created_at=latest.created_at,
                        published_at=latest.published_at,
                    )
                    if latest is not None
                    else None
                ),
            )
        )
    return StudioProgramsResponse(
        tenant_id=access.tenant_id,
        programs=programs,
        truncated=len(rows) > STUDIO_COLLECTION_LIMIT,
    )


def _version_modules(
    database: Session,
    version: ProgramVersion,
) -> list[StudioModuleResponse]:
    modules = tuple(
        database.scalars(
            select(Module)
            .where(Module.program_version_id == version.id)
            .order_by(Module.position.asc(), Module.id.asc())
        ).all()
    )
    edges = tuple(
        database.scalars(
            select(ModulePrerequisite).where(ModulePrerequisite.program_version_id == version.id)
        ).all()
    )
    prerequisites = {
        module.id: sorted(
            (edge.prerequisite_module_id for edge in edges if edge.module_id == module.id),
            key=lambda value: value.hex,
        )
        for module in modules
    }
    response: list[StudioModuleResponse] = []
    for module in modules:
        activities = tuple(
            database.scalars(
                select(Activity)
                .where(Activity.module_id == module.id)
                .order_by(Activity.position.asc(), Activity.id.asc())
            ).all()
        )
        response.append(
            StudioModuleResponse(
                id=module.id,
                position=module.position,
                title=module.title,
                prerequisite_module_ids=prerequisites[module.id],
                activities=[
                    StudioActivityResponse(
                        id=activity.id,
                        position=activity.position,
                        kind=activity.kind,
                        title=activity.title,
                        prompt=activity.prompt,
                        is_required=activity.is_required,
                    )
                    for activity in activities
                ],
            )
        )
    return response


def _studio_program_detail_response(
    database: Session,
    access: StudioAccess,
    program_id: UUID,
    *,
    allow_technical_validation_publication: bool,
    required_version_id: UUID | None = None,
) -> StudioProgramDetailResponse:
    program = database.scalar(
        select(Program).where(
            Program.id == program_id,
            _studio_visibility(access),
        )
    )
    if program is None:
        raise ResourceNotFound("The Studio program is unavailable.")
    versions, immutable_versions_truncated = _studio_detail_versions(database, program)
    # An old successful authoring replay still identifies its original resource.
    # Include that single authorized version even beyond the bounded history page.
    if required_version_id is not None and all(v.id != required_version_id for v in versions):
        required = database.scalar(
            select(ProgramVersion).where(
                ProgramVersion.id == required_version_id, ProgramVersion.program_id == program.id
            )
        )
        if required is None:
            raise ResourceNotFound("The command's catalog version is unavailable.")
        versions = tuple(sorted((*versions, required), key=lambda v: (-v.version_number, v.id.hex)))
    catalog = CatalogService(
        SqlAlchemyCatalogStore(database),
        allow_technical_validation_publication=allow_technical_validation_publication,
    )
    version_responses: list[StudioProgramVersionResponse] = []
    for version in versions:
        version_etag: str | None = None
        if program.scope == CatalogScope.GLOBAL.value:
            readiness_state: Literal["ready", "blocked", "immutable", "global_read_only"] = (
                "global_read_only"
            )
            readiness: CatalogPublicationReadiness | None = None
        elif version.status == ProgramVersionStatus.DRAFT.value:
            readiness = catalog.assess_publication_readiness(
                version.id,
                tenant_id=access.tenant_id,
            )
            readiness_state = "ready" if readiness.ready else "blocked"
            version_etag = readiness.etag
        else:
            readiness = None
            readiness_state = "immutable"
            if version.status == ProgramVersionStatus.PUBLISHED.value:
                version_etag = catalog.publication_etag(
                    catalog.get_version(version.id, tenant_id=access.tenant_id)
                )
        version_responses.append(
            StudioProgramVersionResponse(
                id=version.id,
                version_number=version.version_number,
                status=cast(Literal["draft", "published", "superseded"], version.status),
                supersedes_version_id=version.supersedes_version_id,
                created_at=version.created_at,
                published_at=version.published_at,
                content_source_ref=version.content_source_ref,
                content_reviewed_by=version.content_reviewed_by,
                content_reviewed_at=version.content_reviewed_at,
                release_id=version.release_id,
                content_seed_kind=version.content_seed_kind,
                content_digest=version.content_digest,
                etag=version_etag,
                readiness=readiness_state,
                blockers=list(readiness.blockers) if readiness is not None else [],
                modules=_version_modules(database, version),
            )
        )
    return StudioProgramDetailResponse(
        tenant_id=access.tenant_id,
        id=program.id,
        slug=program.slug,
        title=program.title,
        scope=cast(Literal["tenant", "global"], program.scope),
        access=(
            "global_read_only" if program.scope == CatalogScope.GLOBAL.value else "selected_tenant"
        ),
        versions=version_responses,
        versions_truncated=immutable_versions_truncated,
    )


def _studio_readiness_response(
    database: Session,
    access: StudioAccess,
    *,
    allow_technical_validation_publication: bool,
) -> StudioReadinessResponse:
    as_of = datetime.now(UTC)

    def age_seconds(created_at: datetime) -> int:
        normalized = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
        return max(0, int((as_of - normalized.astimezone(UTC)).total_seconds()))

    filters = (
        Program.scope == CatalogScope.TENANT.value,
        _studio_visibility(access),
        ProgramVersion.status == ProgramVersionStatus.DRAFT.value,
    )
    total = database.scalar(
        select(func.count())
        .select_from(ProgramVersion)
        .join(Program, Program.id == ProgramVersion.program_id)
        .where(*filters)
    )
    rows = tuple(
        database.execute(
            select(Program, ProgramVersion)
            .join(ProgramVersion, ProgramVersion.program_id == Program.id)
            .where(*filters)
            .order_by(ProgramVersion.created_at.asc(), ProgramVersion.id.asc())
            .limit(STUDIO_COLLECTION_LIMIT)
        ).all()
    )
    catalog = CatalogService(
        SqlAlchemyCatalogStore(database),
        allow_technical_validation_publication=allow_technical_validation_publication,
    )
    drafts = [
        StudioDraftReadinessResponse(
            program_id=program.id,
            program_title=program.title,
            program_version_id=version.id,
            version_number=version.version_number,
            created_at=version.created_at,
            age_seconds=age_seconds(version.created_at),
            etag=(
                readiness := catalog.assess_publication_readiness(
                    version.id,
                    tenant_id=access.tenant_id,
                )
            ).etag,
            ready=readiness.ready,
            blockers=list(readiness.blockers),
        )
        for program, version in rows
    ]
    unavailable_reason = (
        "No canonical operational work-item timestamps or capacity plan exist in this slice."
    )
    total_count = int(total or 0)
    return StudioReadinessResponse(
        tenant_id=access.tenant_id,
        draft_backlog_count=total_count,
        as_of=as_of,
        oldest_draft_created_at=drafts[0].created_at if drafts else None,
        oldest_draft_age_seconds=drafts[0].age_seconds if drafts else None,
        drafts=drafts,
        truncated=total_count > STUDIO_COLLECTION_LIMIT,
        arrival_rate=StudioUnavailableMetric(reason=unavailable_reason),
        service_rate=StudioUnavailableMetric(reason=unavailable_reason),
        planned_capacity=StudioUnavailableMetric(reason=unavailable_reason),
    )


def _catalog_publish_key_digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _catalog_publish_fingerprint(
    *,
    actor: ActorContext,
    tenant_id: UUID,
    program_version_id: UUID,
    expected_etag: str,
    reason: str,
) -> str:
    material = dumps(
        {
            "actor_person_id": str(actor.person_id),
            "tenant_id": str(tenant_id),
            "program_version_id": str(program_version_id),
            "expected_etag": expected_etag,
            "reason": reason,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(material.encode("utf-8")).hexdigest()


def _integrity_constraint_name(error: IntegrityError) -> str | None:
    diagnostic = getattr(error.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


async def _reserve_catalog_publish_command(
    auth: AuthenticatedTransaction,
    *,
    actor: ActorContext,
    tenant_id: UUID,
    program_version_id: UUID,
    idempotency_key: str,
    request_fingerprint: str,
) -> tuple[CatalogPublishCommand, bool]:
    key_digest = _catalog_publish_key_digest(idempotency_key)
    statement = select(CatalogPublishCommand).where(
        CatalogPublishCommand.tenant_id == tenant_id,
        CatalogPublishCommand.actor_person_id == actor.person_id,
        CatalogPublishCommand.idempotency_key_digest == key_digest,
    )
    existing = await auth.database.scalar(statement.with_for_update())
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise CatalogPublicationIdempotencyConflict(
                "Use a new Idempotency-Key for a different publication request."
            )
        if existing.state != "completed" or existing.response_payload is None:
            raise ResourceConflict("The prior publication command has not completed.")
        return existing, True

    command = CatalogPublishCommand(
        tenant_id=tenant_id,
        actor_person_id=actor.person_id,
        program_version_id=program_version_id,
        idempotency_key_digest=key_digest,
        request_fingerprint=request_fingerprint,
        state="pending",
    )
    try:
        async with auth.database.begin_nested():
            auth.database.add(command)
            await auth.database.flush([command])
    except IntegrityError as exc:
        constraint_name = _integrity_constraint_name(exc)
        if constraint_name == _CATALOG_PUBLISH_COMMAND_VERSION_FK:
            raise ResourceNotFound("The program version is unavailable.") from None
        if constraint_name != _CATALOG_PUBLISH_COMMAND_UNIQUE_CONSTRAINT:
            raise
        existing = await auth.database.scalar(statement.with_for_update())
        if existing is None:
            raise
        if existing.request_fingerprint != request_fingerprint:
            raise CatalogPublicationIdempotencyConflict(
                "Use a new Idempotency-Key for a different publication request."
            ) from None
        if existing.state != "completed" or existing.response_payload is None:
            raise ResourceConflict("The prior publication command has not completed.") from None
        return existing, True
    return command, False


async def _complete_catalog_publish_command(
    auth: AuthenticatedTransaction,
    command: CatalogPublishCommand,
    *,
    response: ProgramVersionPublishResponse,
    audit_event_id: UUID,
) -> None:
    command.state = "completed"
    command.response_payload = response.model_dump(mode="json")
    command.audit_event_id = audit_event_id
    command.completed_at = datetime.now(UTC)
    await auth.database.flush([command])


def install_admin_learning_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
    activity_resolver: ActivityResolver | None = None,
    reviewer_resolver: ReviewerResolver | None = None,
) -> None:
    """Install truthful G1 admin commands around the caller-owned transaction.

    The diagnosis route is not installed because no existing domain service
    supplies its required redacted, purpose-bound admin query.
    """

    def require_admin_route_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    def require_studio_route_surface(request: Request) -> None:
        if request.url.hostname != settings.coach_app_url.host:
            require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1",
        tags=["admin-learning"],
        dependencies=[Depends(require_admin_route_surface)],
    )
    actor_dependency = Depends(require_actor)
    studio_router = APIRouter(
        prefix="/v1",
        tags=["admin-learning"],
        dependencies=[Depends(require_studio_route_surface)],
    )
    # New authoring responses must not escape a failed outer commit.
    authoring_dependency = Depends(require_actor, scope="function")
    projection_router = APIRouter(prefix="/v1", tags=["identity"])
    resolved_activity = activity_resolver or _default_activity_resolver
    resolved_reviewer = reviewer_resolver or (lambda _access: None)

    @projection_router.get("/me/studio-access", response_model=AdminAccessResponse)
    async def admin_access(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> AdminAccessResponse:
        if request.query_params:
            raise DomainError("Studio access is resolved only for the authenticated context.")
        actor = auth.resolved.actor
        if actor.tenant_id is None:
            raise AdminTenantContextRequired("Select an active tenant before using Studio.")
        try:
            projection = await StudioAuthorization(auth.database).projection(actor)
        except CapabilityDenied as error:
            raise AdminAuthorizationDenied(error.detail) from error
        capabilities = [
            StudioCapabilityResponse(
                permission=cast(Any, permission),
                scope_kind="tenant" if access.all_programs else "program",
                tenant_id=access.tenant_id,
                program_id=program_id,
            )
            for permission, access in sorted(projection.items())
            for program_id in (
                (None,) if access.all_programs else tuple(sorted(access.program_ids, key=str))
            )
        ]
        _no_store(response)
        return AdminAccessResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            tenant_id=actor.tenant_id,
            studio_capabilities=capabilities,
        )

    @studio_router.get(
        "/admin/studio/readiness",
        response_model=StudioReadinessResponse,
    )
    async def studio_readiness(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioReadinessResponse:
        access = await _studio_access(auth)
        result = await auth.database.run_sync(
            lambda database: _studio_readiness_response(
                database,
                access,
                allow_technical_validation_publication=settings.environment == "staging",
            )
        )
        _no_store(response)
        return result

    @studio_router.get(
        "/admin/studio/programs",
        response_model=StudioProgramsResponse,
    )
    async def studio_programs(
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioProgramsResponse:
        access = await _studio_access(auth)
        result = await auth.database.run_sync(
            lambda database: _studio_programs_response(database, access)
        )
        _no_store(response)
        return result

    @studio_router.get(
        "/admin/studio/programs/{program_id}",
        response_model=StudioProgramDetailResponse,
    )
    async def studio_program_detail(
        program_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> StudioProgramDetailResponse:
        access = await _studio_access(auth)
        visible_program_id = await auth.database.scalar(
            select(Program.id).where(Program.id == program_id, _studio_visibility(access))
        )
        if visible_program_id is None:
            raise ResourceNotFound("The Studio program is unavailable.")
        await _require_named_admin(
            auth,
            permission="catalog_read",
            program_id=visible_program_id,
        )
        result = await auth.database.run_sync(
            lambda database: _studio_program_detail_response(
                database,
                access,
                program_id,
                allow_technical_validation_publication=settings.environment == "staging",
            )
        )
        _no_store(response)
        return result

    async def author_draft(
        version_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction,
        operation: DraftOperation,
        body: StudioModuleWriteRequest | StudioActivityWriteRequest,
        if_match: str | None,
        idempotency_key: str | None,
        target_id: UUID | None = None,
    ) -> StudioDraftWriteResponse:
        require_safe_origin(request, settings)
        # Returning the existing full Studio representation requires its independent
        # read capability; write never becomes an implicit read/publication grant.
        access = await _studio_access(auth)
        program_id = await auth.database.scalar(
            select(ProgramVersion.program_id)
            .join(Program, Program.id == ProgramVersion.program_id)
            .where(
                ProgramVersion.id == version_id,
                ProgramVersion.scope == "tenant",
                ProgramVersion.tenant_id == access.tenant_id,
                _studio_visibility(access),
            )
        )
        if program_id is None:
            raise ResourceNotFound("The draft is unavailable.")
        actor, tenant_id = await _require_named_admin(
            auth, permission="catalog_write", program_id=program_id
        )
        expected_etag = _program_version_etag(if_match)
        command_key = _idempotency_key(idempotency_key)
        try:
            result = await AsyncCatalogApplication(auth.database).author_draft(
                actor=actor,
                tenant_id=tenant_id,
                program_version_id=version_id,
                operation=operation,
                target_id=target_id,
                title=body.title,
                prompt=body.prompt if isinstance(body, StudioActivityWriteRequest) else None,
                kind=body.kind if isinstance(body, StudioActivityCreateRequest) else None,
                is_required=body.is_required
                if isinstance(body, StudioActivityCreateRequest)
                else None,
                expected_etag=expected_etag,
                idempotency_key=command_key,
                request_id=_request_id(request),
            )
        except CatalogDraftPreconditionError as error:
            raise StudioDraftPreconditionFailed(
                "Reload the saved draft before changing it."
            ) from error
        except (CatalogConflictError, DraftRequiredError) as error:
            raise StudioDraftConflict(
                "The command cannot change this saved draft state."
            ) from error
        except CatalogNotFoundError as error:
            raise ResourceNotFound("The resource is unavailable in this draft.") from error
        except CatalogAccessDeniedError as error:
            raise AdminAuthorizationDenied("The draft command is not authorized.") from error
        except CatalogValidationError as error:
            raise StudioDraftInvalid("The draft command failed catalog validation.") from error
        detail = await auth.database.run_sync(
            lambda database: _studio_program_detail_response(
                database,
                access,
                result.program_id,
                allow_technical_validation_publication=settings.environment == "staging",
                required_version_id=version_id,
            )
        )
        _no_store(response)
        return StudioDraftWriteResponse(
            program=detail, resource_id=result.resource_id, replayed=result.replayed
        )

    @studio_router.post(
        "/admin/studio/program-versions/{version_id}/revision",
        response_model=StudioDraftWriteResponse,
    )
    async def revise_published_version(
        version_id: UUID,
        request: Request,
        response: Response,
        body: StudioRevisionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = authoring_dependency,
    ) -> StudioDraftWriteResponse:
        del body  # Explicit empty object; no caller-supplied identity or provenance.
        require_safe_origin(request, settings)
        access = await _studio_access(auth)
        program_id = await auth.database.scalar(
            select(ProgramVersion.program_id)
            .join(Program, Program.id == ProgramVersion.program_id)
            .where(
                ProgramVersion.id == version_id,
                ProgramVersion.scope == CatalogScope.TENANT.value,
                ProgramVersion.tenant_id == access.tenant_id,
                _studio_visibility(access),
            )
        )
        if program_id is None:
            raise ResourceNotFound("The published course is unavailable.")
        actor, tenant_id = await _require_named_admin(
            auth, permission="catalog_write", program_id=program_id
        )
        try:
            result = await AsyncCatalogApplication(auth.database).revise_published_version(
                actor=actor,
                tenant_id=tenant_id,
                program_version_id=version_id,
                expected_etag=_program_version_etag(if_match),
                idempotency_key=_idempotency_key(idempotency_key),
                request_id=_request_id(request),
            )
        except CatalogDraftPreconditionError as error:
            raise StudioDraftPreconditionFailed(
                "Reload the published course before revising it."
            ) from error
        except CatalogConflictError as error:
            raise StudioDraftConflict(
                "The revision cannot be created from this version."
            ) from error
        except CatalogNotFoundError as error:
            raise ResourceNotFound("The published course is unavailable.") from error
        except CatalogAccessDeniedError as error:
            raise AdminAuthorizationDenied("The revision is not authorized.") from error
        except CatalogValidationError as error:
            raise StudioDraftInvalid("The revision failed catalog validation.") from error
        detail = await auth.database.run_sync(
            lambda database: _studio_program_detail_response(
                database,
                access,
                result.program_id,
                allow_technical_validation_publication=settings.environment == "staging",
                required_version_id=result.resource_id,
            )
        )
        _no_store(response)
        return StudioDraftWriteResponse(
            program=detail, resource_id=result.resource_id, replayed=result.replayed
        )

    @studio_router.post(
        "/admin/studio/program-versions/{version_id}/modules",
        response_model=StudioDraftWriteResponse,
    )
    async def append_draft_module(
        version_id: UUID,
        request: Request,
        response: Response,
        body: StudioModuleWriteRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = authoring_dependency,
    ) -> StudioDraftWriteResponse:
        return await author_draft(
            version_id, request, response, auth, "module_add", body, if_match, idempotency_key
        )

    @studio_router.patch(
        "/admin/studio/program-versions/{version_id}/modules/{module_id}",
        response_model=StudioDraftWriteResponse,
    )
    async def update_draft_module(
        version_id: UUID,
        module_id: UUID,
        request: Request,
        response: Response,
        body: StudioModuleWriteRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = authoring_dependency,
    ) -> StudioDraftWriteResponse:
        return await author_draft(
            version_id,
            request,
            response,
            auth,
            "module_update",
            body,
            if_match,
            idempotency_key,
            module_id,
        )

    @studio_router.post(
        "/admin/studio/program-versions/{version_id}/modules/{module_id}/activities",
        response_model=StudioDraftWriteResponse,
    )
    async def append_draft_activity(
        version_id: UUID,
        module_id: UUID,
        request: Request,
        response: Response,
        body: StudioActivityCreateRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = authoring_dependency,
    ) -> StudioDraftWriteResponse:
        return await author_draft(
            version_id,
            request,
            response,
            auth,
            "activity_add",
            body,
            if_match,
            idempotency_key,
            module_id,
        )

    @studio_router.patch(
        "/admin/studio/program-versions/{version_id}/activities/{activity_id}",
        response_model=StudioDraftWriteResponse,
    )
    async def update_draft_activity(
        version_id: UUID,
        activity_id: UUID,
        request: Request,
        response: Response,
        body: StudioActivityWriteRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = authoring_dependency,
    ) -> StudioDraftWriteResponse:
        return await author_draft(
            version_id,
            request,
            response,
            auth,
            "activity_update",
            body,
            if_match,
            idempotency_key,
            activity_id,
        )

    @studio_router.post(
        "/admin/program-versions/{program_version_id}/publish",
        response_model=ProgramVersionPublishResponse,
    )
    async def publish_program_version(
        program_version_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: PublishRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ProgramVersionPublishResponse:
        require_safe_origin(request, settings)
        if auth.resolved.actor.tenant_id is None:
            raise AdminTenantContextRequired("Select an active tenant before using admin commands.")
        access = await _studio_access(auth, permission="catalog_publish")
        program_id = await auth.database.scalar(
            select(ProgramVersion.program_id)
            .join(Program, Program.id == ProgramVersion.program_id)
            .where(
                ProgramVersion.id == program_version_id,
                ProgramVersion.scope == CatalogScope.TENANT.value,
                ProgramVersion.tenant_id == access.tenant_id,
                _studio_visibility(access),
            )
        )
        if program_id is None:
            raise ResourceNotFound("The program version is unavailable.")
        actor, tenant_id = await _require_named_admin(
            auth,
            permission="catalog_publish",
            program_id=program_id,
        )
        expected_etag = _program_version_etag(if_match)
        command_key = _idempotency_key(idempotency_key)
        request_fingerprint = _catalog_publish_fingerprint(
            actor=actor,
            tenant_id=tenant_id,
            program_version_id=program_version_id,
            expected_etag=expected_etag,
            reason=body.reason,
        )
        command, replayed = await _reserve_catalog_publish_command(
            auth,
            actor=actor,
            tenant_id=tenant_id,
            program_version_id=program_version_id,
            idempotency_key=command_key,
            request_fingerprint=request_fingerprint,
        )
        if replayed:
            stored = ProgramVersionPublishResponse.model_validate(command.response_payload)
            _no_store(response)
            return stored.model_copy(update={"replayed": True})
        try:
            version = await AsyncCatalogApplication(
                auth.database,
                allow_technical_validation_publication=settings.environment == "staging",
            ).publish_version(
                program_version_id,
                actor=actor,
                tenant_id=tenant_id,
                expected_etag=expected_etag,
            )
        except CatalogServiceError as exc:
            raise _catalog_problem(exc) from exc
        publication = _publish_response(version, replayed=False)
        audit_event = await _append_admin_audit(
            auth,
            actor=actor,
            action="audit.catalog.version.published.v1",
            resource_type="program_version",
            resource_id=version.id,
            payload={
                "program_id": str(version.program_id),
                "version_number": version.version_number,
                "status": version.status,
                "supersedes_version_id": (
                    str(version.supersedes_version_id)
                    if version.supersedes_version_id is not None
                    else None
                ),
            },
            reason=body.reason,
            request=request,
        )
        await _complete_catalog_publish_command(
            auth,
            command,
            response=publication,
            audit_event_id=audit_event.id,
        )
        _no_store(response)
        return publication

    @router.post("/admin/corrections", response_model=CorrectionResponse)
    async def append_correction(
        request: Request,
        response: Response,
        body: CorrectionRequest,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=96)] = None,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CorrectionResponse:
        require_safe_origin(request, settings)
        actor, tenant_id = await _require_named_admin(
            auth,
            permission="learning_correct",
        )
        expected_revision = _submission_revision(if_match)
        command_key = _idempotency_key(idempotency_key)

        def mutate(database: Session) -> EvidenceCorrectionSnapshot:
            return _bundle(
                database,
                activity_resolver=resolved_activity,
                reviewer_resolver=resolved_reviewer,
            ).evidence.review_submission(
                actor=actor,
                tenant_id=tenant_id,
                submission_id=body.submission_id,
                decision=ReviewDecision(body.decision),
                reason=body.reason,
                expected_revision=expected_revision,
                idempotency_key=command_key,
            )

        correction = await _run_in_auth_transaction(auth, mutate)
        await _append_admin_audit(
            auth,
            actor=actor,
            action="audit.learning.correction.appended.v1",
            resource_type="evidence_correction",
            resource_id=correction.id,
            payload={
                "submission_id": str(correction.submission_id),
                "decision": str(correction.decision),
                "correction_sequence": correction.correction_sequence,
                "supersedes_correction_id": (
                    str(correction.supersedes_correction_id)
                    if correction.supersedes_correction_id is not None
                    else None
                ),
            },
            reason=body.reason,
            request=request,
        )
        _no_store(response, submission_revision=correction.correction_sequence)
        return CorrectionResponse(
            correction_id=correction.id,
            submission_id=correction.submission_id,
            decision=cast(
                Literal["approved", "rejected", "needs_revision"], str(correction.decision)
            ),
            correction_sequence=correction.correction_sequence,
            supersedes_correction_id=correction.supersedes_correction_id,
        )

    @router.post(
        "/admin/enrollment-grants",
        response_model=EnrollmentGrantResponse,
    )
    async def grant_enrollment(
        request: Request,
        response: Response,
        body: EnrollmentGrantRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> EnrollmentGrantResponse:
        require_safe_origin(request, settings)
        actor, tenant_id = await _require_named_admin(
            auth,
            permission=ENROLLMENT_GRANT_PERMISSION,
        )
        command_key = _idempotency_key(idempotency_key)
        command = ManualEnrollmentGrantCommand(
            actor_person_id=actor.person_id,
            subject_person_id=body.person_id,
            tenant_id=tenant_id,
            program_version_id=body.program_version_id,
            idempotency_key=command_key,
            reason=body.reason,
            policy=_placeholder_policy(
                subject_person_id=body.person_id,
                tenant_id=tenant_id,
                program_version_id=body.program_version_id,
            ),
        )
        result = await AsyncEnrollmentApplication(auth.database).grant_manual(
            command,
            actor=actor,
        )
        if result.created:
            await _append_admin_audit(
                auth,
                actor=actor,
                action="audit.admin.enrollment.granted.v1",
                resource_type="enrollment",
                resource_id=result.enrollment_id,
                payload={
                    "subject_person_id": str(body.person_id),
                    "program_version_id": str(body.program_version_id),
                    "entitlement_id": str(result.entitlement_id),
                    "provenance_id": str(result.provenance_id),
                    "command_idempotency_id": str(result.command_idempotency_id),
                    "source": "manual_grant",
                },
                reason=body.reason,
                request=request,
            )
        _no_store(response)
        if result.created:
            response.status_code = status.HTTP_201_CREATED
        return EnrollmentGrantResponse(
            enrollment_id=result.enrollment_id,
            entitlement_id=result.entitlement_id,
            provenance_id=result.provenance_id,
            command_idempotency_id=result.command_idempotency_id,
            created=result.created,
            replayed=result.replayed,
        )

    application.include_router(router)
    application.include_router(studio_router)
    application.include_router(projection_router)


__all__ = [
    "AdminAuthorizationDenied",
    "AdminTenantContextRequired",
    "CorrectionRequest",
    "CorrectionResponse",
    "EnrollmentGrantRequest",
    "EnrollmentGrantResponse",
    "InvalidAdminETag",
    "MissingAdminETag",
    "MissingAdminIdempotencyKey",
    "ProgramVersionPublishResponse",
    "PublishRequest",
    "install_admin_learning_http",
]
