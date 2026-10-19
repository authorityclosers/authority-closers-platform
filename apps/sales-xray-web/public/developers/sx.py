#!/usr/bin/env python3
"""sx: the Sales X-Ray command line and MCP server, on the public API (/v1/api).

Download: https://salesxray.authorityclosers.com/developers/sx.py

One file, Python 3.10+ standard library only. Uses an API key made in Sales X-Ray
under Organisation -> Integrations; the key is read from SX_API_KEY (never a
command-line argument, so it stays out of shell history and process lists).

    export SX_API_KEY=sxk_live_...            # or sxk_test_... on staging
    export SX_API_BASE=https://salesxray.authorityclosers.com/v1/api   # the default

    sx me                                     # the key's organisation and scopes
    sx calls [--before CALL_ID]               # calls, newest first, 50 a page
    sx facts CALL_ID                          # the facts found in one call
    sx leads [--stage open|new|...] [--offset N]
    sx lead LEAD_ID
    sx add-lead --name NAME [--phone P] [--email E] [--company C] [--city C]
                [--interest I] [--note N] [--external-id ID]
    sx mcp                                    # an MCP server on stdio (for AI assistants)

Output is JSON. Exit status 0 on success, 1 when the API refused (its error code and
message are printed), 2 on a usage or connection problem.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

DEFAULT_BASE = "https://salesxray.authorityclosers.com/v1/api"
VERSION = "1.0.0"
TIMEOUT = 30


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message = status, code, message


Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def _urlopen(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class Client:
    """The Sales X-Ray API for one key."""

    def __init__(self, key: str, base: str = DEFAULT_BASE, transport: Transport = _urlopen):
        if not key.startswith(("sxk_", "sxa_")):
            raise ValueError("SX_API_KEY must be a Sales X-Ray API key (sxk_...)")
        if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
            raise ValueError("SX_API_BASE must be https://")
        self.key, self.base, self.transport = key, base.rstrip("/"), transport

    def call(
        self,
        method: str,
        path: str,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        clean = {k: v for k, v in (query or {}).items() if v is not None}
        url = self.base + path + ("?" + urllib.parse.urlencode(clean) if clean else "")
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
        request.add_header("Authorization", f"Bearer {self.key}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"sx/{VERSION}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        status, raw = self.transport(request)
        try:
            payload = json.loads(raw or b"null")
        except ValueError:
            payload = None
        if not 200 <= status < 300:
            error = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
            raise ApiError(status, error.get("code", "http_error"), error.get("message", ""))
        return payload

    def me(self) -> Any:
        return self.call("GET", "/me")

    def calls(self, before: str | None = None) -> Any:
        return self.call("GET", "/calls", {"before": before})

    def facts(self, call_id: str) -> Any:
        return self.call("GET", f"/calls/{urllib.parse.quote(call_id, safe='')}/facts")

    def leads(self, stage: str | None = None, offset: int | None = None) -> Any:
        return self.call("GET", "/leads", {"stage": stage, "offset": offset})

    def lead(self, lead_id: str) -> Any:
        return self.call("GET", f"/leads/{urllib.parse.quote(lead_id, safe='')}")

    def add_lead(self, **fields: Any) -> Any:
        return self.call("POST", "/leads", body={k: v for k, v in fields.items() if v})


# ----- MCP (Model Context Protocol) over stdio ------------------------------------

PROTOCOL = "2025-06-18"
TOOLS: list[dict[str, Any]] = [
    {
        "name": "whoami",
        "description": "The Sales X-Ray organisation this key belongs to and what it may do.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_calls",
        "description": "The organisation's analysed sales calls, newest first, 50 a page. "
        "Pass before=<the last id> for the next page.",
        "inputSchema": {
            "type": "object",
            "properties": {"before": {"type": "string", "description": "Call id to page after"}},
        },
    },
    {
        "name": "call_facts",
        "description": "The facts Sales X-Ray found in one call: needs, budget, decision "
        "makers, objections, next steps, each with the quote it came from.",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": {"type": "string"}},
            "required": ["call_id"],
        },
    },
    {
        "name": "list_leads",
        "description": "Leads in the organisation's Lead Desk, newest change first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "enum": [
                        "open",
                        "new",
                        "not_connected",
                        "follow_up",
                        "interested",
                        "won",
                        "lost",
                    ],
                },
                "offset": {"type": "integer", "minimum": 0},
            },
        },
    },
    {
        "name": "get_lead",
        "description": "One lead with its history.",
        "inputSchema": {
            "type": "object",
            "properties": {"lead_id": {"type": "string"}},
            "required": ["lead_id"],
        },
    },
    {
        "name": "add_lead",
        "description": "Add a lead to the Lead Desk. Needs at least a name, phone or email. "
        "The same external_id again changes nothing.",
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
    },
]


def _tool(client: Client, name: str, args: dict[str, Any]) -> Any:
    if name == "whoami":
        return client.me()
    if name == "list_calls":
        return client.calls(args.get("before"))
    if name == "call_facts":
        return client.facts(str(args["call_id"]))
    if name == "list_leads":
        return client.leads(args.get("stage"), args.get("offset"))
    if name == "get_lead":
        return client.lead(str(args["lead_id"]))
    if name == "add_lead":
        allowed = {t: args.get(t) for t in TOOLS[5]["inputSchema"]["properties"]}
        return client.add_lead(**allowed)
    raise KeyError(name)


def handle(client: Client, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC request in, its response out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None  # notifications (e.g. notifications/initialized) need no answer
    if method == "initialize":
        result: Any = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "sales-xray", "version": VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            data = _tool(client, str(params.get("name")), dict(params.get("arguments") or {}))
            result = {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}
        except ApiError as error:
            text = f"Sales X-Ray refused ({error.status} {error.code}): {error.message}"
            result = {"content": [{"type": "text", "text": text}], "isError": True}
        except KeyError as error:
            return {
                "jsonrpc": "2.0",
                "id": ident,
                "error": {"code": -32602, "message": f"Unknown tool or argument: {error}"},
            }
        except (OSError, ValueError) as error:
            result = {
                "content": [
                    {"type": "text", "text": f"Could not reach Sales X-Ray: {type(error).__name__}"}
                ],
                "isError": True,
            }
    else:
        return {
            "jsonrpc": "2.0",
            "id": ident,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(client: Client, stdin: Any = sys.stdin, stdout: Any = sys.stdout) -> None:
    for line in stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: dict[str, Any] | None = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        else:
            reply = handle(client, message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


# ----- command line --------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sx", description="Sales X-Ray from the command line.")
    parser.add_argument("--version", action="version", version=f"sx {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("me")
    calls = commands.add_parser("calls")
    calls.add_argument("--before")
    facts = commands.add_parser("facts")
    facts.add_argument("call_id")
    leads = commands.add_parser("leads")
    leads.add_argument("--stage")
    leads.add_argument("--offset", type=int)
    lead = commands.add_parser("lead")
    lead.add_argument("lead_id")
    add = commands.add_parser("add-lead")
    for name in ("name", "phone", "email", "company", "city", "interest", "note", "external-id"):
        add.add_argument(f"--{name}")
    commands.add_parser("mcp")
    return parser


def main(
    argv: list[str] | None = None,
    environ: dict[str, str] | None = None,
    transport: Transport = _urlopen,
) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        client = Client(env.get("SX_API_KEY", ""), env.get("SX_API_BASE", DEFAULT_BASE), transport)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if args.command == "mcp":
        serve(client)
        return 0
    try:
        if args.command == "me":
            out = client.me()
        elif args.command == "calls":
            out = client.calls(args.before)
        elif args.command == "facts":
            out = client.facts(args.call_id)
        elif args.command == "leads":
            out = client.leads(args.stage, args.offset)
        elif args.command == "lead":
            out = client.lead(args.lead_id)
        else:
            out = client.add_lead(
                name=args.name,
                phone=args.phone,
                email=args.email,
                company=args.company,
                city=args.city,
                interest=args.interest,
                note=args.note,
                external_id=args.external_id,
            )
    except ApiError as error:
        print(
            json.dumps(
                {"error": {"status": error.status, "code": error.code, "message": error.message}}
            ),
            file=sys.stderr,
        )
        return 1
    except OSError as error:
        print(f"Could not reach Sales X-Ray: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
