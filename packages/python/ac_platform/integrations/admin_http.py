"""Platform admins see every organisation's integrations (Admin host, operations only).

- GET  /v1/admin/integrations                        counts, then every organisation's
                                                     keys, webhook and connected apps
- POST /v1/admin/integrations/keys/{id}/revoke       a key, at once
- POST /v1/admin/integrations/webhooks/{id}/disable  a webhook, at once

Each change is audited in that organisation's own chain and answers with the updated
row. No key or secret is ever returned: keys by prefix, webhooks by scheme and host.
The reads and changes are plain functions (``overview``, ``revoke_key``,
``disable_webhook``) so they are tested without the Admin sign-in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.conversation_intelligence.application import (
    ConversationApplication,
    ConversationError,
)
from ac_platform.conversation_intelligence.provider_admin import ConversationProviderAdmin
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    require_admin_surface,
    require_safe_origin,
)
from ac_platform.http.routes import RouteContext
from ac_platform.identity.models import Person
from ac_platform.integrations import keys, oauth, sealed
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.kernel.errors import DomainError
from ac_platform.organisations.workspace_kinds import classify_workspaces
from ac_platform.partner_events import endpoints as partner
from ac_platform.partner_events.models import (
    PartnerLeadAttempt,
    PartnerLeadEvent,
    PartnerWebhookAttempt,
    PartnerWebhookEndpoint,
    PartnerWebhookEvent,
)

PRIVATE = {"Cache-Control": "private, no-store"}
UNUSED_AFTER = timedelta(days=30)
SCHEMA = "sx-integrations-admin/2"


def _host(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _people(database: AsyncSession, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    rows = await database.execute(
        select(Person.id, Person.display_name, Person.email).where(Person.id.in_(ids))
    )
    return {row.id: row.display_name or row.email or "Unknown" for row in rows}


def _unused(row: Any, now: datetime) -> bool:
    return bool((row.last_used_at or row.created_at) < now - UNUSED_AFTER)


def _key_row(row: Any, now: datetime, names: dict[UUID, str]) -> dict[str, Any]:
    return {
        **keys.view(row, now),
        "created_by": {
            "person_id": str(row.created_by_person_id),
            "label": names.get(row.created_by_person_id, "Unknown"),
        },
        "revoked_by": (
            {
                "person_id": str(row.revoked_by_person_id),
                "label": names.get(row.revoked_by_person_id, "Unknown"),
            }
            if row.revoked_by_person_id
            else None
        ),
        "unused_30d": keys.state(row, now) == "active" and _unused(row, now),
    }


async def _delivery_health(
    database: AsyncSession, endpoint_ids: list[UUID], now: datetime
) -> dict[UUID, dict[str, Any]]:
    """Per endpoint: last delivery, the last answer, failed attempts in 24 hours."""
    health: dict[UUID, dict[str, Any]] = {
        endpoint_id: {"last_delivery_at": None, "last_status": None, "failures_24h": 0}
        for endpoint_id in endpoint_ids
    }
    if not endpoint_ids:
        return health
    last_try: dict[UUID, datetime] = {}
    since = now - timedelta(hours=24)
    pairs: tuple[tuple[Any, Any], ...] = (
        (PartnerWebhookEvent, PartnerWebhookAttempt),
        (PartnerLeadEvent, PartnerLeadAttempt),
    )
    for event, attempt in pairs:
        delivered = await database.execute(
            select(event.endpoint_id, func.max(event.delivered_at))
            .where(event.endpoint_id.in_(endpoint_ids))
            .group_by(event.endpoint_id)
        )
        for endpoint_id, at in delivered:
            current = health[endpoint_id]["last_delivery_at"]
            if at is not None and (current is None or at > current):
                health[endpoint_id]["last_delivery_at"] = at
        latest = await database.execute(
            select(
                event.endpoint_id,
                func.max(attempt.started_at),
            )
            .join(attempt, attempt.event_id == event.id)
            .where(event.endpoint_id.in_(endpoint_ids))
            .group_by(event.endpoint_id)
        )
        for endpoint_id, started in latest:
            if started is None or (endpoint_id in last_try and last_try[endpoint_id] >= started):
                continue
            last_try[endpoint_id] = started
            answer = (
                await database.execute(
                    select(attempt.http_status, attempt.error_code)
                    .join(event, event.id == attempt.event_id)
                    .where(event.endpoint_id == endpoint_id, attempt.started_at == started)
                    .limit(1)
                )
            ).first()
            if answer is not None:
                health[endpoint_id]["last_status"] = (
                    answer.http_status if answer.http_status is not None else answer.error_code
                )
        failed = await database.execute(
            select(event.endpoint_id, func.count())
            .join(attempt, attempt.event_id == event.id)
            .where(
                event.endpoint_id.in_(endpoint_ids),
                attempt.started_at >= since,
                (attempt.http_status.is_(None))
                | (attempt.http_status < 200)
                | (attempt.http_status >= 300),
            )
            .group_by(event.endpoint_id)
        )
        for endpoint_id, count in failed:
            health[endpoint_id]["failures_24h"] += int(count)
    for entry in health.values():
        entry["last_delivery_at"] = _iso(entry["last_delivery_at"])
    return health


def _webhook_row(endpoint: Any, health: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(endpoint.id),
        "host": _host(endpoint.url),
        "events": list(endpoint.events),
        "status": endpoint.status,
        "managed_in_app": sealed.id_from_ref(endpoint.secret_ref) is not None,
        "created_at": endpoint.created_at.isoformat(),
        "disabled_at": _iso(endpoint.disabled_at),
        **health,
    }


async def overview(
    database: AsyncSession,
    *,
    operations_tenant_id: UUID | None,
    personal_tenant_id: UUID | None,
    environment: str,
    now: datetime,
) -> dict[str, Any]:
    key_rows = (
        await database.scalars(
            select(IntegrationApiKey).order_by(IntegrationApiKey.created_at.desc())
        )
    ).all()
    endpoints = (
        await database.scalars(
            select(PartnerWebhookEndpoint).order_by(PartnerWebhookEndpoint.created_at.desc())
        )
    ).all()
    grants: list[dict[str, Any]] = await database.run_sync(
        lambda session: oauth.all_connections(session.connection())
    )
    names = await _people(
        database,
        {row.created_by_person_id for row in key_rows}
        | {row.revoked_by_person_id for row in key_rows if row.revoked_by_person_id},
    )
    health = await _delivery_health(database, [endpoint.id for endpoint in endpoints], now)
    tenant_ids = (
        {row.tenant_id for row in key_rows}
        | {endpoint.tenant_id for endpoint in endpoints}
        | {UUID(grant["tenant_id"]) for grant in grants}
    )
    workspaces = await classify_workspaces(
        database,
        operations_tenant_id=operations_tenant_id,
        personal_tenant_id=personal_tenant_id,
        tenant_ids=tenant_ids,
    )
    organisations: dict[UUID, dict[str, Any]] = {
        tenant_id: {
            "id": str(tenant_id),
            "name": workspaces[tenant_id].name if tenant_id in workspaces else None,
            "kind": workspaces[tenant_id].kind if tenant_id in workspaces else "other",
            "keys": [],
            "webhooks": [],
            "connections": [],
        }
        for tenant_id in tenant_ids
    }
    for row in key_rows:
        organisations[row.tenant_id]["keys"].append(_key_row(row, now, names))
    for endpoint in endpoints:
        organisations[endpoint.tenant_id]["webhooks"].append(
            _webhook_row(endpoint, health[endpoint.id])
        )
    for grant in grants:
        organisations[UUID(grant["tenant_id"])]["connections"].append(grant)
    active_keys = [row for row in key_rows if keys.state(row, now) == "active"]
    active_hooks = [endpoint for endpoint in endpoints if endpoint.status == "active"]
    return {
        "schema": SCHEMA,
        "environment": environment,
        "counts": {
            "active_keys": len(active_keys),
            "keys_unused_30d": sum(1 for row in active_keys if _unused(row, now)),
            "active_webhooks": len(active_hooks),
            "webhooks_failing": sum(
                1 for endpoint in active_hooks if health[endpoint.id]["failures_24h"] > 0
            ),
            "connected_apps": sum(1 for grant in grants if grant["revoked_at"] is None),
        },
        "organisations": sorted(
            organisations.values(), key=lambda item: (item["name"] or "", item["id"])
        ),
    }


async def revoke_key(
    database: AsyncSession, *, key_id: UUID, actor: Any, now: datetime
) -> dict[str, Any]:
    revoked, changed = await database.run_sync(
        lambda session: keys.revoke(
            session.connection(), tenant_id=None, key_id=key_id, person_id=actor.person_id, now=now
        )
    )
    row = await database.get(IntegrationApiKey, key_id, populate_existing=True)
    assert row is not None
    if changed:
        # In the organisation's own chain, so its owners see who revoked it.
        await AuditRepository(database).append(
            tenant_id=row.tenant_id,
            actor_person_id=actor.person_id,
            action="integration.api_key_revoked",
            resource_type="integration_api_key",
            resource_id=revoked["id"],
            payload={"name": revoked["name"], "prefix": revoked["prefix"], "by": "platform"},
            session_id=actor.session_id,
        )
    names = await _people(database, {row.created_by_person_id, actor.person_id})
    return _key_row(row, now, names)


async def disable_webhook(
    database: AsyncSession, *, endpoint_id: UUID, actor: Any, now: datetime
) -> dict[str, Any]:
    endpoint = await database.get(PartnerWebhookEndpoint, endpoint_id)
    if endpoint is None:
        raise IntegrationError("not_found", 404)
    if endpoint.status == "active":
        await partner.disable(
            database,
            endpoint_id=endpoint_id,
            reason="Admin -> Integrations",
            operator_reference=f"admin:person:{actor.person_id}",
            apply=True,
            now=now,
        )
        for ref in (endpoint.secret_ref, endpoint.secret_ref_next):
            found = sealed.id_from_ref(ref)
            if found is None:
                continue

            def retire(sync: Any, secret_id: UUID = found) -> None:
                sealed.retire(sync.connection(), secret_id, by=f"admin:{actor.person_id}", now=now)

            await database.run_sync(retire)
        await AuditRepository(database).append(
            tenant_id=endpoint.tenant_id,
            actor_person_id=actor.person_id,
            action="integration.webhook_disabled",
            resource_type="partner_webhook_endpoint",
            resource_id=str(endpoint_id),
            payload={"host": _host(endpoint.url), "by": "platform"},
            session_id=actor.session_id,
        )
    fresh = await database.get(PartnerWebhookEndpoint, endpoint_id, populate_existing=True)
    assert fresh is not None
    health = await _delivery_health(database, [endpoint_id], now)
    return _webhook_row(fresh, health[endpoint_id])


def install_integrations_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(prefix="/v1/admin/integrations", tags=["integrations-admin"])

    async def admit(
        request: Request, response: Response, auth: AuthenticatedTransaction, *, write: bool
    ) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(403, "Use this Admin page to continue.") from None
        if request.query_params:
            raise HTTPException(422, "This view takes no filters.")
        actor = auth.resolved.actor
        if (
            settings.operations_tenant_id is None
            or actor.tenant_id != settings.operations_tenant_id
        ):
            raise HTTPException(403, "Use the AC operations workspace.")
        try:
            await ConversationProviderAdmin(ConversationApplication(auth.database)).admit(actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None
        return actor

    @router.get("")
    async def read(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        await admit(request, response, auth, write=False)
        return await overview(
            auth.database,
            operations_tenant_id=settings.operations_tenant_id,
            personal_tenant_id=settings.public_learner_tenant_id,
            environment=settings.environment,
            now=datetime.now(UTC),
        )

    @router.post("/keys/{key_id}/revoke")
    async def revoke(
        key_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        actor = await admit(request, response, auth, write=True)
        try:
            return await revoke_key(
                auth.database, key_id=key_id, actor=actor, now=datetime.now(UTC)
            )
        except IntegrationError:
            raise HTTPException(404, "That key is not here.") from None

    @router.post("/webhooks/{endpoint_id}/disable")
    async def disable(
        endpoint_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        actor = await admit(request, response, auth, write=True)
        try:
            return await disable_webhook(
                auth.database, endpoint_id=endpoint_id, actor=actor, now=datetime.now(UTC)
            )
        except IntegrationError:
            raise HTTPException(404, "That webhook is not here.") from None

    application.include_router(router)
