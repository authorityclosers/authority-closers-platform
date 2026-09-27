"""Finite, audited administrator grants against the canonical learner ledger."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.models import AuditEvent
from ac_platform.conversation_intelligence.entitlements import (
    MinuteAccount,
    MinuteGrant,
    grant_minutes,
)
from ac_platform.conversation_intelligence.models import ConversationMinuteAccount
from ac_platform.identity.models import Person
from ac_platform.tenancy.models import Membership, Tenant

MINUTE_GRANT_ACTION = "operations.conversation_minute_granted"
MINUTE_GRANT_RESOURCE_TYPE = "conversation_minute_grant"


class EligibleLearnerUnavailable(Exception):
    """The exact requested tenant/person pair is not an eligible learner."""


class EligibleLearnerBusy(Exception):
    """The learner account is being changed; the caller may retry the command."""


class InvalidMinuteAccountSnapshot(Exception):
    """The persisted finite minute ledger cannot be read safely."""


@dataclass(frozen=True, slots=True)
class MinuteAccountState:
    account: MinuteAccount
    revision: int


async def require_eligible_learner(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    operations_tenant_id: UUID,
    lock_person: bool = False,
) -> None:
    """Check the exact active learner pair; platform authority does not bypass it."""

    if tenant_id == operations_tenant_id:
        raise EligibleLearnerUnavailable
    person_statement = (
        select(Person).where(Person.id == person_id).execution_options(populate_existing=True)
    )
    if lock_person:
        # Account owners authenticate through this same Person row. Take it
        # first, matching the learner path, but fail quickly when another
        # command already owns it. This also breaks mutual-admin target cycles:
        # each request can hold its own Person before trying to target the other.
        person_statement = person_statement.with_for_update(nowait=True)
    try:
        person = await database.scalar(person_statement)
    except DBAPIError as error:
        if lock_person and _is_lock_not_available(error):
            raise EligibleLearnerBusy from error
        raise
    tenant_statement = select(Tenant).where(Tenant.id == tenant_id)
    membership_statement = select(Membership).where(
        Membership.tenant_id == tenant_id,
        Membership.person_id == person_id,
        Membership.role == "learner",
        Membership.status == "active",
        Membership.ended_at.is_(None),
    )
    if lock_person:
        # Recheck tenant and membership while holding compatible shared locks.
        # Identity deletion and supported account-state changes take Person
        # first, then alter membership; the lock order remains Person → Tenant
        # → Membership → minute account.
        tenant_statement = tenant_statement.with_for_update(read=True)
        membership_statement = membership_statement.with_for_update(read=True)
    tenant = await database.scalar(tenant_statement.execution_options(populate_existing=True))
    membership = await database.scalar(
        membership_statement.execution_options(populate_existing=True)
    )
    if (
        tenant is None
        or tenant.status != "active"
        or person is None
        or person.status != "active"
        or person.email_verified_at is None
        or membership is None
    ):
        raise EligibleLearnerUnavailable


def _is_lock_not_available(error: DBAPIError) -> bool:
    original = error.orig
    return (
        getattr(original, "sqlstate", None) == "55P03"
        or getattr(getattr(original, "diag", None), "sqlstate", None) == "55P03"
    )


async def load_minute_account(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    lock: bool = False,
) -> MinuteAccountState:
    statement = select(ConversationMinuteAccount).where(
        ConversationMinuteAccount.tenant_id == tenant_id,
        ConversationMinuteAccount.person_id == person_id,
    )
    if lock:
        statement = statement.with_for_update()
    row = await database.scalar(statement.execution_options(populate_existing=True))
    if row is None:
        return MinuteAccountState(
            account=MinuteAccount(str(tenant_id), str(person_id)),
            revision=0,
        )
    try:
        account = MinuteAccount.from_dict(row.snapshot)
    except (TypeError, ValueError) as error:
        raise InvalidMinuteAccountSnapshot from error
    if (account.tenant_id, account.account_id) != (str(tenant_id), str(person_id)):
        raise InvalidMinuteAccountSnapshot
    return MinuteAccountState(account=account, revision=row.revision)


async def audited_admin_grant_seconds(
    database: AsyncSession,
    *,
    account: MinuteAccount,
    tenant_id: UUID,
    person_id: UUID,
    operations_tenant_id: UUID,
) -> int:
    """Count only finite grants backed by the canonical operations event.

    Hosted release allowances and derived tester flags are intentionally not
    upload-quota extensions. A grant contributes only when its snapshot entry
    is bound to the immutable audit event emitted by the admin grant route.
    """

    candidates: list[tuple[MinuteGrant, UUID]] = []
    for grant in account.grants:
        if (
            grant.tenant_id != str(tenant_id)
            or grant.account_id != str(person_id)
            or type(grant.seconds) is not int
            or grant.seconds % 60 != 0
            or not grant.authorization_ref.startswith("audit-event:")
        ):
            continue
        try:
            event_id = UUID(grant.authorization_ref.removeprefix("audit-event:"))
            UUID(grant.grant_id)
            UUID(grant.granted_by)
        except ValueError:
            continue
        candidates.append((grant, event_id))
    if not candidates:
        return 0

    event_ids = {event_id for _, event_id in candidates}
    events = (
        await database.scalars(
            select(AuditEvent).where(
                AuditEvent.id.in_(event_ids),
                AuditEvent.tenant_id == operations_tenant_id,
                AuditEvent.action == MINUTE_GRANT_ACTION,
                AuditEvent.resource_type == MINUTE_GRANT_RESOURCE_TYPE,
            )
        )
    ).all()
    events_by_id = {event.id: event for event in events}
    additional_seconds = 0
    for grant, event_id in candidates:
        event = events_by_id.get(event_id)
        payload = None if event is None else event.payload
        if (
            event is None
            or event.resource_id != grant.grant_id
            or event.actor_person_id is None
            or str(event.actor_person_id) != grant.granted_by
            or event.reason != grant.reason
            or type(payload) is not dict
            or set(payload)
            != {
                "idempotency_key",
                "request_digest",
                "grant_id",
                "tenant_id",
                "person_id",
                "minutes",
                "seconds",
            }
            or payload.get("grant_id") != grant.grant_id
            or payload.get("tenant_id") != str(tenant_id)
            or payload.get("person_id") != str(person_id)
            or type(payload.get("minutes")) is not int
            or payload.get("minutes") != grant.seconds // 60
            or type(payload.get("seconds")) is not int
            or payload.get("seconds") != grant.seconds
            or not isinstance(payload.get("idempotency_key"), str)
            or not payload["idempotency_key"]
            or not isinstance(payload.get("request_digest"), str)
            or len(payload["request_digest"]) != 64
            or any(char not in "0123456789abcdef" for char in payload["request_digest"])
        ):
            continue
        additional_seconds += grant.seconds
    return additional_seconds


async def append_minute_grant(
    database: AsyncSession,
    *,
    tenant_id: UUID,
    person_id: UUID,
    operations_tenant_id: UUID,
    grant: MinuteGrant,
) -> MinuteAccountState:
    """Append one immutable finite grant and keep the learner ledger revision."""

    await require_eligible_learner(
        database,
        tenant_id=tenant_id,
        person_id=person_id,
        operations_tenant_id=operations_tenant_id,
        lock_person=True,
    )
    row = await database.scalar(
        select(ConversationMinuteAccount)
        .where(
            ConversationMinuteAccount.tenant_id == tenant_id,
            ConversationMinuteAccount.person_id == person_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    try:
        before = (
            MinuteAccount(str(tenant_id), str(person_id))
            if row is None
            else MinuteAccount.from_dict(row.snapshot)
        )
    except (TypeError, ValueError) as error:
        raise InvalidMinuteAccountSnapshot from error
    if (before.tenant_id, before.account_id) != (str(tenant_id), str(person_id)):
        raise InvalidMinuteAccountSnapshot
    try:
        after = grant_minutes(before, grant)
    except ValueError as error:
        raise InvalidMinuteAccountSnapshot from error
    if row is None:
        row = ConversationMinuteAccount(
            tenant_id=tenant_id,
            person_id=person_id,
            snapshot=after.as_dict(),
            revision=1,
        )
        database.add(row)
    else:
        row.snapshot = after.as_dict()
        row.revision += 1
    await database.flush()
    return MinuteAccountState(account=after, revision=row.revision)
