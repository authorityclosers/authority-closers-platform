"""Admin bug work without the browser: API, CLI and MCP (owner, 26 Oct 2026: "Add admin
api, cli, mcp access to do this dynamically without the interface ... cli mcp and api is
must"; v0.93).

- Admin's own report routes take a report's number as well as its id: GET /v1/admin/bugs/9,
  POST /v1/admin/bugs/9/events. A staff key holding bugs:read reaches the list and one
  report; bugs:write also changes one. ``ac-bugs reports | report | report-set`` call them.
- POST /v1/admin/bugs/mcp is an MCP server (Streamable HTTP, one JSON answer) with list_bugs,
  get_bug and set_bug_status. It is for staff only: Admin's host, the AC operations workspace,
  and with a staff key, bugs:read (bugs:write to change). Customer tokens never reach it.
- A list for a key or a tool never carries a report's words as typed: emails, phone numbers,
  tokens and keys are masked, and the reporter's email is left out. Only asking for one
  report gives its words.
- Each change goes through BugReportStore.change, as Admin's form does, and is audited in the
  operations chain (bug_report.changed); with a staff key, the audit names the key.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.audit.service import AuditRepository
from ac_platform.bug_reports.models import STATUSES, BugReport
from ac_platform.bug_reports.scrub import scrub_text
from ac_platform.bug_reports.store import BugReportNotFound, BugReportRefused, BugReportStore

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
MAX_BODY = 65536
LIST_STATUSES = ("open", *STATUSES, "all")
INSTRUCTIONS = (
    "Sales X-Ray bug reports for the AC team. List them (words masked), read one by its "
    "number, and set its status with a note the reporter's history shows. Fixed reads as "
    "Solved in the reporter's app. Every change is audited under this key's name."
)
_NUMBER = re.compile(r"#?([0-9]{1,9})")


async def report_id(database: AsyncSession, ref: str) -> UUID:
    """A report by its number (9 or #9) or its id."""
    number = _NUMBER.fullmatch(ref.strip())
    if number is not None:
        found = await database.scalar(
            select(BugReport.id).where(BugReport.number == int(number.group(1)))
        )
        if found is None:
            raise BugReportNotFound(ref)
        return found
    try:
        return UUID(ref.strip())
    except ValueError:
        raise BugReportNotFound(ref) from None


def masked(item: dict[str, Any]) -> dict[str, Any]:
    """A listed report for a key or a tool: its words masked, no reporter email."""
    person = {key: value for key, value in (item.get("person") or {}).items() if key != "email"}
    return {**item, "words": scrub_text(item.get("words"), 280), "person": person}


async def apply_change(
    database: AsyncSession,
    actor: Any,
    key: Any,
    bug_id: UUID,
    *,
    status: str | None = None,
    severity: str | None = None,
    area: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Admin's change: one event per field that moves, audited (naming the key, if any)."""
    store = BugReportStore(database)
    before = await store.state(bug_id)
    added = await store.change(
        bug_id,
        actor_person_id=actor.person_id,
        now=datetime.now(UTC),
        status=status,
        severity=severity,
        area=area,
        note=note,
    )
    if added:
        await AuditRepository(database).append_for_actor(
            actor,
            action="bug_report.changed",
            resource_type="bug_report",
            resource_id=str(bug_id),
            payload={
                "changed": added,
                "status": [before["status"], status or before["status"]],
                "severity": [before["severity"], severity or before["severity"]],
                "area": [before["area"], area or before["area"]],
                "note": bool(note),
                **({"key": {"name": key.name, "prefix": key.prefix}} if key is not None else {}),
            },
        )
    return await store.detail(bug_id)


# ---------- MCP ----------

_NUMBER_ARG = {"type": "integer", "minimum": 1, "description": "The report's number, e.g. 9."}
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "list_bugs",
        "title": "List bug reports",
        "description": (
            "Bug reports, newest first: number, status, area, screen, organisation and the "
            "words with emails, phone numbers and keys masked. status: open (default: new, "
            "triaged or in progress), one status, or all."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": list(LIST_STATUSES)},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
        "scope": "bugs:read",
    },
    {
        "name": "get_bug",
        "title": "Read one bug report",
        "description": (
            "One report by its number: its words, screen, app, device, recent errors and history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"number": _NUMBER_ARG},
            "required": ["number"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True},
        "scope": "bugs:read",
    },
    {
        "name": "set_bug_status",
        "title": "Set a bug report's status",
        "description": (
            "Set a report's status with a note its history shows; fixed reads as Solved in "
            "the reporter's app. Closing needs a note (a duplicate, or not a bug). Audited "
            "under this key's name."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "number": _NUMBER_ARG,
                "status": {"type": "string", "enum": list(STATUSES)},
                "note": {"type": "string", "maxLength": 2000},
            },
            "required": ["number", "status"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "scope": "bugs:write",
    },
)
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


class ToolRefused(ValueError):
    """A tool's arguments cannot be used."""


def allowed(tool: dict[str, Any], key: Any) -> bool:
    """Staff signed in to Admin may use every tool; a staff key, those its scopes hold."""
    return key is None or tool["scope"] in (key.scopes or ())


def _number(args: dict[str, Any]) -> str:
    number = args.get("number")
    if not isinstance(number, int) or isinstance(number, bool) or not 0 < number < 10**9:
        raise ToolRefused("number: the report's number, e.g. 9.")
    return str(number)


def _brief(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": item["number"],
        "status": item["status"],
        "severity": item["severity"],
        "area": item["area"],
        "route": item["route"],
        "page": (item.get("app") or {}).get("page"),
        "created_at": item["created_at"],
        "words": item["words"],
        "blocks_work": item["blocks_work"],
        "organisation": (item.get("organisation") or {}).get("name"),
        "has_screenshot": item["has_screenshot"],
        "error_count": item["error_count"],
    }


def _full(detail: dict[str, Any]) -> dict[str, Any]:
    return {
        **_brief(detail),
        "bug_id": detail["bug_id"],
        "reporter": (detail.get("person") or {}).get("name"),
        "app": detail.get("app"),
        "device": detail.get("device"),
        "client_errors": detail.get("client_errors") or [],
        "voice_seconds": (detail.get("voice") or {}).get("seconds"),
        "history": [
            {
                "kind": event["kind"],
                "status": event["status"],
                "severity": event["severity"],
                "area": event["area"],
                "note": event["note"],
                "by": event["actor_name"] or event["actor"],
                "at": event["created_at"],
            }
            for event in detail.get("history") or []
        ],
        "admin_path": f"/bugs/{detail['bug_id']}",
    }


async def run_tool(
    database: AsyncSession, actor: Any, key: Any, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    store = BugReportStore(database)
    if name == "list_bugs":
        status = args.get("status", "open")
        limit = args.get("limit", 20)
        if status not in LIST_STATUSES:
            raise ToolRefused(f"status: one of {', '.join(LIST_STATUSES)}.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ToolRefused("limit: 1 to 50.")
        page = await store.page(status=None if status == "all" else status, limit=limit)
        return {
            "reports": [_brief(masked(item)) for item in page["items"]],
            "counts": page["counts"],
        }
    if name == "get_bug":
        return {"report": _full(await store.detail(await report_id(database, _number(args))))}
    status, note = args.get("status"), args.get("note")
    if status not in STATUSES:
        raise ToolRefused(f"status: one of {', '.join(STATUSES)}.")
    if note is not None and (not isinstance(note, str) or len(note) > 2000):
        raise ToolRefused("note: text, up to 2000 characters.")
    bug_id = await report_id(database, _number(args))
    detail = await apply_change(database, actor, key, bug_id, status=status, note=note)
    return {"report": _full(detail)}


def _reply(ident: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def failure(ident: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


def _text(data: dict[str, Any], *, error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        **({} if error else {"structuredContent": data}),
        "isError": error,
    }


async def answer(
    database: AsyncSession, actor: Any, key: Any, message: Any
) -> dict[str, Any] | None:
    """One JSON-RPC message's answer; None for a notification."""
    if (
        not isinstance(message, dict)
        or message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)
    ):
        return failure(None, -32600, "Invalid request")
    if "id" not in message:
        return None
    ident, method = message["id"], message["method"]
    raw = message.get("params")
    params: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _reply(
            ident,
            {
                "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "ac-admin-bugs",
                    "title": "AC Admin: bugs",
                    "version": "1.0.0",
                },
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _reply(ident, {})
    if method == "tools/list":
        return _reply(
            ident,
            {
                "tools": [
                    {k: v for k, v in tool.items() if k != "scope"}
                    for tool in TOOLS
                    if allowed(tool, key)
                ]
            },
        )
    if method != "tools/call":
        return failure(ident, -32601, "Method not found")
    name = params.get("name")
    given = params.get("arguments")
    args: dict[str, Any] = given if isinstance(given, dict) else {}
    tool = _BY_NAME.get(name) if isinstance(name, str) else None
    if tool is None:
        return failure(ident, -32602, "Unknown tool")
    if not allowed(tool, key):
        return _reply(
            ident, _text({"error": f"This key does not hold {tool['scope']}."}, error=True)
        )
    try:
        data = await run_tool(database, actor, key, tool["name"], args)
    except BugReportNotFound:
        return _reply(ident, _text({"error": "No report with that number."}, error=True))
    except (BugReportRefused, ToolRefused) as error:
        return _reply(ident, _text({"error": str(error)}, error=True))
    return _reply(ident, _text(data))
