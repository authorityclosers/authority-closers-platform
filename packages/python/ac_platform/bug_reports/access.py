"""Who may use the advanced bug reporter (owner, 31 Oct 2026).

On for the platform's own staff (support, admins and owners outside customer organisations,
admin@ among them), for everyone in the Authority Closers organisation and in the flagged
sandbox organisations the testers use (orchestrator for the owner, 31 Oct 2026), and for the
testers the owner lets in. Anyone else may ask: the request waits in Admin, where the owner
lets them in or turns them down, and can take it away later, from anyone but staff. Every
step is a new row in ``bug_reporter_access``; the newest per person stands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.bug_reports.models import BugReporterAccess
from ac_platform.conversation_intelligence.synthetic_import_models import (
    ConversationSandboxOrganisation,
)
from ac_platform.identity.application import has_platform_staff_membership
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, MembershipStatus, OrganisationDomainSetting

Access = Literal["on", "requested", "off"]
DECISIONS = ("granted", "denied", "revoked")

#: The Authority Closers organisation: the one whose verified email domains name ours.
AC_DOMAIN = "authorityclosers.com"


async def _newest(db: AsyncSession, person_id: UUID) -> str | None:
    kind: str | None = await db.scalar(
        select(BugReporterAccess.kind)
        .where(BugReporterAccess.person_id == person_id)
        .order_by(BugReporterAccess.created_at.desc(), BugReporterAccess.id.desc())
        .limit(1)
    )
    return kind


async def _in_our_organisations(db: AsyncSession, person_id: UUID) -> bool:
    """An active member of a flagged sandbox organisation, or of the AC organisation."""
    theirs = select(Membership.tenant_id).where(
        Membership.person_id == person_id,
        Membership.status == MembershipStatus.ACTIVE.value,
    )
    sandbox = await db.scalar(
        select(ConversationSandboxOrganisation.tenant_id)
        .where(ConversationSandboxOrganisation.tenant_id.in_(theirs))
        .limit(1)
    )
    if sandbox is not None:
        return True
    # Domain settings are versioned: each organisation's newest one stands.
    newest: dict[UUID, tuple[int, list[str]]] = {}
    for tenant_id, version, domains in await db.execute(
        select(
            OrganisationDomainSetting.tenant_id,
            OrganisationDomainSetting.version,
            OrganisationDomainSetting.verified_domains,
        ).where(OrganisationDomainSetting.tenant_id.in_(theirs))
    ):
        if tenant_id not in newest or version > newest[tenant_id][0]:
            newest[tenant_id] = (version, list(domains or []))
    return any(
        AC_DOMAIN in {str(domain).lower() for domain in domains} for _, domains in newest.values()
    )


async def access_for(db: AsyncSession, person_id: UUID) -> Access:
    if await has_platform_staff_membership(db, person_id):
        return "on"
    newest = await _newest(db, person_id)
    # The owner's "take away" holds for anyone but staff.
    if newest == "revoked":
        return "off"
    if newest == "granted" or await _in_our_organisations(db, person_id):
        return "on"
    return "requested" if newest == "requested" else "off"


async def ask(db: AsyncSession, person_id: UUID, *, now: datetime) -> Access:
    """Asks the owner once; asking again while it waits, or when it is on, changes nothing."""
    current = await access_for(db, person_id)
    if current != "off":
        return current
    db.add(
        BugReporterAccess(
            id=uuid4(),
            person_id=person_id,
            kind="requested",
            actor_person_id=person_id,
            created_at=now,
        )
    )
    await db.flush()
    return "requested"


async def decide(
    db: AsyncSession,
    person_id: UUID,
    *,
    kind: str,
    actor_person_id: UUID,
    note: str | None,
    now: datetime,
) -> None:
    if kind not in DECISIONS:
        raise ValueError("Choose let in, turn down or take away.")
    if actor_person_id == person_id:
        raise ValueError("Someone else decides for you.")
    db.add(
        BugReporterAccess(
            id=uuid4(),
            person_id=person_id,
            kind=kind,
            actor_person_id=actor_person_id,
            note=note,
            created_at=now,
        )
    )
    await db.flush()


async def people(db: AsyncSession) -> list[dict[str, Any]]:
    """Everyone with an access history: where each stands now, waiting requests first."""
    rows = (
        await db.execute(
            select(BugReporterAccess, Person.display_name, Person.email)
            .join(Person, Person.id == BugReporterAccess.person_id)
            .order_by(BugReporterAccess.created_at, BugReporterAccess.id)
        )
    ).all()
    standing: dict[UUID, dict[str, Any]] = {}
    for row, name, email in rows:
        entry = standing.setdefault(
            row.person_id,
            {"person_id": str(row.person_id), "name": name, "email": email, "asked_at": None},
        )
        if row.kind == "requested":
            entry["asked_at"] = row.created_at.isoformat()
        entry["state"] = row.kind
        entry["since"] = row.created_at.isoformat()
        entry["note"] = row.note
    return sorted(
        standing.values(),
        key=lambda item: (item["state"] != "requested", item["since"]),
    )
