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
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Path, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.catalog.services import (
    AsyncCatalogApplication,
    CatalogAccessDeniedError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogServiceError,
    CatalogValidationError,
    DraftRequiredError,
    ProgramVersionSnapshot,
    SupersessionRequiredError,
)
from ac_platform.enrollment.services import (
    ENROLLMENT_GRANT_PERMISSION,
    AsyncEnrollmentApplication,
    EnrollmentPolicyInput,
    ManualEnrollmentGrantCommand,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
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


class PublishRequest(BaseModel):
    """Human reason captured alongside the immutable publication fact."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=MAX_AUDIT_REASON_LENGTH)


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
) -> tuple[ActorContext, UUID]:
    """Revalidate the selected tenant and canonical membership under row locks."""

    actor = auth.resolved.actor
    tenant_id = actor.tenant_id
    if tenant_id is None:
        raise AdminTenantContextRequired("Select an active tenant before using admin commands.")
    if permission not in actor.permissions:
        raise AdminAuthorizationDenied(f"The actor lacks the {permission} permission.")

    result = await auth.database.execute(
        select(Person, Tenant, Membership)
        .select_from(Membership)
        .join(Person, Person.id == Membership.person_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.person_id == actor.person_id,
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise AdminAuthorizationDenied("The actor has no active admin membership in this tenant.")
    person, tenant, membership = row
    if (
        person.status != PersonStatus.ACTIVE.value
        or tenant.status != TenantStatus.ACTIVE.value
        or membership.status != MembershipStatus.ACTIVE.value
        or membership.ended_at is not None
        or membership.role not in {"admin", "owner"}
    ):
        raise AdminAuthorizationDenied("The actor has no active admin membership in this tenant.")
    return actor, tenant_id


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


def _catalog_problem(error: CatalogServiceError) -> DomainError:
    if isinstance(error, CatalogNotFoundError):
        return ResourceNotFound("The program version is unavailable.")
    if isinstance(error, CatalogAccessDeniedError):
        return AdminAuthorizationDenied("The program version is outside the selected tenant scope.")
    if isinstance(error, CatalogConflictError | DraftRequiredError | SupersessionRequiredError):
        return ResourceConflict("The program version cannot be published in its current state.")
    if isinstance(error, CatalogValidationError):
        return CatalogPublicationRejected("The program version failed catalog validation.")
    return CatalogPublicationRejected("The program version could not be published.")


def _publish_response(version: ProgramVersionSnapshot) -> ProgramVersionPublishResponse:
    if version.status != "published" or version.published_at is None:
        raise CatalogPublicationRejected("The catalog service returned a non-published version.")
    return ProgramVersionPublishResponse(
        id=version.id,
        program_id=version.program_id,
        version_number=version.version_number,
        status="published",
        supersedes_version_id=version.supersedes_version_id,
        published_at=version.published_at,
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
) -> None:
    await AuditRepository(auth.database).append_for_actor(
        actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        reason=reason,
        request_id=_request_id(request),
    )


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

    router = APIRouter(prefix="/v1", tags=["admin-learning"])
    actor_dependency = Depends(require_actor)
    resolved_activity = activity_resolver or _default_activity_resolver
    resolved_reviewer = reviewer_resolver or (lambda _access: None)

    @router.post(
        "/admin/program-versions/{program_version_id}/publish",
        response_model=ProgramVersionPublishResponse,
    )
    async def publish_program_version(
        program_version_id: Annotated[UUID, Path()],
        request: Request,
        response: Response,
        body: PublishRequest,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> ProgramVersionPublishResponse:
        require_safe_origin(request, settings)
        actor, tenant_id = await _require_named_admin(
            auth,
            permission="catalog_publish",
        )
        try:
            version = await AsyncCatalogApplication(auth.database).publish_version(
                program_version_id,
                actor=actor,
                tenant_id=tenant_id,
            )
        except CatalogServiceError as exc:
            raise _catalog_problem(exc) from exc
        await _append_admin_audit(
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
        _no_store(response)
        return _publish_response(version)

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
