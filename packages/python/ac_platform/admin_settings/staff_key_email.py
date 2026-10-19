"""The email a control account gets when a production staff key is made for them.

Durable through the outbox (orchestrator's go, 19 Oct 2026): the message is resolved
from the key's row when it is sent, names the key by its prefix and never carries the
key, and links to Admin -> Integrations to revoke it.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.admin_settings.models import AdminStaffKey
from ac_platform.identity.models import Person
from ac_platform.kernel.events import EventCategory, EventEnvelope
from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute, OutboxRepository
from ac_platform.providers.ports import EmailMessage, PermanentProviderError

STAFF_KEY_CREATED_EVENT = "admin.staff_key.created.v1"
STAFF_KEY_CREATED_JOB = "email.admin_staff_key_created.v1"
STAFF_KEY_CREATED_ROUTE = OutboxJobRoute(
    job_kind=STAFF_KEY_CREATED_JOB,
    required_payload_keys=frozenset({"key_id"}),
    uuid_payload_keys=frozenset({"key_id"}),
)


async def enqueue_staff_key_email(database: AsyncSession, row: AdminStaffKey) -> None:
    await OutboxRepository(database).enqueue(
        EventEnvelope(
            name=STAFF_KEY_CREATED_EVENT,
            category=EventCategory.OPERATIONAL,
            aggregate_type="admin_staff_key",
            aggregate_id=row.id,
            tenant_id=row.tenant_id,
            payload={"key_id": str(row.id)},
        ),
        dedupe_key=f"admin-staff-key-created:{row.id}",
    )


async def resolve_staff_key_created_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != STAFF_KEY_CREATED_JOB:
        raise PermanentProviderError("staff key notice route is unavailable")
    payload = STAFF_KEY_CREATED_ROUTE.normalize_payload(job.payload)
    row = await database.get(AdminStaffKey, UUID(payload["key_id"]))
    person = None if row is None else await database.get(Person, row.person_id)
    if row is None or person is None or not person.email:
        raise PermanentProviderError("staff key notice is unavailable")
    return EmailMessage(
        to=person.email,
        template="admin-staff-key-created",
        template_version=1,
        idempotency_key=provider_key,
        communication_class="verification_security",
        variables={
            "first_name": person.first_name or "there",
            "key_prefix": row.prefix,
            "key_name": row.name,
            "action_link": f"{str(settings.admin_app_url).rstrip('/')}/integrations",
        },
    )
