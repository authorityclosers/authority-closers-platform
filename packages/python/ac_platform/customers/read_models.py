"""Canonical C2 customer directory; no impersonation or state writes."""

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, literal, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.billing.ledger import BillingLedger
from ac_platform.billing.trial import TrialPolicy
from ac_platform.identity.models import Person
from ac_platform.identity.models import Session as IdentitySession
from ac_platform.tenancy.models import Membership, Organisation, Tenant


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CustomerQuery(_Strict):
    q: str | None = Field(default=None, min_length=2, max_length=120)
    kind: Literal["all", "personal", "organisation"] = "all"
    status: Literal["active", "suspended", "deleted", "all"] = "all"
    cursor: str | None = Field(default=None, min_length=1, max_length=300)
    limit: int = Field(default=25, ge=1, le=50)

    @field_validator("q", mode="before")
    @classmethod
    def empty_search(cls, value: object) -> object:
        return None if value == "" else value


class PersonalSummary(_Strict):
    plan_key: str | None
    available_seconds: int = Field(ge=0)
    used_seconds_30d: int = Field(ge=0)


class CustomerOrganisation(_Strict):
    tenant_id: UUID
    name: str
    role: str


class CustomerRow(_Strict):
    person_id: UUID
    name: str | None
    email: str | None
    status: Literal["active", "suspended", "deleted"]
    created_at: datetime
    last_active_at: datetime | None
    personal: PersonalSummary | None
    organisations: list[CustomerOrganisation]


class CustomerPage(_Strict):
    items: list[CustomerRow]
    next_cursor: str | None


def encode_cursor(created_at: datetime, person_id: UUID) -> str:
    value = [created_at.astimezone(UTC).isoformat().replace("+00:00", "Z"), str(person_id)]
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,300}", value) is None:
        raise ValueError("Invalid customer cursor.")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parts = json.loads(raw)
        if (
            not isinstance(parts, list)
            or len(parts) != 2
            or not all(isinstance(part, str) for part in parts)
        ):
            raise ValueError
        created_at, person_id = datetime.fromisoformat(parts[0]), UUID(parts[1])
        if created_at.tzinfo is None or encode_cursor(created_at, person_id) != value:
            raise ValueError
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid customer cursor.") from error
    return created_at, person_id


async def customer_page(
    database: AsyncSession,
    *,
    public_tenant_id: UUID,
    operations_tenant_id: UUID,
    query: CustomerQuery,
    trial_policy: TrialPolicy,
    now: datetime,
) -> CustomerPage:
    # Membership category selects customers. Person.status alone supplies status;
    # inactive memberships still preserve a suspended/deleted customer's identity.
    protected = (operations_tenant_id, public_tenant_id)
    personal = (
        select(Membership.person_id)
        .where(Membership.person_id == Person.id, Membership.tenant_id == public_tenant_id)
        .exists()
    )
    organisation = (
        select(Membership.person_id)
        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .where(Membership.person_id == Person.id, Membership.tenant_id.not_in(protected))
        .exists()
    )
    last_active = (
        select(func.max(IdentitySession.last_seen_at))
        .where(IdentitySession.person_id == Person.id, IdentitySession.audience == "account")
        .correlate(Person)
        .scalar_subquery()
    )
    statement = select(Person, last_active).where(
        personal
        if query.kind == "personal"
        else organisation
        if query.kind == "organisation"
        else or_(personal, organisation)
    )
    if query.status != "all":
        statement = statement.where(Person.status == query.status)
    if query.q is not None:
        statement = statement.where(
            or_(
                Person.email.istartswith(query.q, autoescape=True),
                Person.display_name.icontains(query.q, autoescape=True),
            )
        )
    if query.cursor is not None:
        created_at, person_id = decode_cursor(query.cursor)
        statement = statement.where(
            tuple_(Person.created_at, Person.id) < tuple_(literal(created_at), literal(person_id))
        )
    rows = (
        await database.execute(
            statement.order_by(Person.created_at.desc(), Person.id.desc()).limit(query.limit + 1)
        )
    ).all()
    page = rows[: query.limit]
    ids = [person.id for person, _ in page]
    personal_ids = set(
        await database.scalars(
            select(Membership.person_id).where(
                Membership.tenant_id == public_tenant_id, Membership.person_id.in_(ids)
            )
        )
    )
    organisations: dict[UUID, list[CustomerOrganisation]] = {person: [] for person in ids}
    for person_id, tenant_id, name, role in await database.execute(
        select(Membership.person_id, Tenant.id, Tenant.name, Membership.role)
        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.person_id.in_(ids), Membership.tenant_id.not_in(protected))
        .order_by(Tenant.name, Tenant.id)
    ):
        organisations[person_id].append(
            CustomerOrganisation(tenant_id=tenant_id, name=name, role=role)
        )
    ledger = BillingLedger(
        database, trial_policy=trial_policy, operations_tenant_id=operations_tenant_id
    )
    items = []
    for person, active_at in page:
        summary = None
        if person.id in personal_ids:
            projection = await ledger.project_person(
                tenant_id=public_tenant_id, person_id=person.id, now=now, mirror=False
            )
            uses = await ledger.person_uses(tenant_id=public_tenant_id, person_id=person.id)
            summary = PersonalSummary(
                plan_key=projection.plan_key,
                available_seconds=projection.available_seconds,
                used_seconds_30d=sum(
                    use.seconds for use in uses if now - timedelta(days=30) <= use.at <= now
                ),
            )
        items.append(
            CustomerRow.model_validate(
                {
                    "person_id": person.id,
                    "name": person.display_name,
                    "email": person.email,
                    "status": person.status,
                    "created_at": person.created_at,
                    "last_active_at": active_at,
                    "personal": summary,
                    "organisations": organisations[person.id],
                }
            )
        )
    return CustomerPage(
        items=items,
        next_cursor=encode_cursor(page[-1][0].created_at, page[-1][0].id)
        if len(rows) > query.limit
        else None,
    )
