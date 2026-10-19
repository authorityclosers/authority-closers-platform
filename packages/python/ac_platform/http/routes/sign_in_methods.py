"""Settings -> Security -> Sign-in methods on the Sales Xray account session.

- GET  /v1/me/sign-in-methods                     what can sign this account in, and
                                                  which providers can be connected
- POST /v1/me/sign-in-methods/{provider}/remove   remove Google, Apple or Facebook

Removal needs a session started in the last 10 minutes and never takes the last way
in. It writes identity.provider_removed.v1 (provider, account, time, client address)
and emails the account (identity/provider_link_email.py). Staff keys can't remove.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import AuthenticatedTransaction, require_safe_origin
from ac_platform.http.rate_limits import client_identity
from ac_platform.http.routes import RouteContext
from ac_platform.identity.provider_link_email import (
    PROVIDER_LABELS,
    PROVIDER_REMOVED_ACTION,
    enqueue_provider_notice,
)
from ac_platform.identity.sign_in_methods import (
    FRESH_SIGN_IN,
    SignInMethodError,
    remove_provider,
    session_is_fresh,
    sign_in_methods,
)
from ac_platform.kernel.errors import DomainError

ORDER = 1265
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
WORDS = {
    "fresh_sign_in": "For your safety, sign in again, then remove it within 10 minutes.",
    "last_method": "This is your only way to sign in, so it can't be removed.",
    "not_found": "That sign-in method isn't on your account.",
}


def install(app: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/me/sign-in-methods", tags=["identity"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    @asynccontextmanager
    async def account(
        request: Request, response: Response, *, write: bool = False
    ) -> AsyncIterator[AuthenticatedTransaction]:
        response.headers.update(PRIVATE)
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Sign-in methods are unavailable here.", headers=PRIVATE)
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
                if write and getattr(request.state, "staff_key", False) is True:
                    raise HTTPException(
                        403, "Sign in to change your sign-in methods.", headers=PRIVATE
                    )
                yield auth
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    @router.get("")
    async def listing(request: Request, response: Response) -> dict[str, Any]:
        async with account(request, response) as auth:
            actor = auth.resolved.actor
            methods = await sign_in_methods(auth.database, actor.person_id)
            fresh = await session_is_fresh(auth.database, actor.session_id, datetime.now(UTC))
            configured: frozenset[str] = getattr(
                request.app.state, "sign_in_provider_names", frozenset()
            )
            linked = {method.kind for method in methods}
            return {
                "methods": [
                    {
                        "kind": method.kind,
                        "added_at": method.added_at.isoformat() if method.added_at else None,
                        "last_used_at": (
                            method.last_used_at.isoformat() if method.last_used_at else None
                        ),
                        "removable": method.removable,
                    }
                    for method in methods
                ],
                # Settings -> Connect: configured here and not yet on the account.
                "providers": {
                    provider: {
                        "linked": provider in linked,
                        "can_connect": provider in configured and provider not in linked,
                    }
                    for provider in ("google", "apple", "facebook")
                },
                "fresh_sign_in": fresh,
                "fresh_minutes": int(FRESH_SIGN_IN.total_seconds() // 60),
            }

    @router.post("/{provider}/remove")
    async def remove(
        request: Request,
        response: Response,
        provider: Literal["google", "apple", "facebook"],
    ) -> dict[str, Any]:
        async with account(request, response, write=True) as auth:
            actor = auth.resolved.actor
            tenant_id = actor.tenant_id or settings.public_learner_tenant_id
            if tenant_id is None:
                raise HTTPException(503, "Sign-in methods are unavailable here.", headers=PRIVATE)
            now = datetime.now(UTC)
            try:
                await remove_provider(
                    auth.database,
                    person_id=actor.person_id,
                    session_id=actor.session_id,
                    provider=provider,
                    now=now,
                )
            except SignInMethodError as error:
                status = 404 if error.code == "not_found" else 409
                raise HTTPException(
                    status,
                    {"code": error.code, "message": WORDS[error.code]},
                    headers=PRIVATE,
                ) from None
            event = await AuditRepository(auth.database).append(
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action=PROVIDER_REMOVED_ACTION,
                resource_type="person",
                resource_id=actor.person_id,
                payload={
                    "provider": provider,
                    "ip_address": client_identity(
                        request.scope,
                        trusted_proxy_addresses=settings.rate_limit_trusted_proxy_addresses,
                    ),
                },
                reason=f"The person removed {PROVIDER_LABELS[provider]} sign-in.",
                now=now,
            )
            await enqueue_provider_notice(auth.database, event)
            return {"removed": provider}

    app.include_router(router)
