"""HTTP composition for the learner course-completion certificate read."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Path, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ac_platform.certificates.models import COURSE_COMPLETION_CERTIFICATE_TYPE
from ac_platform.certificates.services import (
    CertificateNotFoundError,
    CertificateView,
    CourseCompletionCertificateData,
    CourseCompletionCertificateService,
    SqlAlchemyCertificateRepository,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.kernel.authz import ActorContext
from ac_platform.kernel.errors import DomainError

CertificateStatus = Literal["issued", "corrected", "revoked"]


class CertificateTenantContextRequired(DomainError):
    """The authenticated session has not selected an active tenant context."""

    code = "certificate_tenant_context_required"
    title = "A tenant context is required"
    status = 403


class CertificateCompletionResponse(BaseModel):
    """Safe, learner-facing summary of the server-authoritative predicate."""

    model_config = ConfigDict(extra="forbid")

    predicate_version: str = Field(min_length=1, max_length=64)
    required_activity_count: int = Field(ge=1)
    completed_activity_count: int = Field(ge=0)
    is_complete: Literal[True]
    captured_at: datetime


class CertificateResponse(BaseModel):
    """Safe certificate representation without internal identity or audit data."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    certificate_type: Literal["course-completion"]
    program_id: UUID
    program_version_id: UUID
    issued_at: datetime
    status: CertificateStatus
    completion: CertificateCompletionResponse


def _tenant_context(actor: ActorContext) -> UUID:
    tenant_id = actor.tenant_id
    if tenant_id is None:
        raise CertificateTenantContextRequired(
            "Select an active tenant before reading a course-completion certificate."
        )
    return tenant_id


async def _run_in_auth_transaction[ResultT](
    auth: AuthenticatedTransaction,
    operation: Callable[[Session], ResultT],
) -> ResultT:
    """Run the synchronous certificate service on the caller-owned transaction."""

    return cast(ResultT, await auth.database.run_sync(operation))


def _completion_matches_certificate(
    certificate: CourseCompletionCertificateData,
    completion: object,
) -> bool:
    return (
        certificate.enrollment_id is not None
        and getattr(completion, "tenant_id", None) == certificate.tenant_id
        and getattr(completion, "person_id", None) == certificate.person_id
        and getattr(completion, "enrollment_id", None) == certificate.enrollment_id
        and getattr(completion, "program_id", None) == certificate.program_id
        and getattr(completion, "program_version_id", None) == certificate.program_version_id
        and getattr(completion, "program_scope", None) == certificate.program_scope
        and getattr(completion, "program_tenant_id", None) == certificate.program_tenant_id
        and getattr(completion, "program_owner_key", None) == certificate.program_owner_key
    )


def _require_visible_completion(view: CertificateView) -> None:
    certificate = view.certificate
    if certificate.certificate_type != COURSE_COMPLETION_CERTIFICATE_TYPE:
        raise CertificateNotFoundError("certificate does not exist")
    for completion in (view.original_completion, view.current_completion):
        if not _completion_matches_certificate(certificate, completion):
            raise CertificateNotFoundError("certificate completion is unavailable")
        if (
            not completion.is_complete
            or completion.required_activity_count <= 0
            or completion.completed_activity_count != completion.required_activity_count
        ):
            raise CertificateNotFoundError("certificate completion is unavailable")


def _certificate_response(view: CertificateView) -> CertificateResponse:
    _require_visible_completion(view)
    event_type = view.current_event.event_type
    if event_type.value not in {"issued", "corrected", "revoked"}:
        raise CertificateNotFoundError("certificate status is unavailable")
    status_value: CertificateStatus = event_type.value
    completion = view.current_completion
    return CertificateResponse(
        id=view.certificate.id,
        certificate_type=COURSE_COMPLETION_CERTIFICATE_TYPE,
        program_id=view.certificate.program_id,
        program_version_id=view.certificate.program_version_id,
        issued_at=view.certificate.issued_at,
        status=status_value,
        completion=CertificateCompletionResponse(
            predicate_version=completion.predicate_version,
            required_activity_count=completion.required_activity_count,
            completed_activity_count=completion.completed_activity_count,
            is_complete=True,
            captured_at=completion.captured_at,
        ),
    )


def _read_certificate(
    database: Session,
    *,
    actor: ActorContext,
    certificate_id: UUID,
    tenant_id: UUID,
) -> CertificateView:
    repository = SqlAlchemyCertificateRepository(database)
    return CourseCompletionCertificateService(repository).read(
        certificate_id,
        actor_person_id=actor.person_id,
        tenant_id=tenant_id,
    )


def install_certificate_http(
    application: FastAPI,
    *,
    require_actor: RequireActor,
) -> None:
    """Register the self-scoped learner certificate read route."""

    router = APIRouter(prefix="/v1", tags=["certificates"])
    actor_dependency = Depends(require_actor)

    @router.get("/certificates/{certificate_id}", response_model=CertificateResponse)
    async def get_certificate(
        certificate_id: Annotated[UUID, Path()],
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> CertificateResponse:
        actor = auth.resolved.actor
        tenant_id = _tenant_context(actor)
        view = await _run_in_auth_transaction(
            auth,
            lambda database: _read_certificate(
                database,
                actor=actor,
                certificate_id=certificate_id,
                tenant_id=tenant_id,
            ),
        )
        response.headers["cache-control"] = "no-store"
        response.headers["pragma"] = "no-cache"
        return _certificate_response(view)

    application.include_router(router)


# Keep both singular and resource-plural installer names discoverable while
# the application composition root decides when to wire this slice.
install_certificates_http = install_certificate_http


__all__ = [
    "CertificateCompletionResponse",
    "CertificateResponse",
    "CertificateStatus",
    "CertificateTenantContextRequired",
    "install_certificate_http",
    "install_certificates_http",
]
