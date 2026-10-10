"""Owner-contract API for the authenticated session's selected organisation."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.http.auth import AuthenticatedTransaction, RequireActor, require_safe_origin
from ac_platform.http.organisation_settings import install_organisation_settings_routes
from ac_platform.identity.models import Person
from ac_platform.identity.services import TenantScopeDeniedError, normalize_email
from ac_platform.kernel.errors import AuthorizationDenied, DomainError, ResourceNotFound
from ac_platform.organisations.activity import organisation_activity
from ac_platform.organisations.invitations import invitation_policies
from ac_platform.organisations.seats import seat_exempt
from ac_platform.organisations.service import OrganisationService
from ac_platform.organisations.usage import member_rows, organisation_pool, organisation_seats
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    OrganisationInvite,
    Tenant,
)


class OrganisationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    name: str
    role: Literal["owner", "admin", "member"]
    verified_domains: list[str]
    auto_join: bool
    member_count: int


class OrganisationProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: UUID
    handle: str
    name: str
    your_role: Literal["owner", "admin", "member"]


class ChangeHandleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    handle: str


class CreateOrganisationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=80)


class PendingInviteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invite_id: UUID
    tenant_id: UUID
    organisation_name: str
    role: Literal["admin", "member"]
    invited_at: datetime
    expires_at: datetime | None


class PendingInvitesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invites: list[PendingInviteResponse]


class AcceptedInviteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    invite_id: UUID
    tenant_id: UUID
    person_id: UUID
    role: Literal["owner", "admin", "member"]
    status: Literal["accepted"]


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


class OrganisationUsageResponse(MembersResponse):
    available_seconds: int
    balance_seconds: int
    used_seconds: int


class OrganisationBillingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    paid_seats: int
    active_members: int
    pending_invites: int
    seats_available: int


class MemberActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    person_id: UUID
    calls: int
    minutes: float
    reports_ready: int
    last_call_at: datetime | None


class ActivityCallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: UUID
    owner_person_id: UUID
    owner_name: str
    label: str | None
    created_at: datetime
    duration_seconds: int
    state: str
    has_report: bool


class ActivityCountsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    calls: int
    recorded_minutes: float
    reports_ready: int


class DailyActivityResponse(ActivityCountsResponse):
    date: date


class RepActivityResponse(ActivityCountsResponse):
    person_id: UUID
    name: str


class ActivityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    members: list[MemberActivityResponse]
    calls: list[ActivityCallResponse]
    per_day: list[DailyActivityResponse]
    per_rep: list[RepActivityResponse]


class AddMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: str
    role: Literal["admin", "member"]


class ChangeRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["admin", "member"]


class TransferOwnerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    # A JSON body carries the identifier as a string.
    person_id: UUID = Field(strict=False)


class OwnerTransferResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    owner: MemberResponse
    former_owner: MemberResponse


def install_organisation_http(
    application: FastAPI, *, settings: Settings, require_actor: RequireActor
) -> None:
    router = APIRouter(prefix="/v1/organisation", tags=["organisation"])

    def no_organisation(request: Request) -> ResourceNotFound:
        suffix = (
            ""
            if request.url.path in {"/v1/organisation/profile", "/v1/organisation/handle"}
            else "."
        )
        return ResourceNotFound("No organisation selected" + suffix)

    async def organisation_actor(request: Request) -> AsyncIterator[AuthenticatedTransaction]:
        try:
            resolver = require_actor.read_only if request.method == "GET" else require_actor  # type: ignore[attr-defined]
            async with asynccontextmanager(resolver)(request) as auth:
                yield auth
        except TenantScopeDeniedError as error:
            raise no_organisation(request) from error

    actor_dependency = Depends(organisation_actor, scope="function")

    async def selected(
        request: Request, response: Response, auth: AuthenticatedTransaction = actor_dependency
    ) -> AuthenticatedTransaction:
        tenant_id = auth.resolved.actor.tenant_id
        # Canonical authentication holds the active tenant and membership fences.
        if (
            tenant_id in {None, settings.public_learner_tenant_id, settings.operations_tenant_id}
            or auth.resolved.membership_role not in {"owner", "admin", "member"}
            or await auth.database.get(Organisation, tenant_id) is None
        ):
            raise no_organisation(request)
        response.headers["cache-control"] = "private, no-store"
        response.headers["vary"] = "Cookie"
        return auth

    selected_dependency = Depends(selected, scope="function")

    def command_id(value: Annotated[str, Header(alias="Idempotency-Key")]) -> UUID:
        try:
            parsed = UUID(value.strip())
        except ValueError as error:
            raise DomainError("Idempotency-Key must be a canonical UUIDv4.") from error
        if parsed.version != 4 or str(parsed) != value.strip().lower():
            raise DomainError("Idempotency-Key must be a canonical UUIDv4.")
        return parsed

    command_dependency = Depends(command_id)
    person_dependency = Depends(require_actor, scope="function")
    person_read_dependency = Depends(require_actor.read_only, scope="function")  # type: ignore[attr-defined]

    @router.get("/invites", response_model=PendingInvitesResponse)
    async def pending_invites(
        response: Response, auth: AuthenticatedTransaction = person_read_dependency
    ) -> PendingInvitesResponse:
        person = await auth.database.get(Person, auth.resolved.actor.person_id)
        assert person is not None and person.email is not None
        rows = list(
            await auth.database.execute(
                select(OrganisationInvite, Tenant)
                .join(Tenant, Tenant.id == OrganisationInvite.tenant_id)
                .join(Organisation, Organisation.tenant_id == Tenant.id)
                .where(
                    func.lower(OrganisationInvite.email_normalized)
                    == normalize_email(person.email).lower(),
                    OrganisationInvite.status == "pending",
                    Tenant.status == "active",
                    Tenant.id.not_in(
                        [
                            value
                            for value in (
                                settings.operations_tenant_id,
                                settings.public_learner_tenant_id,
                            )
                            if value is not None
                        ]
                    ),
                )
                .order_by(OrganisationInvite.created_at, OrganisationInvite.id)
            )
        )
        policies = await invitation_policies(auth.database, [invite for invite, _ in rows])
        response.headers["cache-control"] = "private, no-store"
        response.headers["vary"] = "Cookie"
        return PendingInvitesResponse(
            invites=[
                PendingInviteResponse(
                    invite_id=invite.id,
                    tenant_id=invite.tenant_id,
                    organisation_name=tenant.name,
                    role=cast(Literal["admin", "member"], invite.role),
                    invited_at=invite.created_at,
                    expires_at=policies[invite.id].expires_at,
                )
                for invite, tenant in rows
                if not policies[invite.id].expired(datetime.now(UTC))
            ]
        )

    @router.post("/invites/{invite_id}/accept", response_model=AcceptedInviteResponse)
    async def accept_invite(
        invite_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = person_dependency,
        key: UUID = command_dependency,
    ) -> AcceptedInviteResponse:
        require_safe_origin(request, settings)
        result = await service(auth).accept_invite(
            invite_id, key, actor_person_id=auth.resolved.actor.person_id
        )
        response.headers["cache-control"] = "private, no-store"
        response.headers["vary"] = "Cookie"
        return AcceptedInviteResponse.model_validate_json(json.dumps(result))

    @router.post("", response_model=OrganisationProfileResponse, status_code=201)
    async def create(
        request: Request,
        response: Response,
        body: CreateOrganisationRequest,
        auth: AuthenticatedTransaction = person_dependency,
        key: UUID = command_dependency,
    ) -> OrganisationProfileResponse:
        require_safe_origin(request, settings)
        actor = auth.resolved.actor
        result = await service(auth).create(
            body.name,
            actor.person_id,
            key,
            "self-serve-organisation:AUT-1694",
            actor_person_id=actor.person_id,
        )
        response.headers["cache-control"] = "private, no-store"
        response.headers["vary"] = "Cookie"
        return OrganisationProfileResponse(
            tenant_id=result.tenant_id,
            handle=result.slug,
            name=result.name,
            your_role=cast(Literal["owner", "admin", "member"], result.owner_role),
        )

    @router.get("/profile", response_model=OrganisationProfileResponse)
    async def profile(
        auth: AuthenticatedTransaction = selected_dependency,
    ) -> OrganisationProfileResponse:
        tenant = await auth.database.get(Tenant, auth.resolved.actor.tenant_id)
        assert tenant is not None
        return OrganisationProfileResponse(
            tenant_id=tenant.id,
            handle=tenant.slug,
            name=tenant.name,
            your_role=cast(Literal["owner", "admin", "member"], auth.resolved.membership_role),
        )

    @router.put("/handle", response_model=OrganisationProfileResponse)
    async def handle(
        body: ChangeHandleRequest,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> OrganisationProfileResponse:
        assert auth.resolved.actor.tenant_id is not None
        result = await service(auth).change_handle(
            auth.resolved.actor.tenant_id,
            body.handle,
            key,
            actor_person_id=auth.resolved.actor.person_id,
        )
        return OrganisationProfileResponse.model_validate_json(json.dumps(result))

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
                Membership.role != "processing",
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

    @router.get("/activity", response_model=ActivityResponse)
    async def activity(
        days: Annotated[int, Query(ge=1, le=90)] = 30,
        auth: AuthenticatedTransaction = selected_dependency,
    ) -> ActivityResponse:
        rows = await organisation_activity(
            auth.database,
            auth.resolved.actor,
            days=days,
            every_member=auth.resolved.membership_role != "member",
        )
        return ActivityResponse.model_validate_json(json.dumps(rows))

    @router.get("/usage", response_model=OrganisationUsageResponse)
    async def usage(
        auth: AuthenticatedTransaction = selected_dependency,
    ) -> OrganisationUsageResponse:
        actor = auth.resolved.actor
        assert actor.tenant_id is not None
        rows = dict(
            await organisation_pool(auth.database, actor.tenant_id),
            members=await member_rows(
                auth.database,
                actor.tenant_id,
                actor.person_id if auth.resolved.membership_role == "member" else None,
            ),
        )
        return OrganisationUsageResponse.model_validate_json(json.dumps(rows))

    @router.get("/billing", response_model=OrganisationBillingResponse)
    async def billing(
        auth: AuthenticatedTransaction = selected_dependency,
    ) -> OrganisationBillingResponse:
        if auth.resolved.membership_role != "owner":
            raise AuthorizationDenied("Only the organisation owner can view paid seats.")
        assert auth.resolved.actor.tenant_id is not None
        return OrganisationBillingResponse(
            **await organisation_seats(auth.database, auth.resolved.actor.tenant_id)
        )

    def service(auth: AuthenticatedTransaction) -> OrganisationService:
        if settings.operations_tenant_id is None or settings.public_learner_tenant_id is None:
            raise DomainError("Organisation tenant boundaries are not configured.")
        return OrganisationService(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            public_learner_tenant_id=settings.public_learner_tenant_id,
            seat_exempt=lambda tenant_id: seat_exempt(
                tenant_id,
                policy=getattr(application.state, "internal_tester_policy", None),
                environment=settings.environment,
            ),
        )

    @router.post("/members", response_model=MemberResponse)
    async def add(
        request: Request,
        body: AddMemberRequest,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> MemberResponse:
        require_safe_origin(request, settings)
        assert auth.resolved.actor.tenant_id is not None
        result = await service(auth).request_member(
            auth.resolved.actor.tenant_id,
            body.email,
            body.role,
            key,
            actor_person_id=auth.resolved.actor.person_id,
            require_acceptance=True,
        )
        return MemberResponse.model_validate_json(json.dumps(result))

    @router.delete("/invites/{invite_id}", status_code=204)
    async def revoke(
        request: Request,
        invite_id: UUID,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> None:
        require_safe_origin(request, settings)
        assert auth.resolved.actor.tenant_id is not None
        await service(auth).revoke_invite(
            auth.resolved.actor.tenant_id,
            invite_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
        )

    @router.patch("/members/{person_id}", response_model=MemberResponse)
    async def change_role(
        person_id: UUID,
        body: ChangeRoleRequest,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> MemberResponse:
        assert auth.resolved.actor.tenant_id is not None
        result = await service(auth).change_member_role(
            auth.resolved.actor.tenant_id,
            person_id,
            body.role,
            key,
            actor_person_id=auth.resolved.actor.person_id,
        )
        return MemberResponse.model_validate_json(json.dumps(result))

    @router.delete("/members/{person_id}", status_code=204)
    async def remove(
        person_id: UUID,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> None:
        assert auth.resolved.actor.tenant_id is not None
        await service(auth).remove_member(
            auth.resolved.actor.tenant_id,
            person_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
        )

    @router.post("/owner", response_model=OwnerTransferResponse)
    async def transfer_owner(
        body: TransferOwnerRequest,
        auth: AuthenticatedTransaction = selected_dependency,
        key: UUID = command_dependency,
    ) -> OwnerTransferResponse:
        assert auth.resolved.actor.tenant_id is not None
        result = await service(auth).transfer_ownership(
            auth.resolved.actor.tenant_id,
            body.person_id,
            key,
            actor_person_id=auth.resolved.actor.person_id,
        )
        return OwnerTransferResponse.model_validate_json(json.dumps(result))

    install_organisation_settings_routes(
        router,
        application,
        settings=settings,
        actor_dependency=actor_dependency,
        selected_dependency=selected_dependency,
        command_dependency=command_dependency,
    )
    application.include_router(router)
