"""Platform admins see every organisation's integrations (Admin host, operations only).

- GET  /v1/admin/integrations                  every organisation's keys and webhook
- POST /v1/admin/integrations/keys/{id}/revoke a key, at once (audited in that
                                               organisation's chain)

No key or secret is ever returned: keys by prefix, webhooks by scheme and host.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import select

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
from ac_platform.integrations import keys
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationApiKey
from ac_platform.kernel.errors import DomainError
from ac_platform.partner_events.models import PartnerWebhookEndpoint
from ac_platform.tenancy.models import Organisation, Tenant

PRIVATE = {"Cache-Control": "private, no-store"}


def _host(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}" + (f":{parts.port}" if parts.port else "")


def install_integrations_admin_http(application: FastAPI, ctx: RouteContext) -> None:
    settings = ctx.settings
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(prefix="/v1/admin/integrations", tags=["integrations-admin"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> Any:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
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
    async def overview(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        await admit(request, response, auth)
        now = datetime.now(UTC)
        names: dict[UUID, str] = {
            row.tenant_id: row.name
            for row in (
                await auth.database.execute(
                    select(Organisation.tenant_id, Tenant.name).join(
                        Tenant, Tenant.id == Organisation.tenant_id
                    )
                )
            ).all()
        }
        organisations: dict[UUID, dict[str, Any]] = {}

        def entry(tenant_id: UUID) -> dict[str, Any]:
            return organisations.setdefault(
                tenant_id,
                {
                    "id": str(tenant_id),
                    "name": names.get(tenant_id),
                    "keys": [],
                    "webhooks": [],
                },
            )

        for row in (
            await auth.database.scalars(
                select(IntegrationApiKey).order_by(IntegrationApiKey.created_at.desc())
            )
        ).all():
            entry(row.tenant_id)["keys"].append(keys.view(row, now))
        for endpoint in (
            await auth.database.scalars(
                select(PartnerWebhookEndpoint).order_by(PartnerWebhookEndpoint.created_at.desc())
            )
        ).all():
            entry(endpoint.tenant_id)["webhooks"].append(
                {
                    "id": str(endpoint.id),
                    "host": _host(endpoint.url),
                    "events": list(endpoint.events),
                    "status": endpoint.status,
                    "managed_in_app": endpoint.secret_ref.startswith(
                        "AC_PARTNER_WEBHOOK_SECRET__SEALED_"
                    ),
                    "created_at": endpoint.created_at.isoformat(),
                    "disabled_at": endpoint.disabled_at.isoformat()
                    if endpoint.disabled_at
                    else None,
                }
            )
        return {
            "schema": "sx-integrations-admin/1",
            "environment": settings.environment,
            "organisations": sorted(
                organisations.values(), key=lambda item: (item["name"] or "", item["id"])
            ),
        }

    @router.post("/keys/{key_id}/revoke")
    async def revoke(
        key_id: UUID,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use this Admin page to continue.") from None
        actor = await admit(request, response, auth)
        now = datetime.now(UTC)
        try:
            revoked, changed = await auth.database.run_sync(
                lambda session: keys.revoke(
                    session.connection(),
                    tenant_id=None,
                    key_id=key_id,
                    person_id=actor.person_id,
                    now=now,
                )
            )
        except IntegrationError as error:
            raise HTTPException(error.status, "That key is not here.") from None
        tenant_id = None
        if changed:
            tenant_id = await auth.database.scalar(
                select(IntegrationApiKey.tenant_id).where(IntegrationApiKey.id == key_id)
            )
        if tenant_id is not None:
            # In the organisation's own chain, so its owners see who revoked it.
            await AuditRepository(auth.database).append(
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                action="integration.api_key_revoked",
                resource_type="integration_api_key",
                resource_id=revoked["id"],
                payload={"name": revoked["name"], "prefix": revoked["prefix"], "by": "platform"},
                session_id=actor.session_id,
            )
        return revoked

    application.include_router(router)
