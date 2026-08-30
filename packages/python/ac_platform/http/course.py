"""Published-course queries and the self-only free-enrollment HTTP boundary."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.application.settings import Settings
from ac_platform.catalog.models import (
    Activity,
    CatalogScope,
    Module,
    ModulePrerequisite,
    Program,
    ProgramVersion,
    ProgramVersionStatus,
)
from ac_platform.enrollment.services import (
    AsyncEnrollmentApplication,
    EnrollmentResult,
    FreeEnrollmentCommand,
)
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_safe_origin,
)
from ac_platform.kernel.errors import DomainError

MAX_PUBLIC_PROGRAM_PAGE = 50


class PublicProgramNotFound(DomainError):
    code = "program_not_found"
    title = "Program not found"
    status = 404


class TenantContextRequired(DomainError):
    code = "tenant_context_required"
    title = "A tenant context is required"
    status = 403


class InvalidCollectionCursor(DomainError):
    code = "invalid_cursor"
    title = "The collection cursor is invalid"
    status = 400


class ActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    kind: str
    title: str
    is_required: bool


class ModuleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    position: int
    title: str
    prerequisite_module_ids: list[UUID]
    activities: list[ActivityResponse]


class ProgramSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    slug: str
    title: str
    program_version_id: UUID
    version_number: int
    published_at: str


class ProgramCollectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ProgramSummaryResponse]
    next_cursor: str | None


class ProgramDetailResponse(ProgramSummaryResponse):
    modules: list[ModuleResponse]


class FreeEnrollmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_version_id: UUID


class FreeEnrollmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    entitlement_id: UUID
    provenance_id: UUID
    created: bool
    replayed: bool


@dataclass(frozen=True, slots=True)
class _ProgramCursor:
    slug: str
    program_id: UUID


def _encode_cursor(cursor: _ProgramCursor) -> str:
    payload = json.dumps(
        {"slug": cursor.slug, "program_id": str(cursor.program_id)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def _decode_cursor(value: str) -> _ProgramCursor:
    try:
        raw = base64.b64decode(
            value.encode("ascii") + b"=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict) or set(payload) != {"slug", "program_id"}:
            raise ValueError("unexpected cursor fields")
        slug = str(payload["slug"])
        if not slug or len(slug) > 120:
            raise ValueError("invalid slug")
        return _ProgramCursor(slug=slug, program_id=UUID(str(payload["program_id"])))
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidCollectionCursor("The supplied collection cursor is malformed.") from exc


def _summary(program: Program, version: ProgramVersion) -> ProgramSummaryResponse:
    if version.published_at is None:  # Protected again in SQL; keep the serializer fail closed.
        raise PublicProgramNotFound("The published program is unavailable.")
    return ProgramSummaryResponse(
        id=program.id,
        slug=program.slug,
        title=program.title,
        program_version_id=version.id,
        version_number=version.version_number,
        published_at=version.published_at.isoformat(),
    )


def _enrollment_response(result: EnrollmentResult) -> FreeEnrollmentResponse:
    return FreeEnrollmentResponse(
        enrollment_id=result.enrollment_id,
        entitlement_id=result.entitlement_id,
        provenance_id=result.provenance_id,
        created=result.created,
        replayed=result.replayed,
    )


def install_course_http(
    application: FastAPI,
    *,
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    require_actor: RequireActor,
) -> None:
    """Register published reads and self-only enrollment composition."""

    router = APIRouter(prefix="/v1", tags=["course"])
    actor_dependency = Depends(require_actor)

    @router.get("/programs", response_model=ProgramCollectionResponse)
    async def list_programs(
        limit: Annotated[int, Query(ge=1, le=MAX_PUBLIC_PROGRAM_PAGE)] = 20,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
    ) -> ProgramCollectionResponse:
        decoded = None if cursor is None else _decode_cursor(cursor)
        statement = (
            select(Program, ProgramVersion)
            .join(ProgramVersion, ProgramVersion.program_id == Program.id)
            .where(
                Program.scope == CatalogScope.GLOBAL.value,
                ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
                ProgramVersion.published_at.is_not(None),
            )
            .order_by(Program.slug, Program.id)
            .limit(limit + 1)
        )
        if decoded is not None:
            statement = statement.where(
                or_(
                    Program.slug > decoded.slug,
                    and_(Program.slug == decoded.slug, Program.id > decoded.program_id),
                )
            )
        async with sessions() as database, database.begin():
            rows = list((await database.execute(statement)).tuples())
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last_program = visible[-1][0]
            next_cursor = _encode_cursor(
                _ProgramCursor(slug=last_program.slug, program_id=last_program.id)
            )
        return ProgramCollectionResponse(
            items=[_summary(program, version) for program, version in visible],
            next_cursor=next_cursor,
        )

    @router.get("/programs/{slug}", response_model=ProgramDetailResponse)
    async def get_program(slug: str, response: Response) -> ProgramDetailResponse:
        async with sessions() as database, database.begin():
            row = (
                await database.execute(
                    select(Program, ProgramVersion)
                    .join(ProgramVersion, ProgramVersion.program_id == Program.id)
                    .where(
                        Program.scope == CatalogScope.GLOBAL.value,
                        Program.slug == slug,
                        ProgramVersion.status == ProgramVersionStatus.PUBLISHED.value,
                        ProgramVersion.published_at.is_not(None),
                    )
                )
            ).one_or_none()
            if row is None:
                raise PublicProgramNotFound("The requested published program is unavailable.")
            program, version = row
            modules = list(
                await database.scalars(
                    select(Module)
                    .where(Module.program_version_id == version.id)
                    .order_by(Module.position, Module.id)
                )
            )
            activities = list(
                await database.scalars(
                    select(Activity)
                    .where(Activity.program_version_id == version.id)
                    .order_by(Activity.module_id, Activity.position, Activity.id)
                )
            )
            prerequisites = list(
                await database.scalars(
                    select(ModulePrerequisite).where(
                        ModulePrerequisite.program_version_id == version.id
                    )
                )
            )
        activities_by_module: dict[UUID, list[ActivityResponse]] = {}
        for activity in activities:
            activities_by_module.setdefault(activity.module_id, []).append(
                ActivityResponse(
                    id=activity.id,
                    position=activity.position,
                    kind=activity.kind,
                    title=activity.title,
                    is_required=activity.is_required,
                )
            )
        prerequisites_by_module: dict[UUID, list[UUID]] = {}
        for prerequisite in prerequisites:
            prerequisites_by_module.setdefault(prerequisite.module_id, []).append(
                prerequisite.prerequisite_module_id
            )
        summary = _summary(program, version)
        response.headers["etag"] = f'"program-version-{version.id}"'
        response.headers["cache-control"] = "public, max-age=60, stale-while-revalidate=300"
        return ProgramDetailResponse(
            **summary.model_dump(),
            modules=[
                ModuleResponse(
                    id=module.id,
                    position=module.position,
                    title=module.title,
                    prerequisite_module_ids=sorted(
                        prerequisites_by_module.get(module.id, []), key=str
                    ),
                    activities=activities_by_module.get(module.id, []),
                )
                for module in modules
            ],
        )

    @router.post("/enrollments/free", response_model=FreeEnrollmentResponse)
    async def enroll_free(
        request: Request,
        response: Response,
        body: FreeEnrollmentRequest,
        idempotency_key: Annotated[
            str,
            Header(alias="Idempotency-Key", min_length=1, max_length=200),
        ],
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> FreeEnrollmentResponse:
        require_safe_origin(request, settings)
        tenant_id = auth.resolved.actor.tenant_id
        if tenant_id is None:
            raise TenantContextRequired(
                "Select an active learner tenant before requesting enrollment."
            )
        result = await AsyncEnrollmentApplication(auth.database).enroll_free(
            FreeEnrollmentCommand(
                actor_person_id=auth.resolved.actor.person_id,
                subject_person_id=auth.resolved.actor.person_id,
                tenant_id=tenant_id,
                program_version_id=body.program_version_id,
                idempotency_key=idempotency_key,
            ),
            actor=auth.resolved.actor,
        )
        response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
        response.headers["cache-control"] = "no-store"
        return _enrollment_response(result)

    application.include_router(router)


__all__ = [
    "ActivityResponse",
    "FreeEnrollmentResponse",
    "InvalidCollectionCursor",
    "ModuleResponse",
    "ProgramCollectionResponse",
    "ProgramDetailResponse",
    "PublicProgramNotFound",
    "TenantContextRequired",
    "install_course_http",
]
