"""Sales X-Ray's remote MCP server: Streamable HTTP (MCP 2025-06-18), one JSON answer.

- POST /v1/mcp   one JSON-RPC 2.0 message per request; the answer is application/json
                 (a notification gets 202 and no body).
- GET  /v1/mcp   405: this server opens no event stream of its own.

Every request carries ``Authorization: Bearer``: a Connect access token (``sxa_``) or an
API key (``sxk_``). Without a valid one the answer is 401 with
``WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/v1/mcp"``
(RFC 9728), so an MCP host (Claude, ChatGPT, Pulse's assistant) finds Connect, registers
itself (RFC 7591) and signs the person in with PKCE. The tools read through the same
``Reader`` as ``/v1/api``, so a person's connection sees exactly what they see in
Sales X-Ray, and each tool needs the same scope as its API route.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.api_http import STAGES, ApiError, NewLeadBody, Reader, make_opener

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
VERSION = "1.0.0"
MAX_BODY = 65536
INSTRUCTIONS = (
    "Sales X-Ray holds this person's sales calls (with reports and the facts found in "
    "them) and their leads. List calls or leads first, then read one by its id. Quote "
    "facts as Sales X-Ray gives them; withheld parts of a call are never shown."
)

_ID = {"type": "string", "description": "The id from a list."}
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "whoami",
        "title": "Who am I in Sales X-Ray",
        "description": (
            "The person, workspace or organisation this connection reads, and its scopes."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
        "scope": None,
    },
    {
        "name": "list_calls",
        "title": "List calls",
        "description": (
            "Sales calls, newest first, 50 a page: id, title, date, length in seconds, "
            "whether a report is ready and a link to open it. Pass next_before for the next page."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"before": {"type": "string", "description": "next_before from a page"}},
        },
        "annotations": {"readOnlyHint": True},
        "scope": "calls:read",
    },
    {
        "name": "get_call",
        "title": "Read one call",
        "description": (
            "One call with its title, date, length, report state and the facts found in it."
        ),
        "inputSchema": {"type": "object", "properties": {"call_id": _ID}, "required": ["call_id"]},
        "annotations": {"readOnlyHint": True},
        "scope": "calls:read",
    },
    {
        "name": "call_facts",
        "title": "Facts found in a call",
        "description": (
            "The facts Sales X-Ray found in one call (budget, timeline, needs and more)."
        ),
        "inputSchema": {"type": "object", "properties": {"call_id": _ID}, "required": ["call_id"]},
        "annotations": {"readOnlyHint": True},
        "scope": "reports:read",
    },
    {
        "name": "list_leads",
        "title": "List leads",
        "description": (
            "Leads on the desk, 50 a page. stage is one of "
            + ", ".join(STAGES)
            + "; pass offset (next_offset from a page) for more."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": list(STAGES)},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
        "annotations": {"readOnlyHint": True},
        "scope": "leads:read",
    },
    {
        "name": "get_lead",
        "title": "Read one lead",
        "description": "One lead with its contact details, stage, owner and history.",
        "inputSchema": {"type": "object", "properties": {"lead_id": _ID}, "required": ["lead_id"]},
        "annotations": {"readOnlyHint": True},
        "scope": "leads:read",
    },
    {
        "name": "add_lead",
        "title": "Add a lead",
        "description": (
            "Adds a lead to Lead Desk. Send at least a name, phone or email. The same "
            "external_id again changes nothing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                name: {"type": "string"}
                for name in (
                    "name",
                    "phone",
                    "email",
                    "company",
                    "city",
                    "interest",
                    "note",
                    "external_id",
                )
            },
        },
        "annotations": {"readOnlyHint": False, "idempotentHint": True},
        "scope": "leads:write",
    },
)
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def listed(scopes: frozenset[str]) -> list[dict[str, Any]]:
    """The tools this connection may use, as MCP describes them."""
    return [
        {key: value for key, value in tool.items() if key != "scope"}
        for tool in TOOLS
        if tool["scope"] is None or tool["scope"] in scopes
    ]


def _uuid(args: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(str(args.get(name, "")))
    except ValueError:
        raise ApiError(422, "argument", f"{name} must be an id from a list.") from None


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "whoami":
        return await reader.me()
    if name == "list_calls":
        before = args.get("before")
        return await reader.calls(_uuid(args, "before") if before else None)
    if name == "get_call":
        return await reader.call(_uuid(args, "call_id"))
    if name == "call_facts":
        return await reader.facts(_uuid(args, "call_id"))
    if name == "list_leads":
        offset = args.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise ApiError(422, "argument", "offset must be a whole number.")
        stage = args.get("stage")
        return await reader.leads(stage if isinstance(stage, str) else None, offset)
    if name == "get_lead":
        return await reader.lead(_uuid(args, "lead_id"))
    if name == "add_lead":
        fields = {key: args.get(key) for key in _BY_NAME["add_lead"]["inputSchema"]["properties"]}
        try:
            body = NewLeadBody(**{k: v for k, v in fields.items() if v is not None})
        except ValueError:
            raise ApiError(422, "argument", "Lead fields must be short text.") from None
        answer, _ = await reader.add_lead(body)
        return answer
    raise KeyError(name)


def _reply(ident: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _fail(ident: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


async def handle(reader: Reader, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC request in, its answer out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if "id" not in message:
        return None
    if not isinstance(method, str):
        return _fail(ident, -32600, "Invalid request")
    raw_params = message.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _reply(
            ident,
            {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sales-xray", "title": "Sales X-Ray", "version": VERSION},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _reply(ident, {})
    if method == "tools/list":
        return _reply(ident, {"tools": listed(reader.key.scopes)})
    if method == "tools/call":
        name = str(params.get("name", ""))
        raw_args = params.get("arguments")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        tool = _BY_NAME.get(name)
        if tool is None:
            return _fail(ident, -32602, f"Unknown tool: {name}")
        try:
            data = await run_tool(reader, name, args)
        except ApiError as error:
            text = f"Sales X-Ray refused ({error.status} {error.code}): {error.message}"
            return _reply(ident, {"content": [{"type": "text", "text": text}], "isError": True})
        text = json.dumps(data, ensure_ascii=False, default=str)
        result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "isError": False}
        if isinstance(data, dict):
            result["structuredContent"] = data
        return _reply(ident, result)
    return _fail(ident, -32601, f"Method not found: {method}")


def install_mcp_http(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/mcp", tags=["mcp"])
    settings = ctx.settings
    open_reader = make_opener(ctx)
    base = str(settings.sales_xray_app_url).rstrip("/") if settings.sales_xray_app_url else ""
    challenge = f'resource_metadata="{base}/.well-known/oauth-protected-resource/v1/mcp"'

    def refused(error: ApiError) -> JSONResponse:
        headers = {"Cache-Control": "no-store"}
        if error.status == 401:
            invalid = ', error="invalid_token"' if error.code == "key_invalid" else ""
            headers["WWW-Authenticate"] = f'Bearer realm="sales-xray", {challenge}{invalid}'
        if error.retry_after is not None:
            headers["Retry-After"] = str(error.retry_after)
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message}},
            status_code=error.status,
            headers=headers,
        )

    @router.post("")
    async def mcp(request: Request) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin.rstrip("/") != base:
            # MCP servers must refuse other web origins (DNS rebinding).
            return JSONResponse(
                {"error": {"code": "origin", "message": "Origin not allowed."}}, 403
            )
        raw = await request.body()
        try:
            message = json.loads(raw) if 0 < len(raw) <= MAX_BODY else None
        except ValueError:
            message = None
        try:
            async with open_reader(request) as reader:
                if not isinstance(message, dict):
                    answer: dict[str, Any] | None = _fail(
                        None, -32600, "Send one JSON-RPC message."
                    )
                else:
                    answer = await handle(reader, message)
        except ApiError as error:
            return refused(error)
        if answer is None:
            return Response(status_code=202)
        return JSONResponse(answer, headers={"Cache-Control": "no-store"})

    @router.get("")
    async def no_stream() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    application.include_router(router)
