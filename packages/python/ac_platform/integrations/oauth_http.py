"""Connect (OAuth 2.0 + PKCE) over HTTP.

The consent screen (Sales X-Ray app, signed in):
- POST /v1/oauth/authorize/check     what the app asks for, before anything is shown
- POST /v1/oauth/authorize/decision  approve or deny; returns where to send the browser

An organisation's own app is approved by that organisation's owner or admin. A
platform app (self-registered or first-party, such as Pulse) is approved by any
signed-in person for their own account in the workspace they have open.

The app's own server (no cookies):
- POST /v1/oauth/token               authorization_code or refresh_token (form or JSON)
- POST /v1/oauth/revoke              RFC 7009
- POST /v1/oauth/register            RFC 7591 dynamic client registration
- GET  /v1/oauth/metadata            RFC 8414 server metadata

Discovery for MCP hosts (ChatGPT, Claude, any spec client), the same documents the web app
serves at these paths in production. On dev the edge sends them here, so a host is never kept
waiting by the web app's development compiler:
- GET  /.well-known/oauth-authorization-server   RFC 8414 (also at openid-configuration,
                                                 for hosts that try OIDC discovery first)
- GET  /.well-known/oauth-protected-resource[/v1/mcp|/v1/api]   RFC 9728

The signed-in person's own connections (Settings):
- GET  /v1/me/connected-apps                     apps they connected for themself
- POST /v1/me/connected-apps/{id}/revoke         remove one

Token answers follow RFC 6749 §5 (``error``, ``error_description``) with
``Cache-Control: no-store``. A wrong client or address never redirects: the screen
says so instead, so the consent page cannot be used to bounce people elsewhere.
"""

from __future__ import annotations

import base64
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ac_platform.audit.service import AuditRepository
from ac_platform.http.auth import require_safe_origin
from ac_platform.http.rate_limits import InMemoryTokenBucketLimiter, RateLimitRule
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import first_party, oauth, scopes
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
REGISTER_WORDS = {
    "invalid_redirect_uri": (
        "Give 1 to 5 exact return addresses: https, or http on 127.0.0.1 or localhost."
    ),
    "invalid_client_metadata": (
        "Send client_name (your app's own name), redirect_uris, and optionally "
        "token_endpoint_auth_method (none, client_secret_basic or client_secret_post) "
        "and grant_types (authorization_code, refresh_token)."
    ),
}
# What an MCP host gets when it asks for no scope: reading, never writing.
DEFAULT_SCOPES = "calls:read reports:read leads:read"
# The MCP tools' scopes, which the resource metadata offers (webhooks:manage is for the CLI).
MCP_SCOPES = ("calls:read", "reports:read", "leads:read", "leads:write")
RESOURCES = ("/v1/mcp", "/v1/api")
DISCOVERY = {"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"}
REGISTER_EACH = RateLimitRule(
    name="oauth-register-address",
    method="POST",
    path=re.compile(r"^/v1/oauth/register$"),
    capacity=10,
    refill_seconds=3600.0,
)
REGISTER_ALL = RateLimitRule(
    name="oauth-register-all",
    method="POST",
    path=re.compile(r"^/v1/oauth/register$"),
    capacity=200,
    refill_seconds=3600.0,
)


class AuthorizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=40)
    redirect_uri: str = Field(min_length=1, max_length=512)
    scope: str | None = Field(default=None, max_length=400)
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
        try:
            data = json.loads(raw or b"{}")
        except ValueError:
            return {}
        if not isinstance(data, dict):
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


def server_metadata(base: str) -> dict[str, Any]:
    """RFC 8414 authorization server metadata for this Sales X-Ray address."""
    methods = list(oauth.AUTH_METHODS)
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/connect",
        "token_endpoint": f"{base}/v1/oauth/token",
        "revocation_endpoint": f"{base}/v1/oauth/revoke",
        "registration_endpoint": f"{base}/v1/oauth/register",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": list(oauth.GRANT_TYPES),
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": methods,
        "revocation_endpoint_auth_methods_supported": methods,
        "scopes_supported": list(scopes.SCOPES),
        "service_documentation": f"{base}/developers",
    }


