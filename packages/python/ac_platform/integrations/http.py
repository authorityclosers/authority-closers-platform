"""Settings -> Integrations on the Sales X-Ray account session (organisation owners, admins).

- GET  /v1/sales-xray/integrations                     keys, scopes, the API address
- POST /v1/sales-xray/integrations/keys                a new key, shown once
- POST /v1/sales-xray/integrations/keys/{key_id}/revoke
- PUT  /v1/sales-xray/integrations/webhook              add or change; a new secret once
- POST /v1/sales-xray/integrations/webhook/rotate       a second secret, shown once
- POST /v1/sales-xray/integrations/webhook/rotate/finish  the new secret alone
- POST /v1/sales-xray/integrations/webhook/test         a signed fictional event, now
- POST /v1/sales-xray/integrations/webhook/disable
- GET  /v1/sales-xray/integrations/webhook/deliveries   the last 50 events' states
- POST /v1/sales-xray/integrations/webhook/deliveries/{event_id}/retry  a dead letter

Only an active owner or admin of a registered organisation may use these, checked
against the live membership on every request. Every create and revoke is an audit
event in the organisation's chain (name, scopes and prefix; never the key).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import keys, oauth, scopes, sealed, webhooks
from ac_platform.integrations.errors import IntegrationError
from ac_platform.integrations.models import IntegrationOAuthGrant
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Organisation

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
MANAGER_ROLES = frozenset({"owner", "admin"})

WORDS = {
    "name": "Give the key a name of up to 80 characters.",
    "scopes": "Choose at least one permission.",
    "expiry": "Choose when the key expires.",
    "too_many_keys": "This organisation has 25 active keys. Revoke one first.",
    "not_found": "That is not in this organisation.",
    "url": "Use an https:// address your app answers on.",
    "events": "Choose at least one event.",
    "facts_profile": "Choose a facts profile from the list.",
    "webhook": "Check the webhook details.",
    "no_webhook": "Add a webhook first.",
    "rotation_open": "Finish the open secret change first.",
    "no_rotation": "There is no secret change to finish.",
    "secret_not_in_app": (
        "AC set this webhook up by hand. Save it here to get a secret you can test with."
    ),
    "not_dead_letter": "Only an event that stopped retrying can be sent again.",
    "not_ready": "Webhooks are not switched on here yet.",
    "redirect_uris": (
        "Use up to 5 https:// return addresses, or http://127.0.0.1 for an app on your computer."
    ),
}


class WebhookCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=8, max_length=2048)
    events: list[str] = Field(min_length=1, max_length=8)
    facts_profile: str | None = Field(default=None, max_length=64)


class AppCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    redirect_uris: list[str] = Field(min_length=1, max_length=5)
    confidential: bool = True


class KeyCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(min_length=1, max_length=len(scopes.SCOPES))
    expires_days: Literal[30, 90, 365] | None = None


def install_integrations_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/sales-xray/integrations", tags=["integrations"])
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    settings = ctx.settings

    def api_base() -> str | None:
        app_url = settings.sales_xray_app_url
        return None if app_url is None else f"{str(app_url).rstrip('/')}/v1/api"

    @asynccontextmanager
    async def manager(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[Any]:
        """The signed-in owner or admin of the selected registered organisation."""
        response.headers.update(PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Integrations are unavailable here.", headers=PRIVATE)
        if any(True for _ in request.query_params):
            raise HTTPException(422, "Remove the extra address options.", headers=PRIVATE)
        if write:
            try:
                require_safe_origin(request, settings)
            except DomainError:
                raise HTTPException(
                    403, "Use this Sales Xray page to continue.", headers=PRIVATE
                ) from None
        try:
            async with asynccontextmanager(ctx.require_actor if write else read_actor)(
                request
            ) as auth:
                actor = auth.resolved.actor
                role = (
                    None
                    if actor.tenant_id is None
                    else await auth.database.scalar(
                        select(Membership.role)
                        .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
                        .where(
                            Membership.tenant_id == actor.tenant_id,
                            Membership.person_id == actor.person_id,
                            Membership.status == "active",
                            Membership.ended_at.is_(None),
                        )
                    )
                )
                if role not in MANAGER_ROLES:
                    raise HTTPException(
                        403,
                        "Only an owner or admin of an organisation can manage integrations.",
                        headers=PRIVATE,
                    )
                yield auth
        except IntegrationError as error:
            raise HTTPException(
                error.status, WORDS.get(error.code, "Check the details."), headers=PRIVATE
            ) from None
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    @router.get("")
    async def overview(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response) as auth:
            tenant_id = auth.resolved.actor.tenant_id
            now = datetime.now(UTC)
            listed = await auth.database.run_sync(
                lambda session: keys.listing(session.connection(), tenant_id, now)
            )
            return {
                "schema": "sx-integrations/1",
                "api_base": api_base(),
                "key_mode": keys.mode(settings.environment),
                "scopes": scopes.public(),
                "expiry_days": list(keys.EXPIRY_DAYS),
                "keys": listed,
                "webhooks_ready": sealed.load_key() is not None,
                "webhook_menu": webhooks.menu(),
                **await webhook_state(auth),
                "apps": await auth.database.run_sync(
                    lambda session: oauth.tenant_clients(session.connection(), tenant_id)
                ),
                "connections": await auth.database.run_sync(
                    lambda session: oauth.connections(session.connection(), tenant_id)
                ),
            }

    @router.post("/keys")
    async def create_key(
        command: KeyCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            now = datetime.now(UTC)
            key, created = await auth.database.run_sync(
                lambda session: keys.create(
                    session.connection(),
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    name=command.name,
                    scopes=list(command.scopes),
                    expires_days=command.expires_days,
                    environment=settings.environment,
                    now=now,
                )
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.api_key_created",
                resource_type="integration_api_key",
                resource_id=created["id"],
                payload={
                    "name": created["name"],
                    "prefix": created["prefix"],
                    "scopes": created["scopes"],
                    "expires_at": created["expires_at"],
                },
            )
            return {**created, "key": key}

    @router.post("/keys/{key_id}/revoke")
    async def revoke_key(key_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            now = datetime.now(UTC)
            revoked, changed = await auth.database.run_sync(
                lambda session: keys.revoke(
                    session.connection(),
                    tenant_id=actor.tenant_id,
                    key_id=key_id,
                    person_id=actor.person_id,
                    now=now,
                )
            )
            if changed:
                await AuditRepository(auth.database).append_for_actor(
                    actor,
                    action="integration.api_key_revoked",
                    resource_type="integration_api_key",
                    resource_id=revoked["id"],
                    payload={"name": revoked["name"], "prefix": revoked["prefix"]},
                )
            result: dict[str, Any] = revoked
            return result

    def seal_key() -> sealed.SealKey:
        key = sealed.load_key()
        if key is None:
            raise IntegrationError("not_ready", 503)
        return key

    async def webhook_state(auth: Any) -> dict[str, Any]:
        tenant_id = auth.resolved.actor.tenant_id
        current = await webhooks.active(auth.database, tenant_id)
        return {"webhook": await webhooks.view(auth.database, current)}

    @router.put("/webhook")
    async def save_webhook(
        command: WebhookCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            secret = await webhooks.save(
                auth.database,
                seal_key(),
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                url=command.url,
                events=list(command.events),
                facts_profile=command.facts_profile,
                environment=settings.environment,
                now=datetime.now(UTC),
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.webhook_saved",
                resource_type="partner_webhook_endpoint",
                payload={"events": list(command.events), "new_secret": secret is not None},
            )
            return {**await webhook_state(auth), "secret": secret}

    @router.post("/webhook/rotate")
    async def rotate_webhook(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            secret = await webhooks.rotate(
                auth.database,
                seal_key(),
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                environment=settings.environment,
                now=datetime.now(UTC),
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.webhook_secret_rotation_started",
                resource_type="partner_webhook_endpoint",
            )
            return {**await webhook_state(auth), "secret": secret}

    @router.post("/webhook/rotate/finish")
    async def finish_rotation(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            await webhooks.finish_rotation(
                auth.database,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                environment=settings.environment,
                now=datetime.now(UTC),
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.webhook_secret_rotation_finished",
                resource_type="partner_webhook_endpoint",
            )
            return await webhook_state(auth)

    @router.post("/webhook/test")
    async def test_webhook(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            result: dict[str, Any] = await webhooks.test(
                auth.database,
                seal_key(),
                tenant_id=auth.resolved.actor.tenant_id,
                environment=settings.environment,
                now=datetime.now(UTC),
                client=getattr(application.state, "integrations_http_client", None),
            )
            return result

    @router.post("/webhook/disable")
    async def disable_webhook(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            await webhooks.disable(
                auth.database,
                tenant_id=actor.tenant_id,
                person_id=actor.person_id,
                now=datetime.now(UTC),
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.webhook_disabled",
                resource_type="partner_webhook_endpoint",
            )
            return {"webhook": None}

    @router.get("/webhook/deliveries")
    async def webhook_deliveries(request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response) as auth:
            tenant_id = auth.resolved.actor.tenant_id
            return {"deliveries": await webhooks.deliveries(auth.database, tenant_id)}

    @router.post("/webhook/deliveries/{event_id}/retry")
    async def retry_delivery(
        event_id: UUID, request: Request, response: Response
    ) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            await webhooks.retry(
                auth.database,
                tenant_id=actor.tenant_id,
                event_id=event_id,
                person_id=actor.person_id,
                now=datetime.now(UTC),
            )
            return {"deliveries": await webhooks.deliveries(auth.database, actor.tenant_id)}

    @router.post("/apps")
    async def register_app(
        command: AppCommand, request: Request, response: Response
    ) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            made, secret = await auth.database.run_sync(
                lambda session: oauth.register_client(
                    session.connection(),
                    tenant_id=actor.tenant_id,
                    person_id=actor.person_id,
                    name=command.name,
                    redirect_uris=list(command.redirect_uris),
                    confidential=command.confidential,
                    now=datetime.now(UTC),
                )
            )
            await AuditRepository(auth.database).append_for_actor(
                actor,
                action="integration.app_registered",
                resource_type="integration_oauth_client",
                resource_id=made["client_id"],
                payload={"name": made["name"], "redirect_uris": made["redirect_uris"]},
            )
            return {**made, "client_secret": secret}

    @router.post("/apps/{app_id}/revoke")
    async def revoke_app(app_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor
            changed = await auth.database.run_sync(
                lambda session: oauth.revoke_client(
                    session.connection(),
                    tenant_id=actor.tenant_id,
                    client_row_id=app_id,
                    now=datetime.now(UTC),
                )
            )
            if changed:
                await AuditRepository(auth.database).append_for_actor(
                    actor,
                    action="integration.app_removed",
                    resource_type="integration_oauth_client",
                    resource_id=str(app_id),
                )
            return {
                "apps": await auth.database.run_sync(
                    lambda session: oauth.tenant_clients(session.connection(), actor.tenant_id)
                )
            }

    @router.post("/connections/{grant_id}/revoke")
    async def revoke_connection(
        grant_id: UUID, request: Request, response: Response
    ) -> dict[str, Any]:
        async with manager(request, response, write=True) as auth:
            actor = auth.resolved.actor

            def run(session: Any) -> bool:
                connection = session.connection()
                owned = connection.scalar(
                    select(IntegrationOAuthGrant.id).where(
                        IntegrationOAuthGrant.id == grant_id,
                        IntegrationOAuthGrant.tenant_id == actor.tenant_id,
                    )
                )
                if owned is None:
                    raise IntegrationError("not_found", 404)
                return oauth.revoke_grant(
                    connection,
                    grant_id=grant_id,
                    by=f"person:{actor.person_id}",
                    now=datetime.now(UTC),
                )

            if await auth.database.run_sync(run):
                await AuditRepository(auth.database).append_for_actor(
                    actor,
                    action="integration.app_disconnected",
                    resource_type="integration_oauth_grant",
                    resource_id=str(grant_id),
                )
            return {
                "connections": await auth.database.run_sync(
                    lambda session: oauth.connections(session.connection(), actor.tenant_id)
                )
            }

    application.include_router(router)
