"""Platform-operator sensitive-segment marks (ADR 0051); IDs only, never segment text."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.conversation_intelligence.sensitive_segment_models import (
    ConversationSensitiveSegmentMark,
)
from ac_platform.conversation_intelligence.sensitive_segments_store import (
    MAX_SEGMENTS_PER_COMMAND,
    SensitiveSegmentInvalid,
    SensitiveSegmentsStore,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.registry import RouteContext, route_installer
from ac_platform.kernel.authz import ActorContext

CAPABILITY = "platform_content_safety_manage"
PREFIX = "/v1/platform/sensitive-segments"
REASON_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 ._:#/-]{2,79}$"
SensitiveCategory = Literal["SENSITIVE_FINANCIAL", "SENSITIVE_LEGAL"]


class SensitiveSegmentMarkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mark_id: UUID
    tenant_id: UUID
    recording_id: UUID
    transcript_revision: str
    segment_id: str
    category: SensitiveCategory
    action: Literal["mark", "release"]
    supersedes_mark_id: UUID | None
    source: Literal["operator", "generation"]
    actor_person_id: UUID
    reason_ref: str
    audit_event_id: UUID
    created_at: datetime


class TranscriptRevisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: str
    segment_count: int


class RecordingSensitiveSegmentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_id: UUID
    tenant_id: UUID
    transcript_revisions: list[TranscriptRevisionResponse]
    marks: list[SensitiveSegmentMarkResponse]


class SegmentMarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_id: str = Field(min_length=1, max_length=128)
    category: SensitiveCategory


class MarkSegmentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_revision: str = Field(min_length=1, max_length=256)
    segments: list[SegmentMarkRequest] = Field(min_length=1, max_length=MAX_SEGMENTS_PER_COMMAND)
    reason_ref: str = Field(pattern=REASON_REF_PATTERN)


class MarkSegmentsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recording_id: UUID
    marks: list[SensitiveSegmentMarkResponse]


class ReleaseMarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_ref: str = Field(pattern=REASON_REF_PATTERN)


def _mark(row: ConversationSensitiveSegmentMark) -> SensitiveSegmentMarkResponse:
    return SensitiveSegmentMarkResponse(
        mark_id=row.id,
        tenant_id=row.tenant_id,
        recording_id=row.recording_id,
        transcript_revision=row.transcript_revision,
        segment_id=row.segment_id,
        category=row.category,
        action=row.action,
        supersedes_mark_id=row.supersedes_mark_id,
        source=row.source,
        actor_person_id=row.actor_person_id,
        reason_ref=row.reason_ref,
        audit_event_id=row.audit_event_id,
        created_at=(
            row.created_at
            if row.created_at.tzinfo is not None
            else row.created_at.replace(tzinfo=UTC)
        ),
    )


def _idempotency_key(value: str | None) -> str:
    if value is None or not value.strip():
        raise SensitiveSegmentInvalid("This command requires Idempotency-Key.")
    return value.strip()


def _no_store(response: Response) -> None:
    response.headers["cache-control"] = "private, no-store"
    response.headers["pragma"] = "no-cache"


async def _validation_without_input(request: Request, error: Exception) -> Response:
    """Never echo a request body back on these routes; report locations and messages only."""

    if not isinstance(error, RequestValidationError):  # pragma: no cover - FastAPI contract
        raise error
    if not request.url.path.startswith(PREFIX):
        return await request_validation_exception_handler(request, error)
    detail = [
        {"loc": item.get("loc", ()), "msg": item.get("msg", ""), "type": item.get("type", "")}
        for item in error.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": detail},
        headers={"cache-control": "private, no-store", "pragma": "no-cache"},
    )


def install_platform_sensitive_segments_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    def require_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    router = APIRouter(prefix=PREFIX, dependencies=[Depends(require_surface)])
    application.add_exception_handler(RequestValidationError, _validation_without_input)
    actor_dependency = Depends(require_actor, scope="function")

    async def require_operator(request: Request, auth: AuthenticatedTransaction) -> ActorContext:
        if request.query_params:
            raise SensitiveSegmentInvalid("Sensitive-segment routes take no query parameters.")
        actor = auth.resolved.actor
        permissions = await platform_projection(
            auth.database, actor, operations_tenant_id=settings.operations_tenant_id
        )
        if CAPABILITY not in permissions:
            raise CapabilityDenied("A current content-safety assignment is required.")
        return actor

    @router.get("/recordings/{recording_id}", response_model=RecordingSensitiveSegmentsResponse)
    async def recording(
        request: Request,
        response: Response,
        recording_id: UUID,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> RecordingSensitiveSegmentsResponse:
        await require_operator(request, auth)
        view = await SensitiveSegmentsStore(auth.database).recording(recording_id)
        _no_store(response)
        return RecordingSensitiveSegmentsResponse(
            recording_id=view.recording_id,
            tenant_id=view.tenant_id,
            transcript_revisions=[
                TranscriptRevisionResponse(revision=item.revision, segment_count=item.segment_count)
                for item in view.transcript_revisions
            ],
            marks=[_mark(row) for row in view.marks],
        )

    @router.post("/recordings/{recording_id}/marks", response_model=MarkSegmentsResponse)
    async def mark(
        request: Request,
        response: Response,
        recording_id: UUID,
        body: MarkSegmentsRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> MarkSegmentsResponse:
        require_safe_origin(request, settings)
        actor = await require_operator(request, auth)
        rows = await SensitiveSegmentsStore(auth.database).mark(
            actor,
            recording_id=recording_id,
            transcript_revision=body.transcript_revision,
            segments=[(item.segment_id, item.category) for item in body.segments],
            reason_ref=body.reason_ref,
            idempotency_key=_idempotency_key(idempotency_key),
        )
        _no_store(response)
        return MarkSegmentsResponse(recording_id=recording_id, marks=[_mark(row) for row in rows])

    @router.post("/marks/{mark_id}/release", response_model=SensitiveSegmentMarkResponse)
    async def release(
        request: Request,
        response: Response,
        mark_id: UUID,
        body: ReleaseMarkRequest,
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key", max_length=128)
        ] = None,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> SensitiveSegmentMarkResponse:
        require_safe_origin(request, settings)
        actor = await require_operator(request, auth)
        row = await SensitiveSegmentsStore(auth.database).release(
            actor,
            mark_id=mark_id,
            reason_ref=body.reason_ref,
            idempotency_key=_idempotency_key(idempotency_key),
        )
        _no_store(response)
        return _mark(row)

    application.include_router(router)


__all__ = [
    "MarkSegmentsRequest",
    "MarkSegmentsResponse",
    "RecordingSensitiveSegmentsResponse",
    "ReleaseMarkRequest",
    "SensitiveSegmentMarkResponse",
    "install_platform_sensitive_segments_http",
]


@route_installer(order=1400)
def _install_routes(context: RouteContext) -> None:
    install_platform_sensitive_segments_http(
        context.application, settings=context.settings, require_actor=context.require_actor
    )