def protected_resource_metadata(base: str, path: str) -> dict[str, Any] | None:
    """RFC 9728 metadata for /v1/mcp (also the bare path) or /v1/api; None for anything else."""
    resource = "/" + path.strip("/") if path.strip("/") else "/v1/mcp"
    if resource not in RESOURCES:
        return None
    return {
        "resource": f"{base}{resource}",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
        "scopes_supported": list(MCP_SCOPES),
        "resource_name": "Sales X-Ray",
        "resource_documentation": f"{base}/developers",
    }


def install_oauth_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/oauth", tags=["oauth"])
    mine = APIRouter(prefix="/v1/me/connected-apps", tags=["oauth"])
    discovery = APIRouter(tags=["oauth"])
    settings = ctx.settings
    read_actor = getattr(ctx.require_actor, "read_only", ctx.require_actor)
    limiter = InMemoryTokenBucketLimiter()

    def served(request: Request) -> bool:
        return (
            settings.sales_xray_app_url is not None
            and request.url.hostname == settings.sales_xray_app_url.host
        )

    def here(request: Request) -> None:
        if not served(request):
            raise HTTPException(404, "Connect is not served here.")

    def base() -> str:
        return str(settings.sales_xray_app_url).rstrip("/")

    async def organisation_manager(auth: Any) -> tuple[Any, dict[str, Any]]:
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
        workspace = {
            "id": str(actor.tenant_id),
            "kind": "organisation",
            "name": row.name,
            "role": row.role,
        }
        return actor, workspace

    async def person_workspace(auth: Any) -> tuple[Any, dict[str, Any]]:
        """The workspace the person has open, for a connection of their own."""
        actor = auth.resolved.actor
        refused = HTTPException(
            403,
            "Open your Personal workspace or an organisation you belong to, then try again.",
            headers={**PRIVATE, "X-Connect-Reach": "person"},
        )
        if actor.tenant_id is None or actor.tenant_id == settings.operations_tenant_id:
            raise refused
        if actor.tenant_id == settings.public_learner_tenant_id:
            return actor, {
                "id": str(actor.tenant_id),
                "kind": "personal",
                "name": "Personal",
                "role": None,
            }
        row = (
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
        if row is None:
            raise refused
        role = row.role if row.role in {"owner", "admin"} else "member"
        return actor, {
            "id": str(actor.tenant_id),
            "kind": "organisation",
            "name": row.name,
            "role": role,
        }

    async def checked(auth: Any, body: AuthorizeRequest) -> tuple[Any, list[str]]:
        try:
            result: tuple[Any, list[str]] = await auth.database.run_sync(
                lambda session: oauth.check_request(
                    session.connection(),
                    client_id=body.client_id,
                    redirect_uri=body.redirect_uri,
                    scope=body.scope or DEFAULT_SCOPES,
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

    async def approver(auth: Any, client: Any) -> tuple[Any, dict[str, Any]]:
        if oauth.is_platform(client):
            return await person_workspace(auth)
        return await organisation_manager(auth)

    def app_view(client: Any) -> dict[str, Any]:
        platform = oauth.is_platform(client)
        known = (
            first_party.verified(client.name, client.redirect_uris, settings.environment)
            if platform
            else None
        )
        return {
            "name": client.name,
            "client_id": client.client_id,
            "verified": known is not None,
            "maker": known.maker if known else None,
            "self_registered": platform and known is None,
        }

    @router.post("/authorize/check")
    async def check(body: AuthorizeRequest, request: Request, response: Response) -> dict[str, Any]:
        here(request)
        response.headers.update(PRIVATE)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                client, chosen = await checked(auth, body)
                _actor, workspace = await approver(auth, client)
                labels = dict(scopes.SCOPES)
                return {
                    "app": app_view(client),
                    "reach": "person" if oauth.is_platform(client) else "organisation",
                    "returns_to": urlsplit(body.redirect_uri).hostname,
                    "organisation": {"id": workspace["id"], "name": workspace["name"]},
                    "workspace": workspace,
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
                actor, workspace = await approver(auth, client)
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
                    payload={
                        "app": client.name,
                        "scopes": chosen,
                        "reach": "person" if oauth.is_platform(client) else "organisation",
                        "workspace_kind": workspace["kind"],
                    },
                )
                return {"redirect": _with_query(body.redirect_uri, {"code": code, **extra})}
        except DomainError:
            raise HTTPException(401, "Sign in to connect this app.", headers=PRIVATE) from None

    @router.post("/token")
    async def token(request: Request) -> JSONResponse:
        if not served(request):
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
        if not served(request):
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

    @router.post("/register")
    async def register(request: Request) -> JSONResponse:
        if not served(request):
            return _oauth_error("invalid_request", 404)
        address = request.headers.get("cf-connecting-ip") or (
            request.client.host if request.client else "unknown"
        )
        for key, rule in ((address[:64], REGISTER_EACH), ("all", REGISTER_ALL)):
            allowed, retry, _ = await limiter.consume(key, rule)
            if not allowed:
                return JSONResponse(
                    {"error": "slow_down", "error_description": "Too many registrations."},
                    status_code=429,
                    headers={**NO_STORE, "Retry-After": str(max(1, retry))},
                )
        raw = await request.body()
        try:
            metadata = json.loads(raw) if 0 < len(raw) <= 8192 else None
        except ValueError:
            metadata = None
        now = datetime.now(UTC)
        try:
            async with ctx.sessions() as session, session.begin():
                answer = await session.run_sync(
                    lambda sync: oauth.register_dynamic(sync.connection(), metadata, now=now)
                )
        except IntegrationError as error:
            code = error.code if error.code in REGISTER_WORDS else "invalid_client_metadata"
            return _oauth_error(code, 400, REGISTER_WORDS[code])
        return JSONResponse(answer, status_code=201, headers=NO_STORE)

    @router.get("/metadata")
    async def metadata(request: Request) -> JSONResponse:
        if not served(request):
            return _oauth_error("invalid_request", 404)
        return JSONResponse(server_metadata(base()), headers={"Cache-Control": "max-age=300"})

    def not_found() -> JSONResponse:
        return JSONResponse({"error": "not_found"}, status_code=404, headers=NO_STORE)

    @discovery.get("/.well-known/oauth-authorization-server")
    @discovery.get("/.well-known/openid-configuration")
    async def server_discovery(request: Request) -> JSONResponse:
        if not served(request):
            return not_found()
        return JSONResponse(server_metadata(base()), headers=DISCOVERY)

    @discovery.get("/.well-known/oauth-protected-resource")
    @discovery.get("/.well-known/oauth-protected-resource/{path:path}")
    async def resource_discovery(request: Request, path: str = "") -> JSONResponse:
        body = protected_resource_metadata(base(), path) if served(request) else None
        return JSONResponse(body, headers=DISCOVERY) if body else not_found()

    @mine.get("")
    async def my_apps(request: Request, response: Response) -> dict[str, Any]:
        here(request)
        response.headers.update(PRIVATE)
        try:
            async with asynccontextmanager(read_actor)(request) as auth:
                person = auth.resolved.actor.person_id
                apps = await auth.database.run_sync(
                    lambda session: oauth.person_connections(session.connection(), person)
                )
                return {"apps": apps}
        except DomainError:
            raise HTTPException(401, "Sign in to see your connected apps.") from None

    @mine.post("/{grant_id}/revoke")
    async def remove_my_app(grant_id: UUID, request: Request, response: Response) -> dict[str, Any]:
        here(request)
        response.headers.update(PRIVATE)
        try:
            require_safe_origin(request, settings)
        except DomainError:
            raise HTTPException(403, "Use the Sales Xray page to continue.") from None
        try:
            async with asynccontextmanager(ctx.require_actor)(request) as auth:
                actor = auth.resolved.actor
                now = datetime.now(UTC)
                try:
                    changed = await auth.database.run_sync(
                        lambda session: oauth.revoke_person_grant(
                            session.connection(),
                            person_id=actor.person_id,
                            grant_id=grant_id,
                            now=now,
                        )
                    )
                except IntegrationError:
                    raise HTTPException(404, "That connection isn't yours.") from None
                if changed and actor.tenant_id is not None:
                    await AuditRepository(auth.database).append_for_actor(
                        actor,
                        action="integration.app_disconnected",
                        resource_type="integration_oauth_grant",
                        resource_id=str(grant_id),
                        payload={"by": "person"},
                    )
                apps = await auth.database.run_sync(
                    lambda session: oauth.person_connections(session.connection(), actor.person_id)
                )
                return {"apps": apps}
        except DomainError:
            raise HTTPException(401, "Sign in to manage your connected apps.") from None

    application.include_router(router)
    application.include_router(mine)
    application.include_router(discovery)
