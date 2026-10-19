"""The organisation's webhook, managed from Settings -> Integrations.

It is the partner-events endpoint (0096): the same table, events, signing, retries and
runner. Only the secret is new: the app makes it, shows it once and keeps it sealed
(``sealed.py``); the endpoint names it ``AC_PARTNER_WEBHOOK_SECRET__SEALED_<id>``.

- save: the first save makes a signing secret; a later save (new address, events or
  facts profile) keeps it. Saving over an endpoint AC set up by hand replaces it with
  an app-managed one and a new secret.
- rotate: a second secret signs alongside the first (two ``v1=`` values) until
  ``finish_rotation`` makes it the only one and retires the old one.
- test: one signed fictional ``sx.test.v1`` sent now, the answer shown at once.
- deliveries: the last 50 events (analysis and lead events) with their state, never
  their payload; a dead letter can be sent again.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.integrations import sealed
from ac_platform.integrations.errors import IntegrationError
from ac_platform.partner_events import endpoints as partner
from ac_platform.partner_events.delivery import mask_url
from ac_platform.partner_events.models import (
    PartnerLeadEvent,
    PartnerWebhookEndpoint,
    PartnerWebhookEvent,
)

EVENT_LABELS = {
    "analysis.completed": "A call's analysis is ready",
    "lead.created": "A lead is added",
    "lead.stage_changed": "A lead moves stage",
    "lead.closed": "A lead is won or lost",
}
REASON = "Settings -> Integrations"
_ERRORS = {
    "url_refused": "url",
    "events_invalid": "events",
    "facts_profile_unknown": "facts_profile",
}


def menu() -> dict[str, Any]:
    from ac_platform.partner_events.quote_facts import PROFILES

    return {
        "events": [{"key": key, "label": EVENT_LABELS.get(key, key)} for key in partner.EVENTS],
        "facts_profiles": sorted(PROFILES),
    }


def _operator(person_id: UUID) -> str:
    return f"settings:person:{person_id}"


async def active(session: AsyncSession, tenant_id: UUID) -> PartnerWebhookEndpoint | None:
    found: PartnerWebhookEndpoint | None = await session.scalar(
        select(PartnerWebhookEndpoint).where(
            PartnerWebhookEndpoint.tenant_id == tenant_id,
            PartnerWebhookEndpoint.status == "active",
        )
    )
    return found


async def view(session: AsyncSession, endpoint: PartnerWebhookEndpoint | None) -> Any:
    if endpoint is None:
        return None
    hints = await session.run_sync(
        lambda sync: (
            sealed.hint(sync.connection(), endpoint.secret_ref),
            sealed.hint(sync.connection(), endpoint.secret_ref_next),
        )
    )
    return {
        "id": str(endpoint.id),
        "url": endpoint.url,
        "host": mask_url(endpoint.url),
        "events": list(endpoint.events or []),
        "facts_profile": endpoint.facts_profile,
        "managed_in_app": sealed.id_from_ref(endpoint.secret_ref) is not None,
        "secret_hint": hints[0],
        "rotating": endpoint.secret_ref_next is not None,
        "next_secret_hint": hints[1],
        "created_at": endpoint.created_at.isoformat(),
    }


async def _new_secret(
    session: AsyncSession, key: sealed.SealKey, tenant_id: UUID, person_id: UUID, now: datetime
) -> tuple[str, str]:
    value = sealed.new_webhook_secret()
    secret_id = await session.run_sync(
        lambda sync: sealed.create(
            sync.connection(),
            key,
            tenant_id=tenant_id,
            purpose="webhook_signing",
            value=value,
            person_id=person_id,
            meta={"for": "webhook"},
            now=now,
        )
    )
    return value, sealed.ref_for(secret_id)


async def _register(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    url: str,
    secret_ref: str,
    secret_ref_next: str | None,
    events: list[str],
    facts_profile: str | None,
    supersede: bool,
    person_id: UUID,
    environment: str,
    now: datetime,
) -> None:
    try:
        await partner.register(
            session,
            tenant_id=tenant_id,
            url=url,
            secret_ref=secret_ref,
            secret_ref_next=secret_ref_next,
            events=events,
            facts_profile=facts_profile,
            reason=REASON,
            operator_reference=_operator(person_id),
            supersede=supersede,
            apply=True,
            environment=environment,
            now=now,
        )
    except partner.EndpointError as error:
        raise IntegrationError(_ERRORS.get(str(error), "webhook")) from None


async def _retire(
    session: AsyncSession, refs: list[str | None], person_id: UUID, now: datetime
) -> None:
    for ref in refs:
        found = sealed.id_from_ref(ref)
        if found is None:
            continue

        def retire(sync: Any, secret_id: UUID = found) -> None:
            sealed.retire(sync.connection(), secret_id, by=_operator(person_id), now=now)

        await session.run_sync(retire)


async def save(
    session: AsyncSession,
    key: sealed.SealKey,
    *,
    tenant_id: UUID,
    person_id: UUID,
    url: str,
    events: list[str],
    facts_profile: str | None,
    environment: str,
    now: datetime,
) -> str | None:
    """Add or change the webhook. Returns a new signing secret only when one was made."""
    current = await active(session, tenant_id)
    keep = current is not None and sealed.id_from_ref(current.secret_ref) is not None
    secret: str | None = None
    if keep:
        assert current is not None
        ref, ref_next = current.secret_ref, current.secret_ref_next
    else:
        secret, ref = await _new_secret(session, key, tenant_id, person_id, now)
        ref_next = None
    await _register(
        session,
        tenant_id=tenant_id,
        url=url.strip(),
        secret_ref=ref,
        secret_ref_next=ref_next,
        events=events,
        facts_profile=facts_profile,
        supersede=current is not None,
        person_id=person_id,
        environment=environment,
        now=now,
    )
    return secret


async def rotate(
    session: AsyncSession,
    key: sealed.SealKey,
    *,
    tenant_id: UUID,
    person_id: UUID,
    environment: str,
    now: datetime,
) -> str:
    current = await active(session, tenant_id)
    if current is None or sealed.id_from_ref(current.secret_ref) is None:
        raise IntegrationError("no_webhook", 409)
    if current.secret_ref_next is not None:
        raise IntegrationError("rotation_open", 409)
    secret, ref_next = await _new_secret(session, key, tenant_id, person_id, now)
    await _register(
        session,
        tenant_id=tenant_id,
        url=current.url,
        secret_ref=current.secret_ref,
        secret_ref_next=ref_next,
        events=list(current.events),
        facts_profile=current.facts_profile,
        supersede=True,
        person_id=person_id,
        environment=environment,
        now=now,
    )
    return secret


async def finish_rotation(
    session: AsyncSession, *, tenant_id: UUID, person_id: UUID, environment: str, now: datetime
) -> None:
    current = await active(session, tenant_id)
    if current is None or current.secret_ref_next is None:
        raise IntegrationError("no_rotation", 409)
    old = current.secret_ref
    await _register(
        session,
        tenant_id=tenant_id,
        url=current.url,
        secret_ref=current.secret_ref_next,
        secret_ref_next=None,
        events=list(current.events),
        facts_profile=current.facts_profile,
        supersede=True,
        person_id=person_id,
        environment=environment,
        now=now,
    )
    await _retire(session, [old], person_id, now)


async def disable(
    session: AsyncSession, *, tenant_id: UUID, person_id: UUID, now: datetime
) -> None:
    current = await active(session, tenant_id)
    if current is None:
        raise IntegrationError("no_webhook", 409)
    await partner.disable(
        session,
        endpoint_id=current.id,
        reason=REASON,
        operator_reference=_operator(person_id),
        apply=True,
        now=now,
    )
    await _retire(session, [current.secret_ref, current.secret_ref_next], person_id, now)


async def test(
    session: AsyncSession,
    key: sealed.SealKey,
    *,
    tenant_id: UUID,
    environment: str,
    now: datetime,
    client: Any = None,
) -> dict[str, Any]:
    """Send one signed fictional event now and say what the app answered."""
    from ac_platform.partner_events.delivery import http_client, post, url_allowed
    from ac_platform.partner_events.payload import body_bytes

    current = await active(session, tenant_id)
    if current is None:
        raise IntegrationError("no_webhook", 409)
    if not url_allowed(current.url, environment):
        raise IntegrationError("url")
    values = await session.run_sync(
        lambda sync: [
            value
            for ref in (current.secret_ref, current.secret_ref_next)
            if ref
            and (value := sealed.resolve(sync.connection(), ref, tenant_id=tenant_id, key=key))
            is not None
        ]
    )
    if not values:
        raise IntegrationError("secret_not_in_app", 409)
    body = partner.fictional_test_body(tenant_id, now)
    started = time.monotonic()
    if client is None:
        async with http_client() as owned:
            outcome = await post(
                owned,
                url=current.url,
                event_id=body["event_id"],
                event_type="test",
                body=body_bytes(body),
                secrets=values,
                environment=environment,
            )
    else:
        outcome = await post(
            client,
            url=current.url,
            event_id=body["event_id"],
            event_type="test",
            body=body_bytes(body),
            secrets=values,
            environment=environment,
        )
    duration_ms = int((time.monotonic() - started) * 1000)
    await partner.record_test_event(
        session,
        endpoint=current,
        event_id=body["event_id"],
        http_status=outcome.http_status,
        error_code=outcome.error_code,
        duration_ms=duration_ms,
        now=now,
    )
    return {
        "event_id": body["event_id"],
        "delivered": outcome.delivered,
        "http_status": outcome.http_status,
        "error_code": outcome.error_code,
        "duration_ms": duration_ms,
    }


async def deliveries(
    session: AsyncSession, tenant_id: UUID, limit: int = 50
) -> list[dict[str, Any]]:
    """The newest events for this organisation's webhooks: state only, never payloads."""
    columns = (
        "id",
        "event_type",
        "status",
        "attempts",
        "last_http_status",
        "last_error_code",
        "created_at",
        "delivered_at",
        "next_attempt_at",
    )
    analysis = select(*(getattr(PartnerWebhookEvent, name) for name in columns)).where(
        PartnerWebhookEvent.tenant_id == tenant_id
    )
    lead = select(*(getattr(PartnerLeadEvent, name) for name in columns)).where(
        PartnerLeadEvent.tenant_id == tenant_id, PartnerLeadEvent.endpoint_id.is_not(None)
    )
    merged = union_all(analysis, lead).subquery()
    rows = (
        await session.execute(select(merged).order_by(merged.c.created_at.desc()).limit(limit))
    ).all()
    return [
        {
            "id": str(row.id),
            "event_type": row.event_type,
            "status": row.status,
            "attempts": row.attempts,
            "last_http_status": row.last_http_status,
            "last_error_code": row.last_error_code,
            "created_at": row.created_at.isoformat(),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "next_attempt_at": row.next_attempt_at.isoformat() if row.status == "pending" else None,
        }
        for row in rows
    ]


async def retry(
    session: AsyncSession, *, tenant_id: UUID, event_id: UUID, person_id: UUID, now: datetime
) -> None:
    owned = await session.scalar(
        select(PartnerWebhookEvent.id).where(
            PartnerWebhookEvent.id == event_id, PartnerWebhookEvent.tenant_id == tenant_id
        )
    ) or await session.scalar(
        select(PartnerLeadEvent.id).where(
            PartnerLeadEvent.id == event_id, PartnerLeadEvent.tenant_id == tenant_id
        )
    )
    if owned is None:
        raise IntegrationError("not_found", 404)
    try:
        await partner.replay(
            session,
            event_id=event_id,
            reason=REASON,
            operator_reference=_operator(person_id),
            apply=True,
            now=now,
        )
    except partner.EndpointError:
        raise IntegrationError("not_dead_letter", 409) from None
