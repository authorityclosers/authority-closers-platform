"""Bounded, tenant-scoped member directory from canonical membership records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ac_platform.community.models import CohorvaPublicProfile
from ac_platform.enrollment.models import Enrollment
from ac_platform.identity.models import Person
from ac_platform.learning.admin_diagnosis import DiagnosisLookupInvalid, _mask_email
from ac_platform.tenancy.models import Membership, Tenant

DirectoryRole = Literal["all", "learner", "support", "admin", "owner"]
DirectoryStatus = Literal["all", "active", "inactive", "suspended", "unverified"]


@dataclass(frozen=True, slots=True)
class DirectoryMember:
    person_id: UUID
    display_name: str
    username: str | None
    masked_email: str
    membership_role: str
    membership_status: str
    account_status: str
    email_verified: bool
    joined_at: datetime
    active_enrollments: int


@dataclass(frozen=True, slots=True)
class DirectorySummary:
    total: int
    active_learners: int
    team: int
    unverified: int


@dataclass(frozen=True, slots=True)
class MemberDirectory:
    tenant_id: UUID
    tenant_name: str
    members: tuple[DirectoryMember, ...]
    summary: DirectorySummary
    matching_count: int
    page: int
    page_size: int


def list_members(
    database: Session,
    *,
    tenant_id: UUID,
    query: str = "",
    role: DirectoryRole = "all",
    status: DirectoryStatus = "all",
    page: int = 1,
    page_size: int = 25,
) -> MemberDirectory:
    """Return one academy's members; never join or infer another tenant's access."""
    query = query.strip().lower()
    if (
        len(query) > 320
        or role not in {"all", "learner", "support", "admin", "owner"}
        or status not in {"all", "active", "inactive", "suspended", "unverified"}
        or not 1 <= page <= 10000
        or not 1 <= page_size <= 50
    ):
        raise DiagnosisLookupInvalid("Invalid member directory filters.")
    academy = database.scalar(
        select(Tenant).where(Tenant.id == tenant_id, Tenant.status == "active")
    )
    if academy is None:
        raise DiagnosisLookupInvalid("Academy directory is unavailable.")
    base = (
        select(Membership, Person, CohorvaPublicProfile)
        .join(Person, Person.id == Membership.person_id)
        .outerjoin(CohorvaPublicProfile, CohorvaPublicProfile.person_id == Person.id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.role != "processing",
            Person.status != "deleted",
        )
    )
    active = (Membership.status == "active") & (Person.status == "active")
    counts = database.execute(
        base.with_only_columns(
            func.count(),
            func.coalesce(func.sum(case((active & (Membership.role == "learner"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((active & (Membership.role != "learner"), 1), else_=0)), 0),
            func.coalesce(func.sum(case((Person.email_verified_at.is_(None), 1), else_=0)), 0),
            maintain_column_froms=True,
        )
    ).one()
    filtered = base
    if query:
        # Escape LIKE metacharacters; '%' and '_' are literal search input.
        escaped = query.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"%{escaped}%"
        filtered = filtered.where(
            or_(
                func.lower(Person.display_name).like(pattern, escape="!"),
                func.lower(Person.email).like(pattern, escape="!"),
                func.lower(CohorvaPublicProfile.username).like(pattern, escape="!"),
            )
        )
    if role != "all":
        filtered = filtered.where(Membership.role == role)
    if status == "active":
        filtered = filtered.where(active)
    elif status == "inactive":
        filtered = filtered.where(Membership.status == "inactive")
    elif status == "suspended":
        filtered = filtered.where(Person.status == "suspended")
    elif status == "unverified":
        filtered = filtered.where(Person.email_verified_at.is_(None))
    matching = (
        database.scalar(filtered.with_only_columns(func.count(), maintain_column_froms=True)) or 0
    )
    rows = database.execute(
        filtered.order_by(Membership.created_at.desc(), Person.id)
        .limit(page_size)
        .offset((page - 1) * page_size)
    ).all()
    person_ids = [person.id for _membership, person, _profile in rows]
    enrollments: dict[UUID, int] = (
        {
            person_id: count
            for person_id, count in database.execute(
                select(Enrollment.person_id, func.count())
                .where(
                    Enrollment.tenant_id == tenant_id,
                    Enrollment.person_id.in_(person_ids),
                    Enrollment.status == "active",
                )
                .group_by(Enrollment.person_id)
            ).all()
        }
        if person_ids
        else {}
    )
    return MemberDirectory(
        tenant_id=tenant_id,
        tenant_name=academy.name,
        members=tuple(
            DirectoryMember(
                person_id=person.id,
                display_name=person.display_name or "Academy member",
                username=profile.username if profile else None,
                masked_email=_mask_email(person.email),
                membership_role=membership.role,
                membership_status=membership.status,
                account_status=person.status,
                email_verified=person.email_verified_at is not None,
                joined_at=membership.created_at,
                active_enrollments=enrollments.get(person.id, 0),
            )
            for membership, person, profile in rows
        ),
        summary=DirectorySummary(*counts),
        matching_count=matching,
        page=page,
        page_size=page_size,
    )
