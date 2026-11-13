"""The tester welcome email (owner, 13 Nov 2026: "selected people get a professional, branded
email"), in the style of the one the owner sent by hand that day: the green card, the logo,
three numbered steps with buttons and an "Item not found" box.

It goes only from Admin -> Testers, for a tester the team approved and added to the Google
Group (store.request_welcome), through the outbox like every other email. The links are
fixed here, never taken from the job: the Play opt-in page, the store page and our site.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.outbox.models import Job
from ac_platform.outbox.repository import OutboxJobRoute
from ac_platform.providers.ports import EmailMessage, PermanentProviderError
from ac_platform.testers import store
from ac_platform.testers.models import SalesXrayTesterEvent

TEMPLATE = "sales-xray-tester-welcome"
WELCOME_ROUTE = OutboxJobRoute(
    job_kind=store.WELCOME_JOB,
    required_payload_keys=frozenset({"tester_event_id"}),
    uuid_payload_keys=frozenset({"tester_event_id"}),
)


async def resolve_tester_welcome_message(
    database: AsyncSession, settings: Any, job: Job, *, provider_key: str
) -> EmailMessage:
    if job.kind != store.WELCOME_JOB:
        raise PermanentProviderError("tester welcome route is unavailable")
    payload = WELCOME_ROUTE.normalize_payload(job.payload)
    row = await database.get(SalesXrayTesterEvent, UUID(payload["tester_event_id"]))
    if row is None or row.kind != "emailed" or row.via != "app":
        raise PermanentProviderError("tester welcome is unavailable")
    standing = await store.standing_for_email(database, row.email)
    if standing is None or standing.decision == "declined" or standing.in_group_at is None:
        raise PermanentProviderError("tester is no longer in the Play group")
    return EmailMessage(
        to=row.email,
        template=TEMPLATE,
        template_version=1,
        idempotency_key=provider_key,
        communication_class="enrollment_welcome_next_action",
        variables={"first_name": store.first_name(standing.name), "email": row.email},
    )


__all__ = ["TEMPLATE", "WELCOME_ROUTE", "resolve_tester_welcome_message"]
