"""Connect (OAuth 2.0 + PKCE) over HTTP.

The consent screen (Sales X-Ray app, signed in as an organisation owner or admin):
- POST /v1/oauth/authorize/check     what the app asks for, before anything is shown
- POST /v1/oauth/authorize/decision  approve or deny; returns where to send the browser

The app's own server (no cookies):
- POST /v1/oauth/token               authorization_code or refresh_token (form or JSON)
- POST /v1/oauth/revoke              RFC 7009

Token answers follow RFC 6749 §5 (``error``, ``error_description``) with
``Cache-Control: no-store``. A wrong client or address never redirects: the screen
says so instead, so the consent page cannot be used to bounce people elsewhere.
"""

from __future__ import annotations

import base64
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import oauth, scopes
from ac_platform.integrations.errors import IntegrationError
from ac_platform.kernel.errors import DomainError
from ac_platform.tenancy.models import Membership, Organisation, Tenant

PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
WORDS = {
    "client_unknown": "This app is not registered with Sales X-Ray.",
    "redirect_uri": "This app asked to return to an address it did not register.",
    "unsupported_response_type": "This app asked in a way Sales X-Ray does not support.",
    "pkce": "This app did not send a valid PKCE challenge (S256).",
    "invalid_scope": "This app asked for a permission Sales X-Ray does not have.",
}


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=40)
    redirect_uri: str = Field(min_length=1, max_length=512)
    scope: str = Field(min_length=1, max_length=400)
    code_challenge: str = Field(min_length=1, max_length=128)
    code_challenge_method: str = Field(min_length=1, max_length=8)
    response_type: str = Field(min_length=1, max_length=16)
    state: str | None = Field(default=None, max_length=500)


class Decision(AuthorizeRequest):
    approve: bool


def _with_query(uri: str, values: dict[str, str]) -> str:
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True) + list(values.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


def _oauth_error(code: str, status: int = 400, description: str | None = None) -> JSONResponse:
    body = {"error": code}
    if description:
        body["error_description"] = description
    headers = dict(NO_STORE)
    if status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="sales-xray"'
    return JSONResponse(body, status_code=status, headers=headers)


async def _form(request: Request) -> dict[str, str]:
    kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    raw = await request.body()
    if len(raw) > 8192:
        return {}
    if kind == "application/json":
        import json

        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            return {}
        return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    return dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))


def _client_credentials(request: Request, form: dict[str, str]) -> tuple[str, str | None]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return "", None
        client_id, _, secret = decoded.partition(":")
        return client_id, secret or None
    return form.get("client_id", ""), form.get("client_secret") or None


