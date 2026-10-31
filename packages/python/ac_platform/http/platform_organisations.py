"""Platform-operator member management for any registered organisation."""

import json
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ac_platform.application.settings import Settings
from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.authorization.platform import platform_projection
from ac_platform.authorization.policy import CapabilityDenied
from ac_platform.billing.models import BillingAccount
from ac_platform.conversation_intelligence.models import ConversationRecording
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    RequireActor,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.organisation import (
    MemberResponse,
    MembersResponse,
    OrganisationBillingResponse,
    OwnerTransferResponse,
)
from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    ResourceConflict,
    ResourceNotFound,
)
from ac_platform.organisations.invitations import active_pending_invites
from ac_platform.organisations.seat_grants import (
    GRANT_ACTION,
    MAX_GRANT_DAYS,
    MAX_GRANT_SEATS,
    GrantCommand,
    SeatGrantRefused,
    complimentary_seats_by_tenant,
    grant_history,
    is_seat_owner,
    last_day,
    record_grant,
    seat_day,
)
from ac_platform.organisations.service import OrganisationService
from ac_platform.organisations.usage import (
    current_plan,
    member_rows,
    organisation_seats,
    organisation_usage,
    paid_seats,
)
from ac_platform.organisations.workspace_kinds import (
    WorkspaceKind,
    classify_workspaces,
    ordered,
)
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationInvite,
    Tenant,
    TenantStatus,
)
from ac_platform.tenancy.roles import AssignableRoleName

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
    # Seats: the paid period's, the owner's live complimentary grants, and pending invites.
    plan_name: str | None
    paid_seats: int
    complimentary_seats: int
    pending_invites: int
    minutes_30d: float
    calls_30d: int


class PlatformOrganisationsResponse(_Strict):
    organisations: list[PlatformOrganisationResponse]


class PlatformWorkspaceResponse(_Strict):
    tenant_id: UUID
    # The name Admin shows; ``registered_name`` is what the registry holds.
    name: str
    registered_name: str
    kind: WorkspaceKind
    status: str
    member_count: int
    call_count: int


class PlatformWorkspacesResponse(_Strict):
    workspaces: list[PlatformWorkspaceResponse]


class AdminWorkspaceResponse(_Strict):
    tenant_id: UUID
    # The name Admin shows ("AC Operations" for the staff workspace).
    name: str
    kind: WorkspaceKind


class AdminWorkspacesResponse(_Strict):
    person_id: UUID
    session_id: UUID
    selected_tenant_id: UUID | None
    workspaces: list[AdminWorkspaceResponse]


class ReasonRequest(_Strict):
    reason: Reason


class PlanResponse(_Strict):
    name: str
    interval: str
    seats: int
    period_end: datetime = Field(strict=False)


class SeatGrantResponse(_Strict):
    id: UUID = Field(strict=False)
    kind: str
    seats: int
    until: date | None = Field(strict=False)
    supersedes_grant_id: UUID | None = Field(strict=False)
    reason: str
    granted_by: str | None
    created_at: datetime = Field(strict=False)
    live: bool


class PlatformSeatsResponse(_Strict):
    """One organisation's seats for Admin: counts, plan, every grant and who may grant."""

    seats: OrganisationBillingResponse
    plan: PlanResponse | None
    grants: list[SeatGrantResponse]
    can_grant: bool
    # The first and last day (IST) a new grant may run until.
    earliest_until: date = Field(strict=False)
    latest_until: date = Field(strict=False)


class SeatGrantRequest(_Strict):
    seats: int = Field(ge=0, le=MAX_GRANT_SEATS)
    # The last day (IST) the seats count; omitted when ending a grant (seats 0).
    until: date | None = Field(default=None, strict=False)
    reason: str = Field(min_length=3, max_length=300)
    supersedes_grant_id: UUID | None = Field(default=None, strict=False)


class OperatorAddMemberRequest(ReasonRequest):
    email: str
    role: AssignableRoleName


class OperatorChangeRoleRequest(ReasonRequest):
    role: AssignableRoleName


class OperatorTransferOwnerRequest(ReasonRequest):
    # A JSON body carries the identifier as a string.
    person_id: UUID = Field(strict=False)


