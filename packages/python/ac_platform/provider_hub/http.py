"""Admin's Providers hub read.

- GET /v1/admin/providers/hub[?provider=<id>]: every provider with what it is for, whether
  the pipeline can call it and how many models it offers; with ``provider``, that one's
  models (context, inputs, structured output, list prices, the stages it can run here).
- GET /v1/admin/providers/health: each provider's spend in this environment (today, this
  month, 30 days) and its failures (last 24 hours, 7 days, the latest in plain words).
- GET /v1/admin/providers/keys: which providers have a key here (last four characters, the
  last test), and whether this environment can seal keys at all.
- POST /v1/admin/providers/{provider}/key {key}: seal a key here, write-only (browser, a
  sign-in within 10 minutes); /key/remove retires it; /key/test makes the free check.

Operations admins (the Sales X-Ray control accounts) only, on the Admin host. It reads
OpenRouter's public catalogue (no key). A provider key arrives only in the add request, is
sealed at once (``keys.py``) and never comes back in any answer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from ac_platform.ai_spend import policy
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
from ac_platform.provider_hub import health, keys
from ac_platform.provider_hub.catalogue import BY_ID
from ac_platform.provider_hub.models import CATALOGUE, Fetch, hub_view

PRIVATE = {"Cache-Control": "private, no-store"}


class KeyRequest(BaseModel):
    """The key itself; checked in ``keys.py`` so that no error ever repeats it."""

    model_config = ConfigDict(extra="forbid")

    key: str


async def fetch_json(url: str) -> Any:
    """A public JSON document (no credentials, no redirects, 15 seconds at most)."""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        answer = await client.get(url, headers={"Accept": "application/json"})
        answer.raise_for_status()
        return answer.json()


def install_provider_hub_http(
    application: FastAPI, ctx: RouteContext, *, fetch: Fetch = fetch_json
) -> None:
    settings = ctx.settings
    environment = policy.environment_name(settings.environment)
    dependency = Depends(ctx.require_actor, scope="function")
    router = APIRouter(tags=["provider-hub"])

    async def admit(request: Request, response: Response, auth: AuthenticatedTransaction) -> None:
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
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

    @router.get("/v1/admin/providers/hub")
    async def hub(
        request: Request,
        response: Response,
        provider: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Providers, and one provider's models when asked; list prices, never a key."""
        await admit(request, response, auth)
        if set(request.query_params) - {"provider"}:
            raise HTTPException(422, "The Providers hub takes only provider.")
        if provider is not None and provider not in BY_ID:
            raise HTTPException(404, "There is no such provider in the catalogue.")
        await CATALOGUE.read(fetch)
        return hub_view(
            CATALOGUE.models,
            fetched_at=CATALOGUE.fetched_at,
            problem=CATALOGUE.problem,
            selected=provider,
            listed={name: ids for name, (_, ids) in keys.LISTED.items()},
        )

    @router.get("/v1/admin/providers/health")
    async def provider_health(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Each provider's spend and failures here; counts and codes, never content."""
        await admit(request, response, auth)
        if request.query_params:
            raise HTTPException(422, "Provider health takes no parameters.")
        now = datetime.now(UTC)
        result: dict[str, Any] = await auth.database.run_sync(
            lambda sync: health.read(sync.connection(), environment, now)
        )
        return result

    def browser_only(request: Request) -> None:
        if getattr(request.state, "staff_key", False):
            raise HTTPException(403, "Provider keys are added in the browser.")
        require_safe_origin(request, settings)

    def known(provider: str) -> str:
        if provider not in BY_ID:
            raise HTTPException(404, "There is no such provider in the catalogue.")
        return provider

    @router.get("/v1/admin/providers/keys")
    async def provider_keys(
        request: Request, response: Response, auth: AuthenticatedTransaction = dependency
    ) -> dict[str, Any]:
        """Which providers have a key here; the last four characters, never a key."""
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        if request.query_params:
            raise HTTPException(422, "Provider keys take no parameters.")
        try:
            return await keys.ProviderKeys(auth.database, settings).view(auth.resolved.actor)
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/providers/{provider}/key", status_code=201)
    async def add_key(
        provider: str,
        body: KeyRequest,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Seal a provider's key for this environment; it is never shown again."""
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        browser_only(request)
        try:
            return await keys.ProviderKeys(auth.database, settings).add(
                auth.resolved.actor, known(provider), body.key, now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/providers/{provider}/key/remove")
    async def remove_key(
        provider: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """Retire a provider's key here."""
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        browser_only(request)
        try:
            return await keys.ProviderKeys(auth.database, settings).remove(
                auth.resolved.actor, known(provider), now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    @router.post("/v1/admin/providers/{provider}/key/test")
    async def test_key(
        provider: str,
        request: Request,
        response: Response,
        auth: AuthenticatedTransaction = dependency,
    ) -> dict[str, Any]:
        """The provider's free read with its key: works or not, and how many models."""
        require_admin_surface(request, settings)
        response.headers.update(PRIVATE)
        browser_only(request)
        try:
            return await keys.ProviderKeys(auth.database, settings).test(
                auth.resolved.actor, known(provider), now=datetime.now(UTC)
            )
        except ConversationError as error:
            raise HTTPException(error.status, str(error)) from None

    application.include_router(router)
