"""HTTP adapter for the bounded Admin People lookup and diagnosis read."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.application.settings import Settings
from ac_platform.audit.service import AuditRepository
from ac_platform.http.admin_learning import (
    _no_store,
    _request_id,
    _require_named_admin,
)
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.learning.admin_diagnosis import (
    MAX_LOOKUP_QUERY_LENGTH,
    DiagnosisLookupInvalid,
    DiagnosisPurpose,
    LearnerDiagnosis,
    LearnerLookupResult,
    diagnose_learner,
    lookup_learners,
)


class LearnerLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_LOOKUP_QUERY_LENGTH)
    purpose: DiagnosisPurpose


class LearnerLookupCandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_id: UUID
    display_name: str = Field(min_length=1)
    username: str | None
    masked_email: str = Field(min_length=1)
    membership_status: Literal["active"]
    membership_role: Literal["learner"]


class LearnerLookupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    redaction_version: str = Field(min_length=1)
    candidates: list[LearnerLookupCandidateResponse]
    truncated: bool


class ActivityStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    state: str
    required: bool
    reason: str = Field(min_length=1)
    missing_activity_ids: list[UUID] = Field(max_length=500)
    missing_module_ids: list[UUID] = Field(max_length=500)


class ProgressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    projection_version: str = Field(min_length=1)
    denominator: int
    completed_count: int
    percentage: float
    next_activity_id: UUID | None
    activity_states: list[ActivityStateResponse] = Field(max_length=500)
    activity_states_truncated: bool


class DraftResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    present: bool
    revision: int
    saved_at: datetime


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: UUID
    evidence_type: str = Field(min_length=1)
    submission_status: str | None
    captured_at: datetime
    submitted_at: datetime | None


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    program_id: UUID
    program_title: str = Field(min_length=1)
    program_version_id: UUID
    version_number: int
    enrollment_status: str
    entitlement_status: str
    progress: ProgressResponse | None
    truncated: bool
    drafts_truncated: bool
    drafts: list[DraftResponse]
    evidence_truncated: bool
    evidence: list[EvidenceResponse]


class LearnerDiagnosisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    person_id: UUID
    display_name: str = Field(min_length=1)
    username: str | None
    masked_email: str = Field(min_length=1)
    membership_status: Literal["active"]
    membership_role: Literal["learner"]
    purpose: DiagnosisPurpose
    redaction_version: str = Field(min_length=1)
    as_of: datetime
    enrollments: list[EnrollmentResponse] = Field(max_length=25)
    truncated: bool


def _lookup_response(result: LearnerLookupResult) -> LearnerLookupResponse:
    return LearnerLookupResponse(
        tenant_id=result.tenant_id,
        redaction_version=result.redaction_version,
        candidates=[
            LearnerLookupCandidateResponse(
                person_id=item.person_id,
                display_name=item.display_name,
                username=item.username,
                masked_email=item.masked_email,
                membership_status=item.membership_status,
                membership_role=item.membership_role,
            )
            for item in result.candidates
        ],
        truncated=result.truncated,
    )


def _diagnosis_response(result: LearnerDiagnosis) -> LearnerDiagnosisResponse:
    return LearnerDiagnosisResponse(
        tenant_id=result.tenant_id,
        person_id=result.person_id,
        display_name=result.display_name,
        username=result.username,
        masked_email=result.masked_email,
        membership_status=result.membership_status,
        membership_role=result.membership_role,
        purpose=DiagnosisPurpose(result.purpose),
        redaction_version=result.redaction_version,
        as_of=result.as_of,
        enrollments=[
            EnrollmentResponse(
                enrollment_id=enrollment.enrollment_id,
                program_id=enrollment.program_id,
                program_title=enrollment.program_title,
                program_version_id=enrollment.program_version_id,
                version_number=enrollment.version_number,
                enrollment_status=enrollment.enrollment_status,
                entitlement_status=enrollment.entitlement_status,
                progress=(
                    None
                    if enrollment.progress is None
                    else ProgressResponse(
                        projection_version=enrollment.progress.projection_version,
                        denominator=enrollment.progress.denominator,
                        completed_count=enrollment.progress.completed_count,
                        percentage=enrollment.progress.percentage,
                        next_activity_id=enrollment.progress.next_activity_id,
                        activity_states_truncated=enrollment.progress.activity_states_truncated,
                        activity_states=[
                            ActivityStateResponse(
                                activity_id=item.activity_id,
                                title=item.title,
                                kind=item.kind,
                                state=item.state,
                                required=item.required,
                                reason=item.reason,
                                missing_activity_ids=list(item.missing_activity_ids),
                                missing_module_ids=list(item.missing_module_ids),
                            )
                            for item in enrollment.progress.activity_states
                        ],
                    )
                ),
                drafts=[
                    DraftResponse(
                        activity_id=item.activity_id,
                        present=item.present,
                        revision=item.revision,
                        saved_at=item.saved_at,
                    )
                    for item in enrollment.drafts
                ],
                truncated=enrollment.truncated,
                drafts_truncated=enrollment.drafts_truncated,
                evidence=[
                    EvidenceResponse(
                        activity_id=item.activity_id,
                        evidence_type=item.evidence_type,
                        submission_status=item.submission_status,
                        captured_at=item.captured_at,
                        submitted_at=item.submitted_at,
                    )
                    for item in enrollment.evidence
                ],
                evidence_truncated=enrollment.evidence_truncated,
            )
            for enrollment in result.enrollments
        ],
        truncated=result.truncated,
    )


def _reject_extra_query_parameters(request: Request, *, allowed: set[str]) -> None:
    names = [name for name, _value in request.query_params.multi_items()]
    if set(names) - allowed or len(names) != len(set(names)):
        raise DiagnosisLookupInvalid("Only the explicit diagnosis purpose is accepted.")


def _function_scoped_actor_dependency(require_actor: RequireActor) -> Any:
    """Keep the audit transaction function-scoped before the response is sent."""

    return Depends(require_actor, scope="function")


async def _append_read_audit(
    auth: AuthenticatedTransaction,
    *,
    actor: Any,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    purpose: DiagnosisPurpose,
    count: int,
    request: Request,
) -> None:
    await AuditRepository(auth.database).append_for_actor(
        actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload={
            "purpose": purpose.value,
            "redaction_version": "admin-learner-v1",
            "result_count": count,
        },
        reason=purpose.value,
        request_id=_request_id(request),
    )


def install_admin_diagnosis_http(
    application: FastAPI,
    *,
    settings: Settings,
    require_actor: RequireActor,
) -> None:
    """Install the selected-tenant, metadata-only People read boundary."""

    def require_admin_route_surface(request: Request) -> None:
        from ac_platform.http.auth import require_admin_surface

        require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1",
        tags=["admin-learning"],
        dependencies=[Depends(require_admin_route_surface)],
    )
    actor_dependency = _function_scoped_actor_dependency(require_actor)

    @router.post(
        "/admin/learners/lookup",
        response_model=LearnerLookupResponse,
    )
    async def lookup(
        request: Request,
        response: Response,
        body: LearnerLookupRequest,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> LearnerLookupResponse:
        _reject_extra_query_parameters(request, allowed=set())
        require_safe_origin(request, settings)
        actor, tenant_id = await _require_named_admin(
            auth,
            permission="learner_diagnose",
            lock=False,
        )
        result = await auth.database.run_sync(
            lambda database: lookup_learners(
                database,
                tenant_id=tenant_id,
                query=body.query,
            )
        )
        await _append_read_audit(
            auth,
            actor=actor,
            action="audit.admin.learner.lookup.v1",
            resource_type="tenant",
            resource_id=tenant_id,
            purpose=body.purpose,
            count=len(result.candidates),
            request=request,
        )
        _no_store(response)
        return _lookup_response(result)

    @router.get(
        "/admin/learners/{person_id}/diagnosis",
        response_model=LearnerDiagnosisResponse,
    )
    async def diagnosis(
        request: Request,
        response: Response,
        person_id: UUID,
        purpose: Annotated[DiagnosisPurpose, Query()],
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> LearnerDiagnosisResponse:
        _reject_extra_query_parameters(request, allowed={"purpose"})
        actor, tenant_id = await _require_named_admin(
            auth,
            permission="learner_diagnose",
            lock=False,
        )
        result = await auth.database.run_sync(
            lambda database: diagnose_learner(
                database,
                tenant_id=tenant_id,
                person_id=person_id,
                purpose=purpose.value,
            )
        )
        await _append_read_audit(
            auth,
            actor=actor,
            action="audit.admin.learner.diagnosed.v1",
            resource_type="person",
            resource_id=person_id,
            purpose=purpose,
            count=len(result.enrollments),
            request=request,
        )
        _no_store(response)
        return _diagnosis_response(result)

    application.include_router(router)


__all__ = [
    "LearnerDiagnosisResponse",
    "LearnerLookupRequest",
    "LearnerLookupResponse",
    "install_admin_diagnosis_http",
]
