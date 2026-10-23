"""Settings -> Security -> Delete account on the Sales Xray account session (Google Play).

- GET  /v1/me/account-deletion   what deleting this account would do, and what stops it
- POST /v1/me/account-deletion   ask for deletion: the account closes and is signed out
                                 everywhere (identity/account_deletion.py)

The ask needs the word DELETE typed and a session started in the last 10 minutes, as
removing a sign-in method does. Staff keys can't ask.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import (
    AuthenticatedTransaction,
    _delete_session_cookie,
    require_safe_origin,
)
from ac_platform.http.rate_limits import client_identity
from ac_platform.http.routes import RouteContext
from ac_platform.identity.account_deletion import (
    ACCOUNT_CLOSED_ACTION,
    CONFIRM_WORD,
    DeletionCheck,
    deletion_check,
    enqueue_account_closed_emails,
)
from ac_platform.identity.sign_in_methods import FRESH_SIGN_IN, session_is_fresh
from ac_platform.kernel.errors import DomainError

ORDER = 1266
PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
WORDS = {
    "confirm": f"Type {CONFIRM_WORD} to confirm.",
    "fresh_sign_in": "For your safety, sign in again, then delete your account within 10 minutes.",
    "staff": "This account has staff access. Ask the owner to close it.",
    "transfer_ownership_first": (
        "Make someone else the owner of your organisation first, so your team keeps it."
    ),
}


class DeleteAccountRequest(BaseModel):
    confirm: str = Field(max_length=40)
    reason: str | None = Field(default=None, max_length=500)


def _organisations(check: DeletionCheck) -> dict[str, list[dict[str, Any]]]:
    return {
        "transfer_first": [
            {"id": str(item.tenant_id), "name": item.name, "other_members": item.other_members}
            for item in check.transfer_first
        ],
        "closes_with_account": [
            {"id": str(item.tenant_id), "name": item.name} for item in check.closes_with_account
        ],
    }


def install(app: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/me/account-deletion", tags=["identity"])
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
            raise HTTPException(404, "Account deletion is unavailable here.", headers=PRIVATE)
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
                if getattr(request.state, "staff_key", False) is True:
                    raise HTTPException(403, "Sign in to delete your account.", headers=PRIVATE)
                yield auth
        except DomainError:
            raise HTTPException(401, "Sign in to see this.", headers=PRIVATE) from None

    def refuse(status: int, code: str, **extra: Any) -> HTTPException:
        return HTTPException(
            status, {"code": code, "message": WORDS[code], **extra}, headers=PRIVATE
        )

    @router.get("")
    async def preview(request: Request, response: Response) -> dict[str, Any]:
        async with account(request, response) as auth:
            actor = auth.resolved.actor
            check = await deletion_check(auth.database, actor.person_id)
            return {
                "confirm_word": CONFIRM_WORD,
                "fresh_sign_in": await session_is_fresh(
                    auth.database, actor.session_id, datetime.now(UTC)
                ),
                "fresh_minutes": int(FRESH_SIGN_IN.total_seconds() // 60),
                "staff": check.staff,
                **_organisations(check),
            }

    @router.post("")
    async def delete_account(
        request: Request, response: Response, body: DeleteAccountRequest
    ) -> dict[str, Any]:
        if body.confirm.strip().upper() != CONFIRM_WORD:
            raise refuse(422, "confirm")
        async with account(request, response, write=True) as auth:
            actor = auth.resolved.actor
            tenant_id = actor.tenant_id or settings.public_learner_tenant_id
            if tenant_id is None:
                raise HTTPException(503, "Account deletion is unavailable here.", headers=PRIVATE)
            now = datetime.now(UTC)
            if not await session_is_fresh(auth.database, actor.session_id, now):
                raise refuse(403, "fresh_sign_in")
            check = await deletion_check(auth.database, actor.person_id)
            if check.staff:
                raise refuse(403, "staff")
            if check.transfer_first:
                raise refuse(
                    409,
                    "transfer_ownership_first",
                    organisations=_organisations(check)["transfer_first"],
                )
            reason = (body.reason or "").strip() or None
            request_row, revoked = await auth.identity.close_account(
                auth.token, reason=reason, now=now
            )
            event = await AuditRepository(auth.database).append(
                tenant_id=tenant_id,
                actor_person_id=actor.person_id,
                session_id=actor.session_id,
                action=ACCOUNT_CLOSED_ACTION,
                resource_type="person",
                resource_id=actor.person_id,
                payload={
                    "deletion_request_id": str(request_row.id),
                    "sessions_revoked": revoked,
                    "organisations_closing": [
                        str(item.tenant_id) for item in check.closes_with_account
                    ],
                    "ip_address": client_identity(
                        request.scope,
                        trusted_proxy_addresses=settings.rate_limit_trusted_proxy_addresses,
                    ),
                },
                reason=(
                    "The person asked in Settings for their account to be deleted, "
                    "which closed it until the deletion is carried out."
                ),
                now=now,
            )
            await enqueue_account_closed_emails(auth.database, event)
        _delete_session_cookie(response, settings)
        return {"closed": True, "requested_at": request_row.requested_at.isoformat()}

    app.include_router(router)