def _refusal(error: SeatGrantRefused) -> DomainError:
    """The grant's refusal as the problem the HTTP layer renders, with its status."""
    if error.status == 404:
        return ResourceNotFound(str(error))
    if error.status == 409:
        return ResourceConflict(str(error))
    return DomainError(str(error))


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
        rows = (
            await auth.database.execute(
                select(Organisation.tenant_id, Tenant.name, member_count, Organisation.created_at)
                .join(Tenant, Tenant.id == Organisation.tenant_id)
                .where(
                    Organisation.tenant_id.not_in([item for item in protected if item is not None]),
                    # A deleted organisation (owner-approved deletion) drops out of the directory.
                    Tenant.status != TenantStatus.DELETED.value,
                )
                .order_by(Organisation.created_at.desc(), Organisation.tenant_id)
            )
        ).all()
        database, now = auth.database, datetime.now(UTC)
        listed = {tenant_id for tenant_id, *_ in rows}
        # Plans and pending invites are read only for the organisations that have them.
        billed = (
            set(
                await database.scalars(
                    select(BillingAccount.tenant_id).where(BillingAccount.kind == "organisation")
                )
            )
            & listed
        )
        inviting = (
            set(
                await database.scalars(
                    select(OrganisationInvite.tenant_id)
                    .where(OrganisationInvite.status == "pending")
                    .distinct()
                )
            )
            & listed
        )
        plans = {tenant: await current_plan(database, tenant, now) for tenant in billed}
        paid = {tenant: await paid_seats(database, tenant, now) for tenant in billed}
        pending = {
            tenant: len(await active_pending_invites(database, tenant_id=tenant))
            for tenant in inviting
        }
        complimentary = await complimentary_seats_by_tenant(database, now)
        usage = await organisation_usage(database, now - timedelta(days=30))
        return PlatformOrganisationsResponse(
            organisations=[
                PlatformOrganisationResponse(
                    tenant_id=tenant_id,
                    name=name,
                    member_count=count or 0,
                    created_at=created
                    if created.tzinfo is not None
                    else created.replace(tzinfo=UTC),
                    plan_name=(plans.get(tenant_id) or {}).get("name"),
                    paid_seats=paid.get(tenant_id, 0),
                    complimentary_seats=complimentary.get(tenant_id, (0, None))[0],
                    pending_invites=pending.get(tenant_id, 0),
                    minutes_30d=round(usage.get(tenant_id, (0, 0))[0] / 60, 1),
                    calls_30d=usage.get(tenant_id, (0, 0))[1],
                )
                for tenant_id, name, count, created in rows
            ]
        )

    async def seat_view(auth: AuthenticatedTransaction, tenant_id: UUID) -> PlatformSeatsResponse:
        database, now = auth.database, datetime.now(UTC)
        today = seat_day(now)
        body: dict[str, Any] = {
            "seats": await organisation_seats(database, tenant_id),
            "plan": await current_plan(database, tenant_id, now),
            "grants": await grant_history(database, tenant_id),
            "can_grant": await is_seat_owner(database, auth.resolved.actor.person_id),
            "earliest_until": today.isoformat(),
            "latest_until": (today + timedelta(days=MAX_GRANT_DAYS)).isoformat(),
        }
        return PlatformSeatsResponse.model_validate_json(json.dumps(body))

    @router.get("/{tenant_id}/seats", response_model=PlatformSeatsResponse)
    async def seats(
        tenant_id: UUID, auth: AuthenticatedTransaction = actor_dependency
    ) -> PlatformSeatsResponse:
        await require_organisation(auth, tenant_id, READ_CAPABILITY)
        return await seat_view(auth, tenant_id)

    @router.post("/{tenant_id}/seat-grants", response_model=PlatformSeatsResponse)
    async def grant_seats(
        request: Request,
        tenant_id: UUID,
        body: SeatGrantRequest,
        auth: AuthenticatedTransaction = actor_dependency,
        key: UUID = command_dependency,
    ) -> PlatformSeatsResponse:
        """The owner gives, changes or ends complimentary seats (no payment, no billing row)."""
        require_safe_origin(request, settings)
        await require_organisation(auth, tenant_id, MANAGE_CAPABILITY)
        database, actor = auth.database, auth.resolved.actor
        if not await is_seat_owner(database, actor.person_id):
            raise AuthorizationDenied("Only the owner (Suyash) can give complimentary seats.")
        command = GrantCommand(
            seats=body.seats,
            until=body.until,
            reason=body.reason,
            supersedes_grant_id=body.supersedes_grant_id,
        )
        prior = await database.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(key)).limit(1)
        )
        if prior is not None:
            # A retried request answers with the seats as they are; another reuse is refused.
            if (
                prior.action != GRANT_ACTION
                or prior.tenant_id != tenant_id
                or prior.payload.get("intent") != command.intent()
            ):
                raise ResourceConflict("Idempotency-Key already records a different request.")
            return await seat_view(auth, tenant_id)
        before = await organisation_seats(database, tenant_id)
        try:
            grant, replaced = await record_grant(
                database,
                tenant_id=tenant_id,
                command=command,
                person_id=actor.person_id,
                now=datetime.now(UTC),
            )
        except SeatGrantRefused as error:
            raise _refusal(error) from None
        after = await organisation_seats(database, tenant_id)
        counted = ("complimentary_seats", "total_seats")
        await append_audit_event(
            database,
            tenant_id=tenant_id,
            actor_person_id=actor.person_id,
            actor_type="person",
            action=GRANT_ACTION,
            resource_type="organisation_seat_grant",
            resource_id=grant.id,
            payload={
                "intent": command.intent(),
                "replaced": None
                if replaced is None
                else {
                    "id": str(replaced.id),
                    "seats": replaced.seats,
                    "until": last_day(replaced.valid_until).isoformat(),
                },
                "before": {name: before[name] for name in counted},
                "after": {name: after[name] for name in counted},
            },
            reason=command.reason.strip(),
            request_id=str(key),
        )
        return await seat_view(auth, tenant_id)

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

    workspaces_router = APIRouter(
        prefix="/v1/platform/workspaces",
        tags=["platform-organisations"],
        dependencies=[Depends(require_surface)],
    )

    @workspaces_router.get("", response_model=PlatformWorkspacesResponse)
    async def workspaces(
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> PlatformWorkspacesResponse:
        """Every workspace with what it is: our company, customers, Personal, sandbox, staff."""
        await require_capability(auth, READ_CAPABILITY)
        kinds = await classify_workspaces(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            personal_tenant_id=settings.public_learner_tenant_id,
        )
        members: dict[UUID, int] = dict(
            (
                await auth.database.execute(
                    select(Membership.tenant_id, func.count())
                    .where(
                        Membership.role != "processing",
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                    )
                    .group_by(Membership.tenant_id)
                )
            )
            .tuples()
            .all()
        )
        calls: dict[UUID, int] = dict(
            (
                await auth.database.execute(
                    select(ConversationRecording.tenant_id, func.count())
                    .where(ConversationRecording.deleted_at.is_(None))
                    .group_by(ConversationRecording.tenant_id)
                )
            )
            .tuples()
            .all()
        )
        return PlatformWorkspacesResponse(
            workspaces=[
                PlatformWorkspaceResponse(
                    tenant_id=item.tenant_id,
                    name=item.name,
                    registered_name=item.registered_name,
                    kind=item.kind,
                    status=item.status,
                    member_count=members.get(item.tenant_id, 0),
                    call_count=calls.get(item.tenant_id, 0),
                )
                for item in ordered(kinds.values())
            ]
        )

    application.include_router(workspaces_router)

    own_router = APIRouter(
        prefix="/v1/me/admin-workspaces",
        tags=["platform-organisations"],
        dependencies=[Depends(require_surface)],
    )

    @own_router.get("", response_model=AdminWorkspacesResponse)
    async def own_workspaces(
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = actor_dependency,
    ) -> AdminWorkspacesResponse:
        """The signed-in person's own workspaces, named and kinded as Admin shows them.

        The same memberships GET /v1/me/workspaces lists, so Admin's sign-in can
        open the staff workspace and never shows two choices that read the same
        (two of them are registered as "Authority Closers"). Presentation only:
        it needs no platform grant, shows no other workspace and selects nothing.
        """
        if request.query_params:
            raise DomainError("Workspaces are resolved only for the authenticated person.")
        actor = auth.resolved.actor
        own = await auth.identity.repository.list_active_workspaces(actor.person_id)
        kinds = await classify_workspaces(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            personal_tenant_id=settings.public_learner_tenant_id,
            tenant_ids=[tenant_id for tenant_id, _ in own],
        )
        response.headers["cache-control"] = "private, no-store"
        response.headers["pragma"] = "no-cache"
        return AdminWorkspacesResponse(
            person_id=actor.person_id,
            session_id=actor.session_id,
            selected_tenant_id=actor.tenant_id,
            workspaces=[
                AdminWorkspaceResponse(tenant_id=item.tenant_id, name=item.name, kind=item.kind)
                for item in ordered(kinds.values())
            ],
        )

    application.include_router(own_router)
