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
    sx note LEAD_ID TEXT [--request-id ID] [--preview]       # needs leads:notes
    sx task LEAD_ID --kind call_back|whatsapp|email|send_file|meeting|other
            --due 2026-10-27T10:00:00+05:30 [--title T] [--note N] [--ends AT]
            [--remind MINUTES] [--request-id ID] [--preview]  # needs leads:tasks
    sx changes [--lead LEAD_ID]               # notes and tasks this key added (30 days)
    sx undo CHANGE_ID                         # within 7 days: a note stops showing,
                                              # an open task is cancelled
    sx mcp                                    # an MCP server on stdio (for AI assistants)

A change sent again with the same --request-id changes nothing; without one, sx makes
a new one each time. Every change shows "via API key sxk_..." in the lead's history.

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
import uuid
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

    def add_note(self, lead_id: str, note: str, request_id: str, preview: bool = False) -> Any:
        body = {"note": note, "request_id": request_id, "preview": preview}
        return self.call("POST", f"/leads/{urllib.parse.quote(lead_id, safe='')}/notes", body=body)

    def add_task(self, lead_id: str, **fields: Any) -> Any:
        body = {k: v for k, v in fields.items() if v is not None}
        return self.call("POST", f"/leads/{urllib.parse.quote(lead_id, safe='')}/tasks", body=body)

    def changes(self, lead_id: str | None = None) -> Any:
        return self.call("GET", "/changes", {"lead_id": lead_id})

    def undo(self, change_id: str, request_id: str | None = None) -> Any:
        body = {"request_id": request_id} if request_id else {}
        return self.call(
            "POST", f"/changes/{urllib.parse.quote(change_id, safe='')}/undo", body=body
        )


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
    {
        "name": "add_note",
        "description": "Adds a note to one lead. The lead's history shows it came from "
        "this API key; it can be undone for 7 days. The same request_id again changes "
        "nothing. Needs leads:notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "note": {"type": "string", "maxLength": 1000},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["lead_id", "note", "request_id"],
        },
    },
    {
        "name": "add_task",
        "description": "Adds a task or reminder to one lead, for its owner. It can be "
        "undone for 7 days. Needs leads:tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": ["call_back", "whatsapp", "email", "send_file", "meeting", "other"],
                },
                "due": {"type": "string", "description": "e.g. 2026-10-27T10:00:00+05:30"},
                "title": {"type": "string"},
                "note": {"type": "string"},
                "ends_at": {"type": "string"},
                "remind_before_minutes": {"type": "integer"},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["lead_id", "kind", "due", "request_id"],
        },
    },
    {
        "name": "list_my_changes",
        "description": "Notes and tasks this key added in the last 30 days, and whether "
        "each can still be undone.",
        "inputSchema": {"type": "object", "properties": {"lead_id": {"type": "string"}}},
    },
    {
        "name": "undo_change",
        "description": "Undoes one change this key made, within 7 days: a note stops "
        "showing, an open task is cancelled. Both stay in the lead's history.",
        "inputSchema": {
            "type": "object",
            "properties": {"change_id": {"type": "string"}, "request_id": {"type": "string"}},
            "required": ["change_id"],
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
    if name == "add_note":
        return client.add_note(
            str(args["lead_id"]),
            str(args["note"]),
            str(args["request_id"]),
            bool(args.get("preview", False)),
        )
    if name == "add_task":
        fields = ("kind", "due", "title", "note", "ends_at", "remind_before_minutes")
        return client.add_task(
            str(args["lead_id"]),
            request_id=str(args["request_id"]),
            preview=bool(args.get("preview", False)),
            **{key: args.get(key) for key in fields},
        )
    if name == "list_my_changes":
        return client.changes(args.get("lead_id"))
    if name == "undo_change":
        return client.undo(str(args["change_id"]), args.get("request_id"))
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


def _request_id() -> str:
    return f"sx-{uuid.uuid4().hex}"


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
    note = commands.add_parser("note")
    note.add_argument("lead_id")
    note.add_argument("text")
    note.add_argument("--request-id")
    note.add_argument("--preview", action="store_true")
    task = commands.add_parser("task")
    task.add_argument("lead_id")
    task.add_argument("--kind", required=True)
    task.add_argument("--due", required=True)
    for name in ("title", "note", "ends", "request-id"):
        task.add_argument(f"--{name}")
    task.add_argument("--remind", type=int)
    task.add_argument("--preview", action="store_true")
    changes = commands.add_parser("changes")
    changes.add_argument("--lead")
    undo = commands.add_parser("undo")
    undo.add_argument("change_id")
    undo.add_argument("--request-id")
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
        elif args.command == "note":
            out = client.add_note(
                args.lead_id, args.text, args.request_id or _request_id(), args.preview
            )
        elif args.command == "task":
            out = client.add_task(
                args.lead_id,
                kind=args.kind,
                due=args.due,
                title=args.title,
                note=args.note,
                ends_at=args.ends,
                remind_before_minutes=args.remind,
                request_id=args.request_id or _request_id(),
                preview=args.preview,
            )
        elif args.command == "changes":
            out = client.changes(args.lead)
        elif args.command == "undo":
            out = client.undo(args.change_id, args.request_id)
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
