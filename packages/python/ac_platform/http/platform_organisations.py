"""Platform-operator member management for any registered organisation."""

import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.organisation import MemberResponse, MembersResponse, OwnerTransferResponse
from ac_platform.kernel.errors import DomainError, ResourceNotFound
from ac_platform.organisations.service import OrganisationService
from ac_platform.organisations.usage import member_rows
from ac_platform.tenancy.models import Membership, Organisation, Tenant

READ_CAPABILITY = "platform_tenants_read"
MANAGE_CAPABILITY = "platform_organisations_manage"
# The reason becomes the audit operator reference of the write.
Reason = Annotated[str, Field(min_length=3, max_length=200)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class PlatformOrganisationResponse(_Strict):
    tenant_id: UUID
    name: str
    member_count: int
    created_at: datetime


class PlatformOrganisationsResponse(_Strict):
    organisations: list[PlatformOrganisationResponse]


class ReasonRequest(_Strict):
    reason: Reason


class OperatorAddMemberRequest(ReasonRequest):
    email: str
    role: Literal["admin", "member"]


class OperatorChangeRoleRequest(ReasonRequest):
    role: Literal["admin", "member"]


class OperatorTransferOwnerRequest(ReasonRequest):
    # A JSON body carries the identifier as a string.
    person_id: UUID = Field(strict=False)


def _command_id(value: Annotated[str, Header(alias="Idempotency-Key")]) -> UUID:
    try:
        parsed = UUID(value.strip())
    except ValueError as error:
        raise DomainError("Idempotency-Key must be a canonical UUIDv4.") from error
    if parsed.version != 4 or str(parsed) != value.strip().lower():
        raise DomainError("Idempotency-Key must be a canonical UUIDv4.")
    return parsed


def install_platform_organisations_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    def require_surface(request: Request) -> None:
        require_admin_surface(request, settings)

    router = APIRouter(
        prefix="/v1/platform/organisations",
        tags=["platform-organisations"],
        dependencies=[Depends(require_surface)],
    )
    actor_dependency = Depends(require_actor, scope="function")
    command_dependency = Depends(_command_id)
    protected = {settings.operations_tenant_id, settings.public_learner_tenant_id}

    async def require_capability(auth: AuthenticatedTransaction, capability: str) -> None:
        permissions = await platform_projection(
            auth.database, auth.resolved.actor, operations_tenant_id=settings.operations_tenant_id
        )
        if capability not in permissions:
            raise CapabilityDenied("A current platform organisation assignment is required.")

    async def require_organisation(
        auth: AuthenticatedTransaction, tenant_id: UUID, capability: str
    ) -> None:
        # The capability is checked first, so a caller without it learns nothing
        # about which tenants exist.
        await require_capability(auth, capability)
        if tenant_id in protected or await auth.database.get(Organisation, tenant_id) is None:
            raise ResourceNotFound("Organisation not found.")

    async def manage(
        request: Request, auth: AuthenticatedTransaction, tenant_id: UUID
    ) -> OrganisationService:
        require_safe_origin(request, settings)
        await require_organisation(auth, tenant_id, MANAGE_CAPABILITY)
        if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
            raise DomainError("Organisation tenant boundaries are not configured.")
        return OrganisationService(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
        )

    @router.get("", response_model=PlatformOrganisationsResponse)
    async def organisations(
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> PlatformOrganisationsResponse:
        await require_capability(auth, READ_CAPABILITY)
        member_count = (
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == Organisation.tenant_id,
                Membership.role != "processing",
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
            .correlate(Organisation)
            .scalar_subquery()
        )
        rows = await auth.database.execute(
            select(Organisation.tenant_id, Tenant.name, member_count, Organisation.created_at)
            .join(Tenant, Tenant.id == Organisation.tenant_id)
            .where(Organisation.tenant_id.not_in([item for item in protected if item is not None]))
            .order_by(Organisation.created_at.desc(), Organisation.tenant_id)
        )
        return PlatformOrganisationsResponse(
            organisations=[
                PlatformOrganisationResponse(
                    tenant_id=tenant_id,
                    name=name,
                    member_count=count or 0,
                    created_at=created
                    if created.tzinfo is not None
                    else created.replace(tzinfo=UTC),
                )
                for tenant_id, name, count, created in rows
            ]
        )

    @router.get("/{tenant_id}/members", response_model=MembersResponse)
    async def members(
        tenant_id: UUID, auth: AuthenticatedTransaction = actor_dependency
    ) -> MembersResponse:
        await require_organisation(auth, tenant_id, READ_CAPABILITY)
        rows = {"members": await member_rows(auth.database, tenant_id)}
        return MembersResponse.model_validate_json(json.dumps(rows))

    @router.post("/{tenant_id}/members", response_model=MemberResponse)
    async def add(
        request: Request,
        tenant_id: UUID,
        body: OperatorAddMemberRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> MemberResponse:
        result = await (await manage(request, auth, tenant_id)).request_member(
            tenant_id,
            body.email,
            body.role,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            operator_reference=body.reason,
        )
        return MemberResponse.model_validate_json(json.dumps(result))

    @router.patch("/{tenant_id}/members/{person_id}", response_model=MemberResponse)
    async def change_role(
        request: Request,
        tenant_id: UUID,
        person_id: UUID,
        body: OperatorChangeRoleRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> MemberResponse:
        result = await (await manage(request, auth, tenant_id)).change_member_role(
            tenant_id,
            person_id,
            body.role,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            operator_reference=body.reason,
        )
        return MemberResponse.model_validate_json(json.dumps(result))

    @router.delete("/{tenant_id}/members/{person_id}", status_code=204)
    async def remove(
        request: Request,
        tenant_id: UUID,
        person_id: UUID,
        body: ReasonRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> None:
        await (await manage(request, auth, tenant_id)).remove_member(
            tenant_id,
            person_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            operator_reference=body.reason,
        )

    @router.post("/{tenant_id}/owner", response_model=OwnerTransferResponse)
    async def transfer_owner(
        request: Request,
        tenant_id: UUID,
        body: OperatorTransferOwnerRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> OwnerTransferResponse:
        result = await (await manage(request, auth, tenant_id)).transfer_ownership(
            tenant_id,
            body.person_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            operator_reference=body.reason,
        )
        return OwnerTransferResponse.model_validate_json(json.dumps(result))

    @router.delete("/{tenant_id}/invites/{invite_id}", status_code=204)
    async def revoke(
        request: Request,
        tenant_id: UUID,
        invite_id: UUID,
        body: ReasonRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> None:
        await (await manage(request, auth, tenant_id)).revoke_invite(
            tenant_id,
            invite_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            operator_reference=body.reason,
        )

    application.include_router(router)
