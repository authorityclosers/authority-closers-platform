"""Transactional, idempotent organisation-management commands."""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.services import normalize_email
from ac_platform.kernel.errors import (
    AuthorizationDenied,
    DomainError,
    ResourceConflict,
    ResourceNotFound,
)
from ac_platform.organisations.usage import invite_row, member_rows, organisation_seats
from ac_platform.tenancy.models import (
    Membership,
    MembershipRole,
    MembershipStatus,
    Organisation,
    OrganisationDomainSetting,
    OrganisationInvite,
    Tenant,
    TenantStatus,
)

_FREE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "yahoo.com",
        "icloud.com",
        "me.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "gmx.com",
        "zoho.com",
        "yandex.com",
        "mail.com",
    }
)
_DOMAIN_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class OrganisationCommandError(DomainError, ValueError):
    """An organisation command fails closed on invalid or protected state."""


class OrganisationCommandConflict(OrganisationCommandError):
    """A command ID was reused with a different intent."""

    status = 409


class OrganisationAdditionLimit(OrganisationCommandError):
    """The organisation's daily addition budget is exhausted."""

    status = 429


class OrganisationDomainConflict(OrganisationCommandError):
    """A domain is unavailable for organisation verification."""

    status = 409


class OrganisationSeatsFull(OrganisationCommandError):
    """An addition would exceed seats from the organisation's verified paid period."""

    code = "seats_full"
    status = 409
    title = "Organisation seats are full"


@dataclass(frozen=True, slots=True)
class OrganisationResult:
    tenant_id: UUID
    organisation_id: UUID
    name: str
    slug: str
    owner_person_id: UUID
    owner_role: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class MemberResult:
    tenant_id: UUID
    person_id: UUID
    email: str | None
    role: str
    status: str
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class DomainSettingResult:
    tenant_id: UUID
    version: int
    verified_domains: tuple[str, ...]
    auto_join: bool
    proof: dict[str, dict[str, str]]
    replayed: bool = False


