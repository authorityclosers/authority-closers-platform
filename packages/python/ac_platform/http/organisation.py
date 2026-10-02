"""Owner-contract API for the authenticated session's selected organisation."""

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor
from ac_platform.identity.services import TenantScopeDeniedError
from ac_platform.kernel.errors import ResourceNotFound
from ac_platform.organisations.usage import member_rows
from ac_platform.tenancy.models import Membership, Organisation, OrganisationDomainSetting, Tenant


class OrganisationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    name: str
    role: Literal["owner", "admin", "member"]
    verified_domains: list[str]
    auto_join: bool
    member_count: int


class MemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    person_id: UUID | None
    invite_id: UUID | None
    name: str | None
    email: str | None
    role: Literal["owner", "admin", "member"]
    status: Literal["active", "invited"]
    joined_at: datetime | None
    last_active_at: datetime | None
    minutes_used_30d: float
    calls_30d: int


class MembersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    members: list[MemberResponse]


def install_organisation_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1/organisation", tags=["organisation"])

    async def organisation_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            async for auth in require_actor.read_only(request):  # type: ignore[attr-defined]
                yield auth
        except TenantScopeDeniedError as error:
            raise ResourceNotFound("No organisation selected.") from error

    actor_dependency = Depends(organisation_actor, scope="function")

    async def selected(
        response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> AuthenticatedTransaction:
        tenant_id = auth.resolved.actor.tenant_id
        # Canonical authentication holds the active tenant and membership fences.
        if (
            tenant_id in {None, settings.public_learner_tenant_id, settings.operations_tenant_id}
            or auth.resolved.membership_role not in {"owner", "admin", "member"}
            or await auth.database.get(Organisation, tenant_id) is None
        ):
            raise ResourceNotFound("No organisation selected.")
        response.headers["cache-control"] = "private, no-store"
        response.headers["vary"] = "Cookie"
        return auth

    selected_dependency = Depends(selected, scope="function")

    @router.get("", response_model=OrganisationResponse)
    async def organisation(
        auth: AuthenticatedTransaction = selected_dependency,
    ) -> OrganisationResponse:
        tenant_id = auth.resolved.actor.tenant_id
        tenant = await auth.database.get(Tenant, tenant_id)
        assert tenant is not None
        domains = await auth.database.scalar(
            select(OrganisationDomainSetting)
            .where(OrganisationDomainSetting.tenant_id == tenant_id)
            .order_by(OrganisationDomainSetting.version.desc())
            .limit(1)
        )
        count = await auth.database.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        return OrganisationResponse(
            tenant_id=tenant.id,
            name=tenant.name,
            role=cast(Literal["owner", "admin", "member"], auth.resolved.membership_role),
            verified_domains=[] if domains is None else domains.verified_domains,
            auto_join=False if domains is None else domains.auto_join,
            member_count=count or 0,
        )

    @router.get("/members", response_model=MembersResponse)
    async def members(auth: AuthenticatedTransaction = selected_dependency) -> MembersResponse:
        actor = auth.resolved.actor
        assert actor.tenant_id is not None
        rows = {
            "members": await member_rows(
                auth.database,
                actor.tenant_id,
                actor.person_id if auth.resolved.membership_role == "member" else None,
            )
        }
        return MembersResponse.model_validate_json(json.dumps(rows))

    application.include_router(router)
