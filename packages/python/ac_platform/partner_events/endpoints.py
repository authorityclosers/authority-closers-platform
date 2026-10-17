"""Operator commands for partner endpoints and events: register, disable, list, replay, test.

Every command is a dry run unless applied, prints before and after, and an
applied change writes an audit event in the workspace's chain naming the
operator reference and reason. Secrets are never stored or printed: an
endpoint keeps only the name of the environment variable that holds its
secret. URLs are shown as scheme, host and port only.

An endpoint's URL or secret is never changed in place. ``supersede`` disables
the active endpoint and adds a new one in one transaction; the old endpoint's
undelivered events move to the new one with their frozen bytes, so a URL
change or a secret rotation loses nothing.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from ac_platform.partner_events.delivery import mask_url, url_allowed
from ac_platform.partner_events.models import SECRET_REF_PATTERN
from ac_platform.partner_events.quote_facts import PROFILES

EVENTS = ("analysis.completed",)
RESOURCE_ENDPOINT = "partner_webhook_endpoint"
RESOURCE_EVENT = "partner_webhook_event"


class EndpointError(ValueError):
    """Stable code only."""


def _text(value: str, name: str, limit: int) -> str:
    cleaned = " ".join((value or "").split())
    if not cleaned or len(cleaned) > limit:
        raise EndpointError(f"{name}_invalid")
    return cleaned


def validate(
    *,
    url: str,
    secret_ref: str,
    secret_ref_next: str | None,
    events: list[str],
    facts_profile: str | None,
    environment: str,
) -> None:
    if len(url) > 2048 or not url_allowed(url, environment):
        raise EndpointError("url_refused")
    for name in (secret_ref, *([secret_ref_next] if secret_ref_next else [])):
        if not re.fullmatch(SECRET_REF_PATTERN, name):
            raise EndpointError("secret_ref_invalid")
    if secret_ref_next == secret_ref:
        raise EndpointError("secret_ref_next_invalid")
    if (
        not events
        or any(event not in EVENTS for event in events)
        or len(set(events)) != len(events)
    ):
        raise EndpointError("events_invalid")
    if facts_profile is not None and facts_profile not in PROFILES:
        raise EndpointError("facts_profile_unknown")


def view(endpoint: Any) -> dict[str, Any]:
    return {
        "endpoint_id": str(endpoint.id),
        "tenant_id": str(endpoint.tenant_id),
        "url": mask_url(endpoint.url),
        "secret_ref": endpoint.secret_ref,
        "secret_ref_next": endpoint.secret_ref_next,
        "events": list(endpoint.events or []),
        "facts_profile": endpoint.facts_profile,
        "status": endpoint.status,
        "events_since": endpoint.events_since.isoformat(),
        "supersedes_endpoint_id": (
            str(endpoint.supersedes_endpoint_id) if endpoint.supersedes_endpoint_id else None
        ),
        "created_by": endpoint.created_by,
        "created_at": endpoint.created_at.isoformat(),
        "disabled_at": endpoint.disabled_at.isoformat() if endpoint.disabled_at else None,
    }


async def _audit(
    session: Any,
    *,
    tenant_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    payload: dict[str, Any],
    reason: str,
    now: datetime,
) -> None:
    from ac_platform.audit.service import append_audit_event

    await append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_person_id=None,
        actor_type="operator",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload,
        reason=reason[:500],
        now=now,
    )


async def register(
    session: Any,
    *,
    tenant_id: UUID,
    url: str,
    secret_ref: str,
    secret_ref_next: str | None,
    events: list[str],
    facts_profile: str | None,
    reason: str,
    operator_reference: str,
    supersede: bool,
    apply: bool,
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    from sqlalchemy import select, update

    from ac_platform.partner_events.models import PartnerWebhookEndpoint, PartnerWebhookEvent
    from ac_platform.tenancy.models import Tenant

    reason = _text(reason, "reason", 500)
    operator_reference = _text(operator_reference, "operator_reference", 160)
    validate(
        url=url,
        secret_ref=secret_ref,
        secret_ref_next=secret_ref_next,
        events=events,
        facts_profile=facts_profile,
        environment=environment,
    )
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise EndpointError("tenant_missing")
    active = await session.scalar(
        select(PartnerWebhookEndpoint)
        .where(
            PartnerWebhookEndpoint.tenant_id == tenant_id,
            PartnerWebhookEndpoint.status == "active",
        )
        .with_for_update()
    )
    if active is not None and not supersede:
        raise EndpointError("active_endpoint_exists_use_supersede")
    if active is None and supersede:
        raise EndpointError("no_active_endpoint_to_supersede")
    endpoint = PartnerWebhookEndpoint(
        id=uuid4(),
        tenant_id=tenant_id,
        url=url,
        secret_ref=secret_ref,
        secret_ref_next=secret_ref_next,
        events=list(events),
        facts_profile=facts_profile,
        status="active",
        events_since=active.events_since if active is not None else now,
        supersedes_endpoint_id=active.id if active is not None else None,
        created_by=operator_reference,
        reason=reason,
        created_at=now,
        disabled_at=None,
    )
    result: dict[str, Any] = {
        "environment": environment,
        "apply": apply,
        "before": view(active) if active is not None else None,
        "after": view(endpoint),
        "secret_values_checked": False,
    }
    if not apply:
        return result
    moved = 0
    if active is not None:
        active.status, active.disabled_at = "disabled", now
        await session.flush()
    session.add(endpoint)
    await session.flush()
    if active is not None:
        moved = (
            await session.execute(
                update(PartnerWebhookEvent)
                .where(
                    PartnerWebhookEvent.endpoint_id == active.id,
                    PartnerWebhookEvent.status.in_(("pending", "dead_letter")),
                )
                .values(endpoint_id=endpoint.id)
            )
        ).rowcount or 0
    await _audit(
        session,
        tenant_id=tenant_id,
        action="partner_events.endpoint_registered",
        resource_type=RESOURCE_ENDPOINT,
        resource_id=endpoint.id,
        payload={
            "endpoint_id": str(endpoint.id),
            "supersedes_endpoint_id": str(active.id) if active is not None else None,
            "url_host": mask_url(url),
            "secret_ref": secret_ref,
            "secret_ref_next": secret_ref_next,
            "events": list(events),
            "facts_profile": facts_profile,
            "events_moved": int(moved),
            "operator_reference": operator_reference,
        },
        reason=reason,
        now=now,
    )
    result["events_moved"] = int(moved)
    result["applied"] = True
    return result


async def disable(
    session: Any,
    *,
    endpoint_id: UUID,
    reason: str,
    operator_reference: str,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    """Stop an endpoint. Its undelivered events are dropped (they would never be sent)."""
    from sqlalchemy import func, select, update

    from ac_platform.partner_events.models import PartnerWebhookEndpoint, PartnerWebhookEvent

    reason = _text(reason, "reason", 500)
    operator_reference = _text(operator_reference, "operator_reference", 160)
    endpoint = await session.scalar(
        select(PartnerWebhookEndpoint)
        .where(PartnerWebhookEndpoint.id == endpoint_id)
        .with_for_update()
    )
    if endpoint is None:
        raise EndpointError("endpoint_missing")
    if endpoint.status != "active":
        raise EndpointError("endpoint_not_active")
    pending = int(
        await session.scalar(
            select(func.count())
            .select_from(PartnerWebhookEvent)
            .where(
                PartnerWebhookEvent.endpoint_id == endpoint_id,
                PartnerWebhookEvent.status.in_(("pending", "dead_letter")),
            )
        )
        or 0
    )
    result: dict[str, Any] = {
        "apply": apply,
        "before": view(endpoint),
        "undelivered_events_to_drop": pending,
    }
    if not apply:
        return result
    endpoint.status, endpoint.disabled_at = "disabled", now
    await session.execute(
        update(PartnerWebhookEvent)
        .where(
            PartnerWebhookEvent.endpoint_id == endpoint_id,
            PartnerWebhookEvent.status.in_(("pending", "dead_letter")),
        )
        .values(status="dropped", leased_until=None, last_error_code="endpoint_disabled")
    )
    await session.flush()
    await _audit(
        session,
        tenant_id=endpoint.tenant_id,
        action="partner_events.endpoint_disabled",
        resource_type=RESOURCE_ENDPOINT,
        resource_id=endpoint.id,
        payload={
            "endpoint_id": str(endpoint.id),
            "events_dropped": pending,
            "operator_reference": operator_reference,
        },
        reason=reason,
        now=now,
    )
    result["after"] = view(endpoint)
    result["applied"] = True
    return result


async def list_endpoints(session: Any) -> list[dict[str, Any]]:
    from sqlalchemy import func, select

    from ac_platform.partner_events.models import PartnerWebhookEndpoint, PartnerWebhookEvent

    endpoints = (
        await session.scalars(
            select(PartnerWebhookEndpoint).order_by(
                PartnerWebhookEndpoint.tenant_id, PartnerWebhookEndpoint.created_at
            )
        )
    ).all()
    counts: dict[tuple[UUID, str], int] = {
        (row.endpoint_id, row.status): int(row.count)
        for row in (
            await session.execute(
                select(
                    PartnerWebhookEvent.endpoint_id,
                    PartnerWebhookEvent.status,
                    func.count().label("count"),
                ).group_by(PartnerWebhookEvent.endpoint_id, PartnerWebhookEvent.status)
            )
        )
    }
    listed = []
    for endpoint in endpoints:
        item = view(endpoint)
        item["events"] = {
            status: counts.get((endpoint.id, status), 0)
            for status in ("pending", "delivered", "dead_letter", "dropped")
        }
        listed.append(item)
    return listed


async def replay(
    session: Any,
    *,
    event_id: UUID,
    reason: str,
    operator_reference: str,
    apply: bool,
    now: datetime,
) -> dict[str, Any]:
    """A dead-lettered event goes back to pending with a fresh 25-attempt budget."""
    from sqlalchemy import select

    from ac_platform.partner_events.models import PartnerWebhookEndpoint, PartnerWebhookEvent

    reason = _text(reason, "reason", 500)
    operator_reference = _text(operator_reference, "operator_reference", 160)
    event = await session.scalar(
        select(PartnerWebhookEvent).where(PartnerWebhookEvent.id == event_id).with_for_update()
    )
    if event is None:
        raise EndpointError("event_missing")
    if event.status != "dead_letter" or event.payload is None:
        raise EndpointError("event_not_dead_letter")
    endpoint = await session.get(PartnerWebhookEndpoint, event.endpoint_id)
    if endpoint is None or endpoint.status != "active":
        raise EndpointError("endpoint_not_active")
    before = {"status": event.status, "attempts": event.attempts}
    result: dict[str, Any] = {
        "apply": apply,
        "event_id": str(event.id),
        "endpoint": mask_url(endpoint.url),
        "before": before,
        "after": {"status": "pending", "attempts": event.attempts, "budget": 25},
    }
    if not apply:
        return result
    event.status = "pending"
    event.replayed_attempts = event.attempts
    event.next_attempt_at = now
    event.leased_until = None
    await session.flush()
    await _audit(
        session,
        tenant_id=event.tenant_id,
        action="partner_events.event_replayed",
        resource_type=RESOURCE_EVENT,
        resource_id=event.id,
        payload={
            "event_id": str(event.id),
            "endpoint_id": str(event.endpoint_id),
            "attempts_before": before["attempts"],
            "operator_reference": operator_reference,
        },
        reason=reason,
        now=now,
    )
    result["applied"] = True
    return result


def fictional_test_body(tenant_id: UUID, now: datetime) -> dict[str, Any]:
    """A fictional ``sx.test.v1`` event: no customer data, only for checking signatures."""
    from ac_platform.partner_events.payload import iso, ref

    return {
        "schema": "sx.test.v1",
        "event_id": str(uuid4()),
        "event_type": "test",
        "occurred_at": iso(now),
        "tenant_ref": ref("ten", tenant_id),
        "message": "Fictional test event from Sales X-Ray. It carries no customer data.",
    }


async def record_test_event(
    session: Any,
    *,
    endpoint: Any,
    event_id: str,
    http_status: int | None,
    error_code: str | None,
    duration_ms: int,
    now: datetime,
) -> None:
    await _audit(
        session,
        tenant_id=endpoint.tenant_id,
        action="partner_events.test_event_sent",
        resource_type=RESOURCE_ENDPOINT,
        resource_id=endpoint.id,
        payload={
            "endpoint_id": str(endpoint.id),
            "test_event_id": event_id,
            "http_status": http_status,
            "error_code": error_code,
            "duration_ms": duration_ms,
        },
        reason="Signed sx.test.v1 event, fictional data",
        now=now,
    )