class OrganisationService:
    """Commands share the caller's transaction and append audit evidence there."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        operations_tenant_id: UUID,
        public_learner_tenant_id: UUID,
        seat_exempt: Callable[[UUID], bool] | None = None,
    ) -> None:
        if operations_tenant_id is None or public_learner_tenant_id is None:
            raise OrganisationCommandError(
                "operations and public tenant IDs are required to protect those tenants"
            )
        self.session = session
        self._seat_exempt = seat_exempt
        self._protected_tenant_ids = frozenset((operations_tenant_id, public_learner_tenant_id))

    async def create(
        self,
        name: str,
        owner_person_id: UUID,
        command_id: UUID,
        operator_reference: str,
        *,
        reason: str | None = None,
    ) -> OrganisationResult:
        name = name.strip()
        if not 2 <= len(name) <= 80:
            raise OrganisationCommandError("organisation name must contain 2 to 80 characters")
        operator_reference = _required_text(operator_reference, "operator reference", 160)
        prior = await self.session.scalar(
            select(Organisation).where(Organisation.creation_command_id == command_id)
        )
        if prior is not None:
            tenant = await self.session.get(Tenant, prior.tenant_id)
            owner = await self._creation_owner(prior.tenant_id, command_id)
            audit = await self._command_audit(prior.tenant_id, command_id, "organisation.created")
            expected = {
                "name": name,
                "owner_person_id": str(owner_person_id),
                "operator_reference": operator_reference,
            }
            if tenant is None or audit is None or audit.payload.get("intent") != expected:
                raise OrganisationCommandConflict(
                    "command ID already records a different create intent"
                )
            if owner is None or owner.person_id != owner_person_id:
                raise OrganisationCommandConflict(
                    "created owner no longer matches the command intent"
                )
            return OrganisationResult(
                prior.tenant_id,
                prior.tenant_id,
                tenant.name,
                tenant.slug,
                owner_person_id,
                owner.role,
                replayed=True,
            )

        await self._ensure_command_id_available(command_id, "organisation.created")

        owner_person = await self.session.get(Person, owner_person_id)
        if owner_person is None or owner_person.status != PersonStatus.ACTIVE.value:
            raise OrganisationCommandError("owner must be an active person")
        tenant_id = uuid4()
        slug = _tenant_slug(name)
        tenant = Tenant(id=tenant_id, slug=slug, name=name, status=TenantStatus.ACTIVE.value)
        organisation = Organisation(
            tenant_id=tenant_id,
            created_by_person_id=owner_person_id,
            creation_command_id=command_id,
            domain_verification_token=secrets.token_urlsafe(32),
        )
        membership = Membership(
            tenant_id=tenant_id,
            person_id=owner_person_id,
            role=MembershipRole.OWNER.value,
            status=MembershipStatus.ACTIVE.value,
        )
        self.session.add(tenant)
        await self.session.flush()
        self.session.add_all([organisation, membership])
        await self.session.flush()
        intent = {
            "name": name,
            "owner_person_id": str(owner_person_id),
            "operator_reference": operator_reference,
        }
        await self._audit(
            tenant_id,
            command_id,
            "organisation.created",
            "organisation",
            tenant_id,
            {
                "command_id": str(command_id),
                "intent": intent,
                "before": None,
                "after": {"role": "owner", "status": "active"},
            },
            reason,
        )
        return OrganisationResult(tenant_id, tenant_id, name, slug, owner_person_id, "owner")

    async def add_member(
        self,
        tenant_id: UUID,
        person_id: UUID,
        role: str,
        command_id: UUID,
        *,
        actor_person_id: UUID | None = None,
        operator_reference: str | None = None,
        reason: str | None = None,
        http_intent: dict[str, str] | None = None,
    ) -> MemberResult:
        role = _member_role(role)
        if operator_reference is not None:
            operator_reference = _required_text(operator_reference, "operator reference", 160)
        organisation = await self._organisation(tenant_id, lock=True)
        del organisation
        prior = await self.session.scalar(
            select(OrganisationInvite).where(OrganisationInvite.command_id == command_id)
        )
        if prior is not None:
            if (
                prior.tenant_id != tenant_id
                or prior.accepted_person_id != person_id
                or prior.role != role
                or prior.status != "accepted"
            ):
                raise OrganisationCommandConflict(
                    "command ID already records a different member intent"
                )
            audit = await self._command_audit(tenant_id, command_id, "organisation.member_added")
            if audit is None or audit.payload.get("intent") != {
                "person_id": str(person_id),
                "role": role,
                "operator_reference": operator_reference,
            }:
                raise OrganisationCommandConflict(
                    "command ID already records a different member intent"
                )
            person = await self.session.get(Person, person_id)
            membership = await self.session.get(Membership, (tenant_id, person_id))
            if person is None or membership is None:
                raise OrganisationCommandError("the recorded member is unavailable")
            return MemberResult(
                tenant_id, person_id, person.email, membership.role, membership.status, True
            )

        await self._ensure_command_id_available(command_id, "organisation.member_added")

        # The registry lock serializes owner changes; avoid upgrading the
        # shared owner fence held by another authenticated request here.
        owners = tuple(
            await self.session.scalars(
                select(Membership).where(
                    Membership.tenant_id == tenant_id,
                    Membership.role == MembershipRole.OWNER.value,
                    Membership.status == MembershipStatus.ACTIVE.value,
                )
            )
        )
        if len(owners) != 1:
            raise OrganisationCommandError("organisation must have exactly one active owner")

        person = await self.session.get(Person, person_id)
        if (
            person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email is None
            or person.email_verified_at is None
        ):
            raise OrganisationCommandError("member must be active and have a verified email")
        email = normalize_email(person.email)
        try:
            membership = await self.session.scalar(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
                .with_for_update(nowait=http_intent is not None)
            )
        except DBAPIError as error:
            # Another authenticated actor may hold a shared membership fence
            # while waiting for this organisation. Refuse the lock upgrade.
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise ResourceConflict(
                    "Member is busy; retry with the same Idempotency-Key."
                ) from error
            raise
        if membership is not None and membership.role == MembershipRole.OWNER.value:
            raise OrganisationCommandError("the active owner cannot be changed by add-member")
        before = (
            None if membership is None else {"role": membership.role, "status": membership.status}
        )
        pending = await self.session.scalar(
            select(OrganisationInvite)
            .where(
                OrganisationInvite.tenant_id == tenant_id,
                OrganisationInvite.email_normalized == email,
                OrganisationInvite.status == "pending",
            )
            .with_for_update()
        )
        # Audited operator provisioning does not require a paid subscription.
        if operator_reference is None and (
            membership is None or membership.status != "active" or membership.ended_at is not None
        ):
            await self._ensure_seat_available(tenant_id, extra=0 if pending is not None else 1)
        now = datetime.now(UTC)
        if membership is None:
            membership = Membership(
                tenant_id=tenant_id,
                person_id=person_id,
                role=role,
                status=MembershipStatus.ACTIVE.value,
            )
            self.session.add(membership)
        else:
            membership.role = role
            membership.status = MembershipStatus.ACTIVE.value
            membership.ended_at = None
            membership.revision += 1
        if pending is not None:
            pending.status = "accepted"
            pending.closed_at = now
            pending.accepted_person_id = person_id
        invite = OrganisationInvite(
            tenant_id=tenant_id,
            email_normalized=email,
            role=role,
            status="accepted",
            invited_by_person_id=actor_person_id,
            command_id=command_id,
            created_at=now,
            closed_at=now,
            accepted_person_id=person_id,
        )
        self.session.add(invite)
        await self.session.flush()
        http_result = None
        if http_intent is not None:
            http_result = (await member_rows(self.session, tenant_id, person_id))[0]
            if before is not None and before["status"] == "inactive":
                http_result["joined_at"] = now.isoformat()
        await self._audit(
            tenant_id,
            command_id,
            "organisation.member_added",
            "organisation_membership",
            person_id,
            {
                "command_id": str(command_id),
                "intent": {
                    "person_id": str(person_id),
                    "role": role,
                    "operator_reference": operator_reference,
                },
                "before": before,
                "after": {"role": role, "status": "active"},
                **(
                    {"http_intent": http_intent, "result": http_result}
                    if http_intent is not None
                    else {}
                ),
            },
            reason,
            actor_person_id=actor_person_id,
        )
        return MemberResult(tenant_id, person_id, person.email, role, "active")

    async def _ensure_seat_available(self, tenant_id: UUID, *, extra: int = 1) -> None:
        if self._seat_exempt is not None and self._seat_exempt(tenant_id):
            return
        # Every addition holds the registry lock, so competing commands cannot
        # both consume the last seat. Accepting an invite replaces its seat.
        seats = await organisation_seats(self.session, tenant_id)
        if seats["active_members"] + seats["pending_invites"] + extra > seats["paid_seats"]:
            raise OrganisationSeatsFull(
                "All paid seats are occupied by members or pending invites."
            )

    async def _actor(
        self, tenant_id: UUID, actor_person_id: UUID, *, lock: bool = True
    ) -> Membership:
        await self._organisation(tenant_id, lock=lock)
        actor = await self.session.scalar(
            select(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.person_id == actor_person_id)
            .execution_options(populate_existing=True)
        )
        if actor is None or actor.status != "active" or actor.ended_at is not None:
            raise ResourceNotFound("No organisation selected.")
        return actor

    async def _acting(
        self,
        tenant_id: UUID,
        actor_person_id: UUID,
        operator_reference: str | None,
        intent: dict[str, str],
    ) -> str:
        """Return the member's role, or ``operator`` for a platform operator.

        The HTTP boundary has already proved the operator's platform capability;
        an operator needs no membership and acts on any role. The reference is
        part of the intent, so a member can never replay an operator's command.
        """
        if operator_reference is None:
            return (await self._actor(tenant_id, actor_person_id)).role
        intent["operator_reference"] = _required_text(operator_reference, "reason", 200)
        await self._organisation(tenant_id, lock=True)
        return "operator"

    async def _replay(
        self, tenant_id: UUID, command_id: UUID, intent: dict[str, str]
    ) -> AuditEvent | None:
        prior = cast(
            AuditEvent | None,
            await self.session.scalar(
                select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
            ),
        )
        if prior is not None and (
            prior.tenant_id != tenant_id or prior.payload.get("http_intent") != intent
        ):
            raise OrganisationCommandConflict(
                "Idempotency-Key already records a different request."
            )
        return prior

    async def _lock_members(self, tenant_id: UUID, *person_ids: UUID) -> dict[UUID, Membership]:
        # The registry lock is already held. A waiting authenticated request may
        # hold a shared fence on these rows, so refuse the lock upgrade instead
        # of waiting into a cycle; one statement locks them in one order.
        try:
            rows = await self.session.scalars(
                select(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.person_id.in_(person_ids))
                .order_by(Membership.person_id)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) == "55P03":
                raise ResourceConflict(
                    "Member is busy; retry with the same Idempotency-Key."
                ) from error
            raise
        return {
            row.person_id: row
            for row in rows
            if row.status == "active"
            and row.ended_at is None
            and row.role in {"owner", "admin", "member"}
        }

    async def change_member_role(
        self,
        tenant_id: UUID,
        person_id: UUID,
        role: str,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        operator_reference: str | None = None,
    ) -> dict[str, object]:
        role = _member_role(role)
        intent = {
            "action": "change_role",
            "person_id": str(person_id),
            "role": role,
            "actor_person_id": str(actor_person_id),
        }
        acting = await self._acting(tenant_id, actor_person_id, operator_reference, intent)
        prior = await self._replay(tenant_id, command_id, intent)
        if prior is not None:
            return cast(dict[str, object], prior.payload["result"])
        if acting not in {"owner", "operator"}:
            raise AuthorizationDenied("Only the owner can change a role.")
        if acting == "owner" and person_id == actor_person_id:
            raise ResourceConflict("Transfer ownership first.")
        target = (await self._lock_members(tenant_id, person_id)).get(person_id)
        if target is None:
            raise ResourceNotFound("Member not found.")
        if target.role == "owner":
            raise ResourceConflict("Transfer ownership first.")
        before = {"role": target.role, "status": "active"}
        target.role = role
        target.revision += 1
        await self.session.flush()
        result = (await member_rows(self.session, tenant_id, person_id))[0]
        await self._audit(
            tenant_id,
            command_id,
            "organisation.member_role_changed",
            "organisation_membership",
            person_id,
            {
                "http_intent": intent,
                "result": result,
                "before": before,
                "after": {"role": role, "status": "active"},
            },
            operator_reference,
            actor_person_id=actor_person_id,
        )
        return result

    async def remove_member(
        self,
        tenant_id: UUID,
        person_id: UUID,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        operator_reference: str | None = None,
    ) -> None:
        intent = {
            "action": "remove",
            "person_id": str(person_id),
            "actor_person_id": str(actor_person_id),
        }
        acting = await self._acting(tenant_id, actor_person_id, operator_reference, intent)
        if await self._replay(tenant_id, command_id, intent) is not None:
            return
        if acting == "operator":
            pass
        elif person_id == actor_person_id:
            if acting == "owner":
                raise ResourceConflict("Transfer ownership first.")
        elif acting not in {"owner", "admin"}:
            raise AuthorizationDenied("Organisation administration is required.")
        target = (await self._lock_members(tenant_id, person_id)).get(person_id)
        if target is None:
            raise ResourceNotFound("Member not found.")
        if target.role == "owner":
            raise ResourceConflict("Transfer ownership first.")
        if acting == "admin" and person_id != actor_person_id and target.role != "member":
            raise AuthorizationDenied("An admin can remove members only.")
        before = {"role": target.role, "status": "active"}
        # The membership row and its history stay; only its state ends.
        target.status = MembershipStatus.INACTIVE.value
        target.ended_at = datetime.now(UTC)
        target.revision += 1
        await self.session.flush()
        await self._audit(
            tenant_id,
            command_id,
            "organisation.member_removed",
            "organisation_membership",
            person_id,
            {
                "http_intent": intent,
                "result": None,
                "before": before,
                "after": {"role": target.role, "status": "inactive"},
            },
            operator_reference,
            actor_person_id=actor_person_id,
        )

    async def transfer_ownership(
        self,
        tenant_id: UUID,
        person_id: UUID,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        operator_reference: str | None = None,
    ) -> dict[str, object]:
        intent = {
            "action": "transfer_ownership",
            "person_id": str(person_id),
            "actor_person_id": str(actor_person_id),
        }
        acting = await self._acting(tenant_id, actor_person_id, operator_reference, intent)
        prior = await self._replay(tenant_id, command_id, intent)
        if prior is not None:
            return cast(dict[str, object], prior.payload["result"])
        owner_id = actor_person_id
        if acting == "operator":
            # The operator is not the owner; the single-owner check below
            # still refuses an organisation with more than one.
            current = await self.session.scalar(
                select(Membership.person_id)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.role == MembershipRole.OWNER.value,
                    Membership.status == MembershipStatus.ACTIVE.value,
                )
                .limit(1)
            )
            if current is None:
                raise OrganisationCommandError("organisation must have exactly one active owner")
            owner_id = current
        elif acting != "owner":
            raise AuthorizationDenied("Only the owner can transfer ownership.")
        if person_id == owner_id:
            raise ResourceConflict("This person is already the owner.")
        locked = await self._lock_members(tenant_id, owner_id, person_id)
        owner, target = locked.get(owner_id), locked.get(person_id)
        owners = await self.session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.role == MembershipRole.OWNER.value,
                Membership.status == MembershipStatus.ACTIVE.value,
            )
        )
        if owner is None or owner.role != "owner" or owners != 1:
            raise OrganisationCommandError("organisation must have exactly one active owner")
        person = await self.session.get(Person, person_id)
        if (
            target is None
            or person is None
            or person.status != PersonStatus.ACTIVE.value
            or person.email_verified_at is None
        ):
            raise ResourceNotFound("Member not found.")
        before = {"owner_person_id": str(owner_id), "target_role": target.role}
        owner.role = MembershipRole.ADMIN.value
        target.role = MembershipRole.OWNER.value
        owner.revision += 1
        target.revision += 1
        await self.session.flush()
        result: dict[str, object] = {
            "owner": (await member_rows(self.session, tenant_id, person_id))[0],
            "former_owner": (await member_rows(self.session, tenant_id, owner_id))[0],
        }
        await self._audit(
            tenant_id,
            command_id,
            "organisation.ownership_transferred",
            "organisation_membership",
            person_id,
            {
                "http_intent": intent,
                "result": result,
                "before": before,
                "after": {
                    "owner_person_id": str(person_id),
                    "former_owner_person_id": str(owner_id),
                    "former_owner_role": "admin",
                },
            },
            operator_reference,
            actor_person_id=actor_person_id,
        )
        return result

    async def request_member(
        self,
        tenant_id: UUID,
        email: str,
        role: str,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        operator_reference: str | None = None,
    ) -> dict[str, object]:
        role = _member_role(role)
        intent = {"email": "", "role": role, "actor_person_id": str(actor_person_id)}
        acting = await self._acting(tenant_id, actor_person_id, operator_reference, intent)
        if acting not in {"owner", "admin", "operator"}:
            raise AuthorizationDenied("Organisation administration is required.")
        if acting == "admin" and role != "member":
            raise AuthorizationDenied("Only the owner can add an admin.")
        try:
            email = normalize_email(email)
        except ValueError as error:
            raise OrganisationCommandError("A valid email is required.") from error
        intent["email"] = email
        prior = await self._replay(tenant_id, command_id, intent)
        if prior is not None:
            return cast(dict[str, object], prior.payload["result"])
        now = datetime.now(UTC)
        additions = await self.session.scalar(
            select(func.count())
            .select_from(OrganisationInvite)
            .where(
                OrganisationInvite.tenant_id == tenant_id,
                OrganisationInvite.created_at
                >= now.replace(hour=0, minute=0, second=0, microsecond=0),
            )
        )
        if (additions or 0) >= 50:
            raise OrganisationAdditionLimit(
                "Limit of 50 member additions per organisation per day reached."
            )
        person = await self.session.scalar(
            select(Person).where(func.lower(Person.email) == email.lower())
        )
        if person is not None:
            target = await self.session.get(Membership, (tenant_id, person.id))
            if acting == "admin" and target is not None and target.role != "member":
                raise AuthorizationDenied("An admin can add members only.")
            await self.add_member(
                tenant_id,
                person.id,
                role,
                command_id,
                actor_person_id=actor_person_id,
                operator_reference=operator_reference,
                reason=operator_reference,
                http_intent=intent,
            )
            audit = await self._command_audit(tenant_id, command_id, "organisation.member_added")
            assert audit is not None
            return cast(dict[str, object], audit.payload["result"])
        pending = await self.session.scalar(
            select(OrganisationInvite).where(
                OrganisationInvite.tenant_id == tenant_id,
                OrganisationInvite.email_normalized == email,
                OrganisationInvite.status == "pending",
            )
        )
        if pending is not None:
            raise ResourceConflict("A pending invite already exists for this email.")
        if acting != "operator":
            await self._ensure_seat_available(tenant_id)
        invite = OrganisationInvite(
            tenant_id=tenant_id,
            email_normalized=email,
            role=role,
            command_id=command_id,
            invited_by_person_id=actor_person_id,
        )
        self.session.add(invite)
        await self.session.flush()
        result = invite_row(invite)
        await self._audit(
            tenant_id,
            command_id,
            "organisation.member_invited",
            "organisation_invite",
            invite.id,
            {
                "http_intent": intent,
                "result": result,
                "before": None,
                "after": {"status": "pending"},
            },
            operator_reference,
            actor_person_id=actor_person_id,
        )
        return result

    async def revoke_invite(
        self,
        tenant_id: UUID,
        invite_id: UUID,
        command_id: UUID,
        *,
        actor_person_id: UUID,
        operator_reference: str | None = None,
    ) -> None:
        acting = await self._acting(tenant_id, actor_person_id, operator_reference, {})
        if acting not in {"owner", "admin", "operator"}:
            raise AuthorizationDenied("Organisation administration is required.")
        prior = await self._command_audit(tenant_id, command_id, "organisation.invite_revoked")
        if prior is not None:
            if (
                prior.resource_id != str(invite_id)
                or prior.actor_person_id != actor_person_id
                or prior.reason != operator_reference
            ):
                raise OrganisationCommandConflict(
                    "Idempotency-Key already records a different request."
                )
            return
        await self._ensure_command_id_available(command_id, "organisation.invite_revoked")
        invite = await self.session.get(OrganisationInvite, invite_id)
        if invite is None or invite.tenant_id != tenant_id or invite.status != "pending":
            raise ResourceNotFound("Pending invite not found.")
        invite.status, invite.closed_at = "revoked", datetime.now(UTC)
        await self._audit(
            tenant_id,
            command_id,
            "organisation.invite_revoked",
            "organisation_invite",
            invite_id,
            {"before": {"status": "pending"}, "after": {"status": "revoked"}},
            operator_reference,
            actor_person_id=actor_person_id,
        )

    async def list_members(self, tenant_id: UUID) -> tuple[MemberResult, ...]:
        await self._organisation(tenant_id)
        rows = await self.session.execute(
            select(Membership, Person)
            .join(Person, Person.id == Membership.person_id)
            .where(Membership.tenant_id == tenant_id)
            .order_by(Person.email, Person.id)
        )
        return tuple(
            MemberResult(
                tenant_id, membership.person_id, person.email, membership.role, membership.status
            )
            for membership, person in rows
        )

    async def set_domains_attested(
        self,
        tenant_id: UUID,
        domains: list[str] | tuple[str, ...],
        auto_join: bool,
        operator_reference: str,
        command_id: UUID,
        *,
        actor_person_id: UUID | None = None,
        reason: str | None = None,
        verify_domain: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> DomainSettingResult:
        operator_reference = _required_text(operator_reference, "operator reference", 160)
        normalized = tuple(sorted({_normalize_domain(domain) for domain in domains}))
        if type(auto_join) is not bool:
            raise OrganisationCommandError("auto_join must be a boolean")
        preverified: set[str] = set()
        if verify_domain is not None:
            actor = await self._actor(tenant_id, cast(UUID, actor_person_id), lock=False)
            if actor.role != MembershipRole.OWNER.value:
                raise AuthorizationDenied("Only the owner can set domains.")
            prior = await self.session.scalar(
                select(OrganisationDomainSetting).where(
                    OrganisationDomainSetting.command_id == command_id
                )
            )
            if prior is None:
                latest = await self._latest_domain_settings(tenant_id)
                before = set() if latest is None else set(latest.verified_domains)
                for org in await self.session.scalars(select(Organisation)):
                    if org.tenant_id != tenant_id:
                        other = await self._latest_domain_settings(org.tenant_id)
                        if other is not None and set(normalized).intersection(
                            other.verified_domains
                        ):
                            raise OrganisationDomainConflict(
                                "a domain is already verified by another organisation"
                            )
                organisation = await self._organisation(tenant_id)
                # No registry locks are held across external DNS requests.
                for domain in sorted(set(normalized) - before):
                    await verify_domain(domain, organisation.domain_verification_token)
                    preverified.add(domain)
        # Lock every registry row in one order so two domain changes cannot
        # concurrently claim the same JSON-backed domain.
        organisations = tuple(
            await self.session.scalars(
                select(Organisation).order_by(Organisation.tenant_id).with_for_update()
            )
        )
        if verify_domain is not None:
            # Product proof cannot use the operator bypass, including on replay.
            actor = await self._actor(tenant_id, cast(UUID, actor_person_id))
            if actor.role != MembershipRole.OWNER.value:
                raise AuthorizationDenied("Only the owner can set domains.")
        if tenant_id in self._protected_tenant_ids or tenant_id not in {
            row.tenant_id for row in organisations
        }:
            raise OrganisationCommandError("tenant is not an organisation or is protected")
        prior = await self.session.scalar(
            select(OrganisationDomainSetting).where(
                OrganisationDomainSetting.command_id == command_id
            )
        )
        if prior is not None:
            expected = (
                tuple(prior.verified_domains) == normalized
                and prior.auto_join is auto_join
                and prior.operator_reference == operator_reference
            )
            if prior.tenant_id != tenant_id or not expected:
                raise OrganisationCommandConflict(
                    "command ID already records a different domain intent"
                )
            audit = await self._command_audit(tenant_id, command_id, "organisation.domains_set")
            if audit is None or audit.payload.get("intent") != {
                "verified_domains": list(normalized),
                "auto_join": auto_join,
                "operator_reference": operator_reference,
            }:
                raise OrganisationCommandConflict(
                    "command ID already records a different domain intent"
                )
            return _domain_result(prior, replayed=True)

        await self._ensure_command_id_available(command_id, "organisation.domains_set")

        latest = await self._latest_domain_settings(tenant_id)
        before_domains = [] if latest is None else list(latest.verified_domains)
        for org in organisations:
            if org.tenant_id == tenant_id:
                continue
            other = await self._latest_domain_settings(org.tenant_id)
            if other is not None and set(normalized).intersection(other.verified_domains):
                raise OrganisationDomainConflict(
                    "a domain is already verified by another organisation"
                )
        newly_added = set(normalized) - set(before_domains)
        if verify_domain is not None and not newly_added.issubset(preverified):
            raise OrganisationDomainConflict("domains changed, retry")
        checked_at = datetime.now(UTC).isoformat()
        proof = {
            domain: {
                "method": "operator_attested" if verify_domain is None else "dns_txt",
                "checked_at": checked_at,
            }
            for domain in sorted(newly_added)
        }
        version = 1 if latest is None else latest.version + 1
        row = OrganisationDomainSetting(
            tenant_id=tenant_id,
            version=version,
            verified_domains=list(normalized),
            auto_join=auto_join,
            proof=proof,
            actor_person_id=actor_person_id,
            operator_reference=operator_reference,
            command_id=command_id,
        )
        self.session.add(row)
        await self.session.flush()
        await self._audit(
            tenant_id,
            command_id,
            "organisation.domains_set",
            "organisation_domain_settings",
            row.id,
            {
                "command_id": str(command_id),
                "intent": {
                    "verified_domains": list(normalized),
                    "auto_join": auto_join,
                    "operator_reference": operator_reference,
                },
                "before": {
                    "domains": before_domains,
                    "auto_join": None if latest is None else latest.auto_join,
                },
                "after": {"domains": list(normalized), "auto_join": auto_join},
            },
            reason,
            actor_person_id=actor_person_id,
        )
        return _domain_result(row)

    async def _organisation(self, tenant_id: UUID, *, lock: bool = False) -> Organisation:
        if tenant_id in self._protected_tenant_ids:
            raise OrganisationCommandError(
                "operations and public tenants cannot be managed as organisations"
            )
        statement = select(Organisation).where(Organisation.tenant_id == tenant_id)
        if lock:
            statement = statement.with_for_update()
        row = await self.session.scalar(statement)
        if row is None:
            raise OrganisationCommandError("tenant is not a registered organisation")
        return row

    async def _latest_domain_settings(self, tenant_id: UUID) -> OrganisationDomainSetting | None:
        return cast(
            OrganisationDomainSetting | None,
            await self.session.scalar(
                select(OrganisationDomainSetting)
                .where(OrganisationDomainSetting.tenant_id == tenant_id)
                .order_by(OrganisationDomainSetting.version.desc())
                .limit(1)
            ),
        )

    async def _creation_owner(self, tenant_id: UUID, command_id: UUID) -> Membership | None:
        audit = await self._command_audit(tenant_id, command_id, "organisation.created")
        if audit is None:
            return None
        owner_id = audit.payload.get("intent", {}).get("owner_person_id")
        if not owner_id:
            return None
        try:
            person_id = UUID(owner_id)
        except (ValueError, TypeError):
            return None
        return await self.session.get(Membership, (tenant_id, person_id))

    async def _command_audit(
        self, tenant_id: UUID, command_id: UUID, action: str
    ) -> AuditEvent | None:
        conflicting_audit = await self.session.scalar(
            select(AuditEvent).where(
                AuditEvent.request_id == str(command_id),
                or_(AuditEvent.tenant_id != tenant_id, AuditEvent.action != action),
            )
        )
        if conflicting_audit is not None:
            return None
        return cast(
            AuditEvent | None,
            await self.session.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.request_id == str(command_id),
                    AuditEvent.action == action,
                )
            ),
        )

    async def _ensure_command_id_available(self, command_id: UUID, action: str) -> None:
        prior = await self.session.scalar(
            select(AuditEvent).where(AuditEvent.request_id == str(command_id)).limit(1)
        )
        if prior is not None:
            raise OrganisationCommandConflict(
                f"command ID already records a command and cannot be used for {action}"
            )

    async def _audit(
        self,
        tenant_id: UUID,
        command_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        payload: dict[str, object],
        reason: str | None,
        *,
        actor_person_id: UUID | None = None,
    ) -> None:
        await append_audit_event(
            self.session,
            tenant_id=tenant_id,
            actor_person_id=actor_person_id,
            actor_type="person" if actor_person_id else "operator",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload,
            reason=reason,
            request_id=str(command_id),
        )


def _domain_result(
    row: OrganisationDomainSetting, *, replayed: bool = False
) -> DomainSettingResult:
    return DomainSettingResult(
        row.tenant_id,
        row.version,
        tuple(row.verified_domains),
        row.auto_join,
        dict(row.proof),
        replayed,
    )


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise OrganisationCommandError(f"{field} must contain 1 to {maximum} printable characters")
    return normalized


def _member_role(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {MembershipRole.ADMIN.value, MembershipRole.MEMBER.value}:
        raise OrganisationCommandError("member role must be admin or member")
    return normalized


def _normalize_domain(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrganisationCommandError("domain is required")
    try:
        domain = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise OrganisationCommandError("domain is invalid") from exc
    labels = domain.split(".")
    if (
        len(domain) > 253
        or len(labels) < 2
        or any(not _DOMAIN_LABEL.fullmatch(label) for label in labels)
    ):
        raise OrganisationCommandError("domain is invalid")
    if any(domain == free or domain.endswith(f".{free}") for free in _FREE_EMAIL_DOMAINS):
        raise OrganisationDomainConflict("freemail domains cannot be verified")
    return domain


def _tenant_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:50].strip("-") or "organisation"
    return f"{stem}-{secrets.token_hex(2)}"
