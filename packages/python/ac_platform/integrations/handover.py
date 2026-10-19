"""The organisation's hand-over to its own customer app, managed from Settings -> Integrations.

When a lead is won, Sales X-Ray calls the organisation's app (``POST
<app>/api/v1/service/customers/handover``) with the app's service key as the bearer
(0102, ``partner_events.lead_events``). Here the organisation's owner or admin sets
the app's address, pastes the service key (sealed as ``partner_key``, never shown
again) and approves which optional parts go and from which form questions. The
recipient row is the 0102 one, superseded never edited; its secret name is the sealed
``AC_PARTNER_WEBHOOK_SECRET__SEALED_<id>``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.integrations import sealed
from ac_platform.integrations.errors import IntegrationError
from ac_platform.partner_events import endpoints as partner
from ac_platform.partner_events.delivery import mask_url
from ac_platform.partner_events.lead_events import (
    CONSENT_CHANNELS,
    CONSENT_PURPOSES,
    HANDOVER_PATH,
    OPTIONAL,
    QUESTION_PATHS,
    LeadFieldsError,
    validate_lead_fields,
)
from ac_platform.partner_events.models import PartnerHandoverRecipient

REASON = "Settings -> Integrations"
PART_LABELS = {
    "email": "Email",
    "address": "Address",
    "attribution": "Campaign",
    "requirement": "Requirement",
    "salesperson": "Salesperson",
    "consents": "Consents",
    "history": "Lead history",
    "links": "Links to the calls",
}


def menu() -> dict[str, Any]:
    return {
        "path": HANDOVER_PATH,
        "parts": [{"key": part, "label": PART_LABELS.get(part, part)} for part in OPTIONAL],
        "questions": [{"path": path, "part": part} for path, part in QUESTION_PATHS.items()],
        "consent_purposes": list(CONSENT_PURPOSES),
        "consent_channels": list(CONSENT_CHANNELS),
    }


def full_url(address: str) -> str:
    """The app's address, with the hand-over path added when it is not there yet."""
    cleaned = address.strip().rstrip("/")
    return cleaned if cleaned.endswith(HANDOVER_PATH) else cleaned + HANDOVER_PATH


async def active(session: AsyncSession, tenant_id: UUID) -> PartnerHandoverRecipient | None:
    found: PartnerHandoverRecipient | None = await session.scalar(
        select(PartnerHandoverRecipient).where(
            PartnerHandoverRecipient.tenant_id == tenant_id,
            PartnerHandoverRecipient.status == "active",
        )
    )
    return found


async def view(session: AsyncSession, recipient: PartnerHandoverRecipient | None) -> Any:
    if recipient is None:
        return None
    hint = await session.run_sync(lambda sync: sealed.hint(sync.connection(), recipient.secret_ref))
    return {
        "id": str(recipient.id),
        "url": recipient.url,
        "host": mask_url(recipient.url),
        "lead_fields": recipient.lead_fields,
        "managed_in_app": sealed.id_from_ref(recipient.secret_ref) is not None,
        "key_hint": hint,
        "created_at": recipient.created_at.isoformat(),
    }


def _operator(person_id: UUID) -> str:
    return f"settings:person:{person_id}"


async def save(
    session: AsyncSession,
    key: sealed.SealKey,
    *,
    tenant_id: UUID,
    person_id: UUID,
    address: str,
    service_key: str | None,
    lead_fields: Any,
    environment: str,
    now: datetime,
) -> None:
    current = await active(session, tenant_id)
    try:
        fields = validate_lead_fields(lead_fields, "handover")
    except LeadFieldsError:
        raise IntegrationError("lead_fields") from None
    if service_key:
        value = service_key.strip()
        secret_id = await session.run_sync(
            lambda sync: sealed.create(
                sync.connection(),
                key,
                tenant_id=tenant_id,
                purpose="partner_key",
                value=value,
                person_id=person_id,
                meta={"for": "handover"},
                now=now,
            )
        )
        ref = sealed.ref_for(secret_id)
    elif current is not None and sealed.id_from_ref(current.secret_ref) is not None:
        ref = current.secret_ref
    else:
        raise IntegrationError("service_key")
    try:
        await partner.register(
            session,
            tenant_id=tenant_id,
            url=full_url(address),
            secret_ref=ref,
            secret_ref_next=None,
            events=["lead.handover"],
            facts_profile=None,
            reason=REASON,
            operator_reference=_operator(person_id),
            supersede=current is not None,
            apply=True,
            environment=environment,
            now=now,
            kind="handover",
            lead_fields=fields,
        )
    except partner.EndpointError as error:
        code = str(error)
        raise IntegrationError("handover_url" if "url" in code else "handover") from None
    if current is not None and service_key:
        await _retire(session, current.secret_ref, person_id, now)


async def _retire(session: AsyncSession, ref: str | None, person_id: UUID, now: datetime) -> None:
    found = sealed.id_from_ref(ref)
    if found is None:
        return

    def retire(sync: Any, secret_id: UUID = found) -> None:
        sealed.retire(sync.connection(), secret_id, by=_operator(person_id), now=now)

    await session.run_sync(retire)


async def disable(
    session: AsyncSession, *, tenant_id: UUID, person_id: UUID, now: datetime
) -> None:
    current = await active(session, tenant_id)
    if current is None:
        raise IntegrationError("no_handover", 409)
    await partner.disable(
        session,
        endpoint_id=current.id,
        reason=REASON,
        operator_reference=_operator(person_id),
        apply=True,
        now=now,
    )
    await _retire(session, current.secret_ref, person_id, now)