def install_oauth_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/oauth", tags=["oauth"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)

    def here(request: Request) -> None:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            raise HTTPException(404, "Connect is not served here.")

    async def manager(auth: Any) -> tuple[Any, str]:
        actor = auth.resolved.actor
        row = (
            None
            if actor.tenant_id is None
            else (
                await auth.database.execute(
                    select(Membership.role, Tenant.name)
                    .join(Organisation, Organisation.tenant_id == Membership.tenant_id)
                    .join(Tenant, Tenant.id == Membership.tenant_id)
                    .where(
                        Membership.tenant_id == actor.tenant_id,
                        Membership.person_id == actor.person_id,
                        Membership.status == "active",
                        Membership.ended_at.is_(None),
                    )
                )
            ).first()
        )
        if row is None or row.role not in {"owner", "admin"}:
            raise HTTPException(
                403,
                "Open the organisation you want to connect, as its owner or admin.",
                headers=PRIVATE,
            )
        return actor, row.name

    async def checked(auth: Any, body: AuthorizeRequest) -> tuple[Any, list[str]]:
        try:
            result: tuple[Any, list[str]] = await auth.database.run_sync(
                lambda session: oauth.check_request(
                    session.connection(),
                    client_id=body.client_id,
                    redirect_uri=body.redirect_uri,
                    scope=body.scope,
                    code_challenge=body.code_challenge,
                    code_challenge_method=body.code_challenge_method,
                    response_type=body.response_type,
                )
            )
            return result
        except IntegrationError as error:
            raise HTTPException(
                400, WORDS.get(error.code, "This request is not valid."), headers=PRIVATE
            ) from None

    @router.post("/authorize/check")
    async def check(body: AuthorizeRequest, request: Request, response: Response) -> dict[str, Any]:
        here(request)
        response.headers.update(PRIVATE)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                client, chosen = await checked(auth, body)
                actor, organisation = await manager(auth)
                labels = dict(scopes.SCOPES)
                return {
                    "app": {"name": client.name, "client_id": client.client_id},
                    "returns_to": urlsplit(body.redirect_uri).hostname,
                    "organisation": {"id": str(actor.tenant_id), "name": organisation},
                    "scopes": [{"key": key, "label": labels[key]} for key in chosen],
                }
        except DomainError:
            raise HTTPException(401, "Sign in to connect this app.", headers=PRIVATE) from None

    @router.post("/authorize/decision")
    async def decide(body: Decision, request: Request, response: Response) -> dict[str, Any]:
        here(request)
        response.headers.update(PRIVATE)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use the Sales Xray page to continue.") from None
        try:
            async with asynccontextmanager(ctx.require_actor)(request) as auth:
                client, chosen = await checked(auth, body)
                actor, _ = await manager(auth)
                extra = {"state": body.state} if body.state is not None else {}
                if not body.approve:
                    return {
                        "redirect": _with_query(
                            body.redirect_uri, {"error": "access_denied", **extra}
                        )
                    }
                now = datetime.now(UTC)
                code = await auth.database.run_sync(
                    lambda session: oauth.issue_code(
                        session.connection(),
                        client=client,
                        tenant_id=actor.tenant_id,
                        person_id=actor.person_id,
                        scopes=chosen,
                        redirect_uri=body.redirect_uri,
                        code_challenge=body.code_challenge,
                        now=now,
                    )
                )
                await AuditRepository(auth.database).append_for_actor(
                    actor,
                    action="integration.app_connected",
                    resource_type="integration_oauth_client",
                    resource_id=client.client_id,
                    payload={"app": client.name, "scopes": chosen},
                )
                return {"redirect": _with_query(body.redirect_uri, {"code": code, **extra})}
        except DomainError:
            raise HTTPException(401, "Sign in to connect this app.", headers=PRIVATE) from None

    @router.post("/token")
    async def token(request: Request) -> JSONResponse:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            return _oauth_error("invalid_request", 404)
        form = await _form(request)
        client_id, client_secret = _client_credentials(request, form)
        grant_type = form.get("grant_type", "")
        now = datetime.now(UTC)
        result: dict[str, Any] | None = None
        refused: str | None = None
        # A refusal may follow a security action (a reused code or refresh token ends
        # the connection); the transaction still commits, then the refusal is sent.
        async with ctx.sessions() as session, session.begin():
            try:
                if grant_type == "authorization_code":
                    result = await session.run_sync(
                        lambda sync: oauth.exchange_code(
                            sync.connection(),
                            code=form.get("code", ""),
                            client_id=client_id,
                            client_secret=client_secret,
                            redirect_uri=form.get("redirect_uri", ""),
                            code_verifier=form.get("code_verifier", ""),
                            now=now,
                        )
                    )
                elif grant_type == "refresh_token":
                    result = await session.run_sync(
                        lambda sync: oauth.refresh(
                            sync.connection(),
                            refresh_token=form.get("refresh_token", ""),
                            client_id=client_id,
                            client_secret=client_secret,
                            now=now,
                        )
                    )
                else:
                    refused = "unsupported_grant_type"
            except IntegrationError as error:
                refused = (
                    "invalid_client"
                    if error.code in {"invalid_client", "client_unknown"}
                    else "invalid_grant"
                )
        if refused is not None or result is None:
            code = refused or "invalid_grant"
            return _oauth_error(code, 401 if code == "invalid_client" else 400)
        return JSONResponse(result, headers=NO_STORE)

    @router.post("/revoke")
    async def revoke(request: Request) -> Response:
        if (
            settings.sales_xray_app_url is None
            or request.url.hostname != settings.sales_xray_app_url.host
        ):
            return _oauth_error("invalid_request", 404)
        form = await _form(request)
        client_id, client_secret = _client_credentials(request, form)
        now = datetime.now(UTC)
        try:
            async with ctx.sessions() as session, session.begin():
                client = await session.run_sync(
                    lambda sync: oauth.find_client(sync.connection(), client_id)
                )
                oauth._client_auth(client, client_secret)
                await session.run_sync(
                    lambda sync: oauth.revoke_token(
                        sync.connection(), token=form.get("token", ""), client_id=client_id, now=now
                    )
                )
        except IntegrationError:
            return _oauth_error("invalid_client", 401)
        return Response(status_code=200, headers=NO_STORE)

    application.include_router(router)
