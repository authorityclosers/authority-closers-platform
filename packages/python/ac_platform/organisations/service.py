"""Transactional, idempotent organisation-management commands."""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import append_audit_event
from ac_platform.identity.models import Person, PersonStatus
from ac_platform.identity.services import normalize_email
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


class OrganisationCommandError(ValueError):
    """An organisation command fails closed on invalid or protected state."""


class OrganisationCommandConflict(OrganisationCommandError):
    """A command ID was reused with a different intent."""


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
    ) -> None:
        if operations_tenant_id is None or public_learner_tenant_id is None:
            raise OrganisationCommandError(
                "operations and public tenant IDs are required to protect those tenants"
            )
        self.session = session
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

        owners = tuple(
            await self.session.scalars(
                select(Membership)
                .where(
                    Membership.tenant_id == tenant_id,
                    Membership.role == MembershipRole.OWNER.value,
                    Membership.status == MembershipStatus.ACTIVE.value,
                )
                .with_for_update()
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
        membership = await self.session.scalar(
            select(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.person_id == person_id)
            .with_for_update()
        )
        if membership is not None and membership.role == MembershipRole.OWNER.value:
            raise OrganisationCommandError("the active owner cannot be changed by add-member")
        before = (
            None if membership is None else {"role": membership.role, "status": membership.status}
        )
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
        pending = await self.session.scalar(
            select(OrganisationInvite)
            .where(
                OrganisationInvite.tenant_id == tenant_id,
                OrganisationInvite.email_normalized == email,
                OrganisationInvite.status == "pending",
            )
            .with_for_update()
        )
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
            },
            reason,
            actor_person_id=actor_person_id,
        )
        return MemberResult(tenant_id, person_id, person.email, role, "active")

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
    ) -> DomainSettingResult:
        operator_reference = _required_text(operator_reference, "operator reference", 160)
        normalized = tuple(sorted({_normalize_domain(domain) for domain in domains}))
        if type(auto_join) is not bool:
            raise OrganisationCommandError("auto_join must be a boolean")
        # Lock every registry row in one order so two domain changes cannot
        # concurrently claim the same JSON-backed domain.
        organisations = tuple(
            await self.session.scalars(
                select(Organisation).order_by(Organisation.tenant_id).with_for_update()
            )
        )
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
                raise OrganisationCommandError(
                    "a domain is already verified by another organisation"
                )
        newly_added = set(normalized) - set(before_domains)
        checked_at = datetime.now(UTC).isoformat()
        proof = {
            domain: {"method": "operator_attested", "checked_at": checked_at}
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
        raise OrganisationCommandError("freemail domains cannot be verified")
    return domain


def _tenant_slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:50].strip("-") or "organisation"
    return f"{stem}-{secrets.token_hex(2)}"
