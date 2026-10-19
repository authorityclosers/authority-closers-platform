"""What each workspace is, in the words Admin shows.

One registry holds every workspace, and two of them used to read "Authority
Closers": the staff operations workspace and our own company's organisation.
The kind never comes from a name. The operations and Personal workspaces are
settings, a sandbox carries its approved flag, and our own company is a
registered organisation verified for an email domain of the operations staff.
Every other registered organisation is a customer.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import (
    Membership,
    Organisation,
    OrganisationDomainSetting,
    Tenant,
)

WorkspaceKind = Literal["company", "customer", "personal", "sandbox", "operations", "other"]

# The order Admin lists them in: ours first, the staff workspace last.
KIND_ORDER: tuple[WorkspaceKind, ...] = (
    "company",
    "customer",
    "personal",
    "sandbox",
    "operations",
    "other",
)

# The registered names of these two say nothing about what they hold.
CLEAR_NAMES: dict[WorkspaceKind, str] = {
    "personal": "Personal accounts",
    "operations": "AC Operations",
}


@dataclass(frozen=True)
class Workspace:
    tenant_id: UUID
    name: str
    registered_name: str
    kind: WorkspaceKind
    status: str


def clear_name(kind: WorkspaceKind, registered_name: str) -> str:
    return CLEAR_NAMES.get(kind, registered_name)


async def staff_domains(
    database: AsyncSession, operations_tenant_id: UUID | None
) -> frozenset[str]:
    """Email domains of the owners and admins of the operations workspace.

    Learners there are left out: one personal mail address would otherwise make
    any organisation verified for that public domain look like ours.
    """
    if operations_tenant_id is None:
        return frozenset()
    emails = await database.scalars(
        select(Person.email)
        .join(Membership, Membership.person_id == Person.id)
        .where(
            Membership.tenant_id == operations_tenant_id,
            Membership.role.in_(("owner", "admin")),
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    return frozenset(
        email.rsplit("@", 1)[1].strip().lower() for email in emails.all() if email and "@" in email
    )


async def _verified_domains(database: AsyncSession) -> dict[UUID, frozenset[str]]:
    """Each organisation's current verified domains (its newest domain setting)."""
    newest = (
        select(
            OrganisationDomainSetting.tenant_id,
            func.max(OrganisationDomainSetting.version).label("version"),
        )
        .group_by(OrganisationDomainSetting.tenant_id)
        .subquery()
    )
    setting = OrganisationDomainSetting
    rows = await database.execute(
        select(setting.tenant_id, setting.verified_domains).join(
            newest,
            and_(
                setting.tenant_id == newest.c.tenant_id,
                setting.version == newest.c.version,
            ),
        )
    )
    return {
        tenant_id: frozenset(str(domain).strip().lower() for domain in domains or ())
        for tenant_id, domains in rows.all()
    }


async def classify_workspaces(
    database: AsyncSession,
    *,
    operations_tenant_id: UUID | None,
    personal_tenant_id: UUID | None,
    tenant_ids: Iterable[UUID] | None = None,
) -> dict[UUID, Workspace]:
    """Every workspace (or the ones asked for) with its kind and a clear name."""
    query = select(Tenant.id, Tenant.name, Tenant.status, Organisation.tenant_id).outerjoin(
        Organisation, Organisation.tenant_id == Tenant.id
    )
    if tenant_ids is not None:
        wanted = set(tenant_ids)
        if not wanted:
            return {}
        query = query.where(Tenant.id.in_(wanted))
    rows = (await database.execute(query)).all()
    sandboxes = set(
        (await database.scalars(select(ConversationSandboxOrganisation.tenant_id))).all()
    )
    staff = await staff_domains(database, operations_tenant_id)
    domains = await _verified_domains(database) if staff else {}

    workspaces: dict[UUID, Workspace] = {}
    for tenant_id, registered_name, status, organisation in rows:
        kind: WorkspaceKind
        if tenant_id == operations_tenant_id:
            kind = "operations"
        elif tenant_id == personal_tenant_id:
            kind = "personal"
        elif tenant_id in sandboxes:
            kind = "sandbox"
        elif organisation is None:
            kind = "other"
        elif domains.get(tenant_id, frozenset()) & staff:
            kind = "company"
        else:
            kind = "customer"
        workspaces[tenant_id] = Workspace(
            tenant_id=tenant_id,
            name=clear_name(kind, registered_name),
            registered_name=registered_name,
            kind=kind,
            status=str(getattr(status, "value", status)),
        )
    return workspaces


def ordered(workspaces: Iterable[Workspace]) -> list[Workspace]:
    return sorted(
        workspaces,
        key=lambda item: (KIND_ORDER.index(item.kind), item.name.lower(), str(item.tenant_id)),
    )
