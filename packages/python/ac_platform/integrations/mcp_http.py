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

``search`` and ``fetch`` are the two tools ChatGPT asks for outside its developer mode,
and the only ones its deep research uses: ``search`` answers ``{"results": [{id, title,
url}]}`` and ``fetch`` one ``{id, title, text, url, metadata}``, over calls and leads.

Any Origin is accepted: every request carries its own bearer token and nothing is read
from cookies, so a web page gains nothing a token holder doesn't already have, and AI
hosts (ChatGPT, Claude and others) may send their own origin.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from ac_platform.ask_dipak import integration as ask_dipak
from ac_platform.http.routes import RouteContext
from ac_platform.integrations import (
    admin_api,
    coaching_api,
    lead_imports,
    recordings_api,
    reports_api,
    tiers,
)
from ac_platform.integrations.api_http import (
    ApiError,
    AssignBody,
    BulkBody,
    LeadUpdateBody,
    NewLeadBody,
    NoteBody,
    Reader,
    StageBody,
    TaskBody,
    TaskDoneBody,
    TaskSnoozeBody,
    UndoBody,
    UploadBody,
    make_opener,
)
from ac_platform.integrations.oauth_http import connect_scopes
from ac_platform.lead_desk.commitments import TASK_KINDS

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
VERSION = "1.0.0"
MAX_BODY = 65536
INSTRUCTIONS = (
    "Sales X-Ray holds this person's sales calls (with reports and the facts found in "
    "them) and their leads. List calls or leads first, then read one by its id; a "
    "call's report and transcript come from get_report and get_transcript. Quote "
    "facts as Sales X-Ray gives them; withheld parts of a call are never shown. With "
    "permission, notes and tasks can be added to a lead; each shows which app sent it "
    "and can be undone for 7 days. Ask Dipak's sales lessons are here too, with the "
    "person's Next-call missions and their after-call answers."
)

_ID = {"type": "string", "description": "The id from a list."}
# search and fetch need either scope, and then cover only the kinds it allows.
_SEARCHABLE = ("calls:read", "leads:read")
# Every hint explicit, as the ChatGPT and Claude directories ask: nothing deletes or
# overwrites, and every tool stays inside this person's own workspace (a closed world).
_READS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
# Writes add to a lead's history and never delete or overwrite (undo is its own tool);
# the same request_id again changes nothing.
_WRITES = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_REQUEST = {
    "type": "string",
    "minLength": 8,
    "maxLength": 80,
    "description": "A new string of 8 to 80 characters for this change; the same one "
    "again changes nothing.",
}
_PREVIEW = {
    "type": "boolean",
    "description": "true to see what would change, without changing it.",
}
_WHEN = {
    "type": "string",
    "format": "date-time",
    "description": "Date and time with its time zone, e.g. 2026-10-27T10:00:00+05:30.",
}
SEARCH_LIMIT = 20
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "whoami",
        "title": "Who am I in Sales X-Ray",
        "description": (
            "The person, workspace or organisation this connection reads, and its scopes."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": None,
    },
    {
        "name": "search",
        "title": "Search calls and leads",
        "description": (
            "Finds this person's calls (by title or date, YYYY-MM-DD) and leads (by name, "
            "company, city or phone) that match the words. Each result has an id for fetch."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Words to look for."}},
            "required": ["query"],
        },
        "annotations": _READS,
        "scope": _SEARCHABLE,
    },
    {
        "name": "fetch",
        "title": "Read one search result",
        "description": (
            "The whole record for an id from search: a call with the facts found in it, or "
            "a lead with its contact details, stage and history."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "An id from search."}},
            "required": ["id"],
        },
        "annotations": _READS,
        "scope": _SEARCHABLE,
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
        "annotations": _READS,
        "scope": "calls:read",
    },
    {
        "name": "get_call",
        "title": "Read one call",
        "description": (
            "One call with its title, date, length, report state and the facts found in it."
        ),
        "inputSchema": {"type": "object", "properties": {"call_id": _ID}, "required": ["call_id"]},
        "annotations": _READS,
        "scope": "calls:read",
    },
    {
        "name": "call_facts",
        "title": "Facts found in a call",
        "description": (
            "The facts Sales X-Ray found in one call (budget, timeline, needs and more)."
        ),
        "inputSchema": {"type": "object", "properties": {"call_id": _ID}, "required": ["call_id"]},
        "annotations": _READS,
        "scope": "reports:read",
    },
    # Call reports, transcripts and Saved reports (integrations/reports_api.py).
    *reports_api.TOOLS,
    # Coaching from those reports (integrations/coaching_api.py).
    *coaching_api.TOOLS,
    {
        "name": "list_team",
        "title": "List the team",
        "description": (
            "The team: each person's name and role (never an email), whether they take new "
            "leads, their lead limit, open leads and today's calls, and the leads waiting "
            "for an owner. Use a person_id from here to give leads (assign_lead)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": "team:read",
    },
    {
        "name": "analysis_time",
        "title": "Analysis time left",
        "description": (
            "How much call analysis time the workspace has: given, used and left, in "
            "seconds, and the longest call it takes. Time only, never a price. With team, "
            "also what each member used (an organisation's owners and admins)."
        ),
        "inputSchema": {"type": "object", "properties": {"team": {"type": "boolean"}}},
        "annotations": _READS,
        "scope": "calls:read",
    },
    {
        "name": "list_leads",
        "title": "List leads",
        "description": (
            "Leads on the desk, 50 a page. Each answer lists the organisation's own stages "
            "(key and label) under stages; pass one key as stage for that stage alone, or "
            "open for every open lead. Pass offset (next_offset from a page) for more."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {
                    "type": "string",
                    "maxLength": 40,
                    "description": "A key from stages in an answer, or open.",
                },
                "offset": {"type": "integer", "minimum": 0},
            },
        },
        "annotations": _READS,
        "scope": "leads:read",
    },
    {
        "name": "get_lead",
        "title": "Read one lead",
        "description": "One lead with its contact details, stage, owner and history.",
        "inputSchema": {"type": "object", "properties": {"lead_id": _ID}, "required": ["lead_id"]},
        "annotations": _READS,
        "scope": "leads:read",
    },
    {
        "name": "list_duplicates",
        "title": "List possible duplicate leads",
        "description": (
            "Leads that may be one person, the likeliest first: each pair with how sure "
            "(certain, probable, possible) and why. For an organisation's owners and admins. "
            "Merging is done in Sales X-Ray by a person."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": "leads:read",
    },
    {
        "name": "get_duplicate",
        "title": "Compare two possible duplicates",
        "description": (
            "One pair from list_duplicates side by side: the reasons, the lead a merge would "
            "keep and who would have it."
        ),
        "inputSchema": {"type": "object", "properties": {"pair_id": _ID}, "required": ["pair_id"]},
        "annotations": _READS,
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
        "annotations": {**_READS, "readOnlyHint": False, "idempotentHint": True},
        "scope": "leads:write",
    },
    {
        "name": "import_leads",
        "title": "Import many leads",
        "description": (
            "Imports up to 250 leads per call into Lead Desk, filed in the background exactly "
            "like a file uploaded in the app: duplicates (same phone, or same email without "
            "one) are not new leads, and the import can be undone in the app for 48 hours. "
            "Answers at once with an import id; get_lead_import says when it is done. For "
            "thousands of leads, call it again with the next 250 and a new request_id; the "
            "same request_id with the same leads changes nothing. external_id is the lead's "
            "id in your system: the same id again is the same lead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "leads": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 250,
                    "items": {
                        "type": "object",
                        "properties": {
                            name: {"type": "string"}
                            for name in (
                                "name",
                                "phone",
                                "email",
                                "company",
                                "city",
                                "language",
                                "interest",
                                "stage",
                                "owner",
                                "source",
                                "external_id",
                            )
                        },
                    },
                    "description": "Each lead: at least a name, phone or email. stage is a "
                    "stage's name; owner a teammate's email or name; source the list it "
                    "came from.",
                },
                "name": {"type": "string", "description": "The import's name in the app."},
                "side": {"type": "string", "enum": ["inbound", "cold"]},
                "assign": {
                    "type": "string",
                    "enum": ["rules", "none"],
                    "description": "rules: the workspace's lead rules give new leads out; "
                    "none: nobody gets them yet. A lead's owner field wins either way.",
                },
                "duplicates": {
                    "type": "string",
                    "enum": ["skip", "fill", "replace"],
                    "description": "A lead already here: left as it is (skip), its empty "
                    "details filled, or its details replaced.",
                },
                "request_id": _REQUEST,
            },
            "required": ["leads"],
        },
        "annotations": _WRITES,
        "scope": "leads:write",
    },
    {
        "name": "get_lead_import",
        "title": "See where an import stands",
        "description": (
            "Where an import from import_leads stands: queued, running, done or "
            "partly_failed, with how many leads were created, updated and skipped. "
            "problem_rows true also lists the rows that were skipped or failed, and why."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "import_id": _ID,
                "problem_rows": {"type": "boolean"},
            },
            "required": ["import_id"],
        },
        "annotations": _READS,
        "scope": "leads:write",
    },
    {
        "name": "add_note",
        "title": "Add a note to a lead",
        "description": (
            "Adds a note to one lead, as this person. The lead's history shows which app "
            "sent it, and it can be undone for 7 days."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": _ID,
                "note": {"type": "string", "minLength": 1, "maxLength": 1000},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["lead_id", "note", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:notes",
    },
    {
        "name": "add_task",
        "title": "Add a task to a lead",
        "description": (
            "Adds a task or reminder to one lead: call back, WhatsApp, email, send a file, "
            "a meeting or other. It goes on the lead owner's list, shows which app sent it, "
            "and can be undone for 7 days."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": _ID,
                "kind": {"type": "string", "enum": list(TASK_KINDS)},
                "due": _WHEN,
                "title": {"type": "string", "maxLength": 200},
                "note": {"type": "string", "maxLength": 1000},
                "ends_at": _WHEN,
                "remind_before_minutes": {"type": "integer", "minimum": 0, "maximum": 1440},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["lead_id", "kind", "due", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:tasks",
    },
    {
        "name": "create_lead_import_upload",
        "title": "Get an address to upload a CSV of leads",
        "description": (
            "For many leads at once (up to 10,000): returns a one-time upload_url, good for "
            "15 minutes. PUT the CSV there as text/csv (its first row names the columns: name, "
            "phone, email, company, city, interest, stage, owner, source, external id), with no "
            "key needed. It queues as one import (the same file twice, once); read it with "
            "get_lead_import. Choices as for import_leads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 200},
                "side": {"type": "string", "enum": ["inbound", "cold"]},
                "assign": {"type": "string", "enum": ["rules", "none"]},
                "duplicates": {"type": "string", "enum": ["skip", "fill", "replace"]},
                "stage": {"type": "string", "maxLength": 40},
            },
        },
        # A new address each time; nothing changes until a file arrives.
        "annotations": {**_WRITES, "idempotentHint": False},
        "scope": "leads:write",
    },
    {
        "name": "update_lead",
        "title": "Change a lead's details",
        "description": (
            "Changes one lead's name, company, city, interest or language (fields: an object "
            "of those), as this person. Phone and email need a person's review. The history "
            "shows which app changed it, and Undo puts back what was there for 7 days."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": _ID,
                "fields": {
                    "type": "object",
                    "properties": {
                        name: {"type": ["string", "null"], "maxLength": 200}
                        for name in ("name", "company", "city", "interest", "language")
                    },
                },
                "expected_revision": {"type": "integer", "minimum": 1},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["lead_id", "fields", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:update",
    },
    {
        "name": "move_stage",
        "title": "Move a lead to another stage",
        "description": (
            "Moves one lead to another stage of its pipeline, with the reason, as this "
            "person. `step` is a stage key from list_leads' `stages`. Won, Lost and Junk "
            "need a person (needs_review). Some stages also ask for a reason_code or a "
            "next_action_at; the refusal says which. The history shows which app moved it, "
            "and it can be undone for 7 days unless the lead moved again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": _ID,
                "step": {"type": "string", "minLength": 1, "maxLength": 40},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                "reason_code": {"type": "string", "maxLength": 40},
                "next_action_at": _WHEN,
                "expected_revision": {"type": "integer", "minimum": 1},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["lead_id", "step", "reason", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:stage",
    },
    {
        "name": "assign_lead",
        "title": "Give a lead to a teammate",
        "description": (
            "Gives one lead to a teammate (person_id from the team), or with none to whom "
            "the lead rules pick; its open tasks go with it. Only an organisation's API key "
            "held by an owner or admin. Undone for 7 days unless it moved again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": _ID,
                "person_id": _ID,
                "expected_revision": {"type": "integer", "minimum": 1},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["lead_id", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:assign",
    },
    {
        "name": "update_leads",
        "title": "Change many leads at once",
        "description": (
            "One stage move (with the reason) or one assign for up to 1,000 leads: lead_ids, "
            "or a filter by stage. Above 5 leads, call it with preview first and send back "
            "its preview_sha. Each lead is its own change, undone for 7 days (one by one, "
            "or the whole request). Only an organisation's API key held by an owner or admin."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 1000},
                "filter": {
                    "type": "object",
                    "properties": {"stage": {"type": "string"}, "search": {"type": "string"}},
                    "required": ["stage"],
                },
                "change": {
                    "type": "object",
                    "properties": {
                        "stage": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "reason": {"type": "string", "maxLength": 500},
                                "reason_code": {"type": "string"},
                                "next_action_at": _WHEN,
                                "amount": {"type": "integer", "minimum": 1},
                            },
                            "required": ["step", "reason"],
                        },
                        "assign": {
                            "type": "object",
                            "properties": {"person_id": {"type": "string"}},
                        },
                    },
                },
                "request_id": _REQUEST,
                "preview": _PREVIEW,
                "preview_sha": {"type": "string", "minLength": 64, "maxLength": 64},
            },
            "required": ["change", "request_id"],
        },
        "annotations": _WRITES,
        "scope": ("leads:stage", "leads:assign"),
    },
    {
        "name": "list_tasks",
        "title": "List open tasks",
        "description": (
            "This person's open tasks as the Tasks list shows them (call-backs are in To "
            "Call): view is overdue, today (the default) or upcoming, with how many of "
            "each. An owner or admin may pass person (a person_id) for a seller's list."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["overdue", "today", "upcoming"]},
                "person": _ID,
            },
        },
        "annotations": _READS,
        "scope": "leads:read",
    },
    {
        "name": "complete_task",
        "title": "Mark a task done",
        "description": (
            "Marks one open task on a lead done, as this person. The lead's history shows "
            "which app did it, and it can be undone for 7 days (the task reopens) unless "
            "someone changed it since."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": _ID,
                "expected_revision": {"type": "integer", "minimum": 1},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["task_id", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:tasks",
    },
    {
        "name": "snooze_task",
        "title": "Snooze a task",
        "description": (
            "Moves one open task on a lead later: 15m, 1h, evening, tomorrow or week, as "
            "the app's own snooze does. It can be undone for 7 days (the due comes back) "
            "unless someone changed it since."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": _ID,
                "choice": {
                    "type": "string",
                    "enum": ["15m", "1h", "evening", "tomorrow", "week"],
                },
                "expected_revision": {"type": "integer", "minimum": 1},
                "request_id": _REQUEST,
                "preview": _PREVIEW,
            },
            "required": ["task_id", "choice", "request_id"],
        },
        "annotations": _WRITES,
        "scope": "leads:tasks",
    },
    {
        "name": "list_my_changes",
        "title": "Changes this app made",
        "description": (
            "The notes, tasks and stage moves this connection made in the last 30 days, "
            "newest first, and whether each can still be undone."
        ),
        "inputSchema": {"type": "object", "properties": {"lead_id": _ID}},
        "annotations": _READS,
        "scope": ("leads:notes", "leads:tasks", "leads:stage", "leads:assign"),
    },
    {
        "name": "undo_change",
        "title": "Undo a change this app made",
        "description": (
            "Undoes one change this connection made, within 7 days: a note stops showing, "
            "an open task is cancelled, a moved lead goes back. All stay in the lead's "
            "history. A task someone has changed since, or a lead moved again, is not "
            "undone."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"change_id": _ID, "request_id": _REQUEST},
            "required": ["change_id"],
        },
        "annotations": {**_WRITES, "destructiveHint": True},
        "scope": ("leads:notes", "leads:tasks", "leads:stage", "leads:assign"),
    },
    # Ask Dipak's lessons and coaching loop (ask_dipak/integration.py).
    *ask_dipak.TOOLS,
    # A seller's call uploaded by an organisation's key (integrations/recordings_api.py).
    *recordings_api.TOOLS,
    # The admin primitives: the workspace, invites and roles, Archive, Bin and reassign
    # (integrations/admin_api.py; owner, 17 Nov 2026).
    *admin_api.TOOLS,
)
_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _allowed(tool: dict[str, Any], scopes: frozenset[str]) -> bool:
    need = tool["scope"]
    if need is None:
        return True
    return need in scopes if isinstance(need, str) else bool(scopes.intersection(need))


def listed(scopes: frozenset[str]) -> list[dict[str, Any]]:
    """The tools this connection may use, as MCP describes them. The title goes in the
    annotations too: the Claude directory's tool check reads ``annotations.title``."""
    return [
        {
            **{key: value for key, value in tool.items() if key != "scope"},
            "annotations": {**tool["annotations"], "title": tool["title"]},
        }
        for tool in TOOLS
        if _allowed(tool, scopes)
    ]


def _needs(tool: dict[str, Any]) -> list[str]:
    need = tool["scope"]
    return [] if need is None else [need] if isinstance(need, str) else list(need)


def _connection(reader: Reader) -> bool:
    """A person's connected app (ChatGPT, Claude, Pulse), not an API key."""
    return reader.key.prefix.startswith("app ")


def _advertised(reader: Reader) -> bool:
    return reader.platform.advertise_writes and _connection(reader)


def tools_for(reader: Reader) -> list[dict[str, Any]]:
    """What tools/list shows. Until writes are advertised (plugin 1.1, after 1.0's review),
    exactly the tools the scopes allow, as before. Then a connected app also sees the tools
    its plan allows but it hasn't asked for, each with its securitySchemes, so it can ask
    for that scope when it needs it."""
    if not _advertised(reader):
        return listed(reader.key.scopes)
    shown = []
    for tool in TOOLS:
        needs = _needs(tool)
        if not (_allowed(tool, reader.key.scopes) or all(reader.tier.allows(s) for s in needs)):
            continue
        shown.append(
            {
                **{key: value for key, value in tool.items() if key != "scope"},
                "annotations": {**tool["annotations"], "title": tool["title"]},
                "securitySchemes": [{"type": "oauth2", "scopes": needs}],
            }
        )
    return shown


def _challenge(reader: Reader, tool: dict[str, Any]) -> dict[str, Any] | None:
    """A tool whose scope this connection lacks: the MCP answer that asks the app to
    connect again for exactly that scope (or, past the plan, the plain refusal)."""
    if not _advertised(reader) or _allowed(tool, reader.key.scopes):
        return None
    needs = _needs(tool)
    missing = [scope for scope in needs if scope not in reader.key.scopes]
    beyond = [scope for scope in missing if not reader.tier.allows(scope)]
    if beyond:
        text = tiers.not_included(reader.platform, beyond[0])
        return {"content": [{"type": "text", "text": text}], "isError": True}
    words = ", ".join(tiers.LABELS.get(scope, scope).lower() for scope in missing)
    metadata = f"{reader.resource or ''}/.well-known/oauth-protected-resource/v1/mcp"
    return {
        "content": [
            {
                "type": "text",
                "text": f"Sales X-Ray needs your OK to {words}. Connect again to allow it.",
            }
        ],
        "isError": True,
        "_meta": {
            "mcp/www_authenticate": [
                f'Bearer error="insufficient_scope", scope="{" ".join(missing)}", '
                f'resource_metadata="{metadata}", '
                f'error_description="This needs {" ".join(missing)}."'
            ]
        },
    }


def _uuid(args: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(str(args.get(name, "")))
    except ValueError:
        raise ApiError(422, "argument", f"{name} must be an id from a list.") from None


def _call_title(call: dict[str, Any]) -> str:
    return str(call.get("title") or f"Call on {str(call['created_at'])[:10]}")


def _lead_url(reader: Reader, lead_id: str) -> str:
    return f"{reader.base}/leads?lead={lead_id}" if reader.base else ""


async def _search_leads(reader: Reader, query: str) -> list[dict[str, Any]]:
    """Lead Desk matches one phrase; a longer question falls back to its longest word."""
    tries = [query[:80]]
    words = sorted(query.split(), key=len, reverse=True)
    if len(words) > 1 and len(words[0]) >= 3:
        tries.append(words[0][:80])
    for text in tries:
        try:
            page = await reader.leads(None, 0, SEARCH_LIMIT, search=text)
        except ApiError as error:
            if error.code == "organisation_only":  # Personal keeps no leads
                return []
            raise
        if page["leads"]:
            return list(page["leads"])
    return []


async def search(reader: Reader, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not 0 < len(query) <= 200:
        raise ApiError(422, "argument", "query must be 1 to 200 characters.")
    if not any(scope in reader.key.scopes for scope in _SEARCHABLE):
        raise ApiError(403, "scope_missing", "This key has neither calls:read nor leads:read.")
    words = query.casefold().split()
    results: list[dict[str, str]] = []
    if "calls:read" in reader.key.scopes:
        for call in (await reader.calls(None))["calls"]:
            title = _call_title(call)
            haystack = f"{title} {str(call['created_at'])[:10]}".casefold()
            if all(word in haystack for word in words):
                results.append(
                    {"id": f"call:{call['id']}", "title": title, "url": call["open_url"] or ""}
                )
    if "leads:read" in reader.key.scopes:
        for lead in await _search_leads(reader, query):
            parts = (lead.get("name"), lead.get("company"), lead.get("stage_label"))
            lead_id = str(lead["lead_id"])
            results.append(
                {
                    "id": f"lead:{lead_id}",
                    "title": " · ".join(str(part) for part in parts if part),
                    "url": _lead_url(reader, lead_id),
                }
            )
    return {"results": results[:SEARCH_LIMIT]}


async def fetch(reader: Reader, args: dict[str, Any]) -> dict[str, Any]:
    raw = str(args.get("id") or "")
    kind, _, ident = raw.partition(":")
    try:
        key = UUID(ident)
    except ValueError:
        raise ApiError(422, "argument", "id must be one from search.") from None
    if kind == "call":
        call = await reader.call(key)
        body = {
            "date": call["created_at"],
            "length_seconds": call["duration_seconds"],
            "report_ready": call["has_report"],
            "facts": call.get("facts"),
        }
        return {
            "id": raw,
            "title": _call_title(call),
            "text": json.dumps(body, ensure_ascii=False, default=str),
            "url": call["open_url"] or "",
            "metadata": {"kind": "call", "report_ready": call["has_report"]},
        }
    if kind == "lead":
        detail = await reader.lead(key)
        lead = detail["lead"]
        body = {
            "lead": lead,
            "phone": detail.get("phone"),
            "email": detail.get("email"),
            "fields": detail.get("fields"),
            "history": list(detail.get("events") or [])[:SEARCH_LIMIT],
        }
        return {
            "id": raw,
            "title": str(lead.get("name") or "Lead"),
            "text": json.dumps(body, ensure_ascii=False, default=str),
            "url": _lead_url(reader, str(lead["lead_id"])),
            "metadata": {"kind": "lead", "stage": lead.get("stage_label")},
        }
    raise ApiError(422, "argument", "id must be one from search.")


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "search":
        return await search(reader, args)
    if name == "fetch":
        return await fetch(reader, args)
    if name == "whoami":
        return await reader.me()
    if name == "list_calls":
        before = args.get("before")
        return await reader.calls(_uuid(args, "before") if before else None)
    if name == "get_call":
        return await reader.call(_uuid(args, "call_id"))
    if name == "call_facts":
        return await reader.facts(_uuid(args, "call_id"))
    if name == "list_team":
        return await reader.team()
    if name == "analysis_time":
        return await reader.analysis_time(team=args.get("team") is True)
    if name == "list_leads":
        offset = args.get("offset", 0)
        if not isinstance(offset, int) or isinstance(offset, bool):
            raise ApiError(422, "argument", "offset must be a whole number.")
        stage = args.get("stage")
        return await reader.leads(stage if isinstance(stage, str) else None, offset)
    if name == "get_lead":
        return await reader.lead(_uuid(args, "lead_id"))
    if name == "list_duplicates":
        return await reader.duplicates()
    if name == "get_duplicate":
        return await reader.duplicate(_uuid(args, "pair_id"))
    if name == "add_lead":
        fields = {key: args.get(key) for key in _BY_NAME["add_lead"]["inputSchema"]["properties"]}
        try:
            body = NewLeadBody(**{k: v for k, v in fields.items() if v is not None})
        except ValueError:
            raise ApiError(422, "argument", "Lead fields must be short text.") from None
        answer, _ = await reader.add_lead(body)
        return answer
    if name == "import_leads":
        import_fields = ("leads", "name", "side", "assign", "duplicates")
        request_id = args.get("request_id")
        body = _body(
            lead_imports.ImportBody,
            {key: value for key, value in args.items() if key != "request_id"},
            import_fields,
        )
        if len(body.leads) > 250:
            raise ApiError(422, "argument", "Send up to 250 leads per call.")
        door = await reader.import_door()
        try:
            answer, _ = await lead_imports.create(
                reader.session,
                door,
                body,
                idempotency_key=request_id if isinstance(request_id, str) else None,
            )
        except lead_imports.ImportRefused as refusal:
            raise ApiError(refusal.status, refusal.code, refusal.message) from None
        return answer
    if name == "create_lead_import_upload":
        choices = _body(
            UploadBody, args, ("name", "side", "assign", "duplicates", "pipeline", "stage")
        )
        return await reader.lead_import_upload(choices)
    if name == "update_lead":
        change = _body(
            LeadUpdateBody, args, ("fields", "expected_revision", "request_id", "preview")
        )
        answer, _ = await reader.update_lead(_uuid(args, "lead_id"), change)
        return answer
    if name == "get_lead_import":
        door = await reader.import_door()
        job = await lead_imports.find(
            reader.session,
            door,
            _uuid(args, "import_id"),
            every_door=reader.caller.sees_team,
        )
        if job is None:
            raise ApiError(404, "import_missing", "No such import here.")
        answer = await lead_imports.view(reader.session, job)
        if args.get("problem_rows") is True:
            problems = []
            for outcome in ("skipped", "failed"):
                page = await lead_imports.rows(reader.session, job, outcome=outcome, limit=100)
                problems += page["rows"]
            answer["problem_rows"] = sorted(problems, key=lambda item: item["row"])[:200]
        return answer
    if name == "add_note":
        note = _body(NoteBody, args, ("note", "request_id", "preview"))
        answer, _ = await reader.add_note(_uuid(args, "lead_id"), note)
        return answer
    if name == "add_task":
        task_fields = (
            "kind",
            "due",
            "title",
            "note",
            "ends_at",
            "remind_before_minutes",
            "request_id",
            "preview",
        )
        task = _body(TaskBody, args, task_fields)
        answer, _ = await reader.add_task(_uuid(args, "lead_id"), task)
        return answer
    if name == "move_stage":
        stage_fields = (
            "step",
            "reason",
            "reason_code",
            "next_action_at",
            "expected_revision",
            "request_id",
            "preview",
        )
        move = _body(StageBody, args, stage_fields)
        answer, _ = await reader.move_stage(_uuid(args, "lead_id"), move)
        return answer
    if name == "assign_lead":
        giving = _body(
            AssignBody, args, ("person_id", "expected_revision", "request_id", "preview")
        )
        answer, _ = await reader.assign_lead(_uuid(args, "lead_id"), giving)
        return answer
    if name == "update_leads":
        many = _body(
            BulkBody,
            args,
            ("lead_ids", "filter", "change", "request_id", "preview", "preview_sha"),
        )
        answer, _ = await reader.bulk(many)
        return answer
    if name == "list_tasks":
        person = _uuid(args, "person") if args.get("person") else None
        return await reader.tasks(str(args.get("view") or "today"), person)
    if name == "complete_task":
        finished = _body(TaskDoneBody, args, ("expected_revision", "request_id", "preview"))
        answer, _ = await reader.task_done(_uuid(args, "task_id"), finished)
        return answer
    if name == "snooze_task":
        snoozed = _body(
            TaskSnoozeBody, args, ("choice", "expected_revision", "request_id", "preview")
        )
        answer, _ = await reader.task_snooze(_uuid(args, "task_id"), snoozed)
        return answer
    if name == "list_my_changes":
        return await reader.changes(_uuid(args, "lead_id") if args.get("lead_id") else None)
    if name == "undo_change":
        undo = _body(UndoBody, args, ("request_id",))
        return await reader.undo_change(_uuid(args, "change_id"), undo)
    if name in coaching_api.NAMES:
        return await coaching_api.run_tool(reader, name, args)
    if name in reports_api.NAMES:
        return await reports_api.run_tool(reader, name, args)
    if name in ask_dipak.NAMES:
        return await ask_dipak.run_tool(reader, name, args)
    if name in recordings_api.NAMES:
        return await recordings_api.run_tool(reader, name, args)
    if name in admin_api.NAMES:
        return await admin_api.run_tool(reader, name, args)
    raise KeyError(name)


def _body(model: Any, args: dict[str, Any], fields: tuple[str, ...]) -> Any:
    """Only the fields a tool takes; anything else is refused, never dropped."""
    extra = sorted(set(args) - set(fields) - {"lead_id", "change_id", "task_id"})
    if extra:
        raise ApiError(422, "field_not_allowed", f"Not a field this tool takes: {extra[0]}.")
    try:
        return model(**{key: args[key] for key in fields if args.get(key) is not None})
    except ValueError as error:
        first = error.errors()[0] if hasattr(error, "errors") else {}
        where = ".".join(str(part) for part in first.get("loc", ())) or "arguments"
        raise ApiError(422, "argument", f"{where}: {first.get('msg', 'not valid')}") from None


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
        return _reply(ident, {"tools": tools_for(reader)})
    if method == "tools/call":
        name = str(params.get("name", ""))
        raw_args = params.get("arguments")
        args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
        tool = _BY_NAME.get(name)
        if tool is None:
            return _fail(ident, -32602, f"Unknown tool: {name}")
        challenge = _challenge(reader, tool)
        if challenge is not None:
            return _reply(ident, challenge)
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

    async def challenge(request: Request) -> str:
        # RFC 9728 and MCP 2025-11-25: where to find Connect, and the scopes to ask for
        # (reading, and the lead writes once the owner lets connected apps write). The
        # metadata is on the host the assistant reached: mcp.salesxray.in, or the old address
        # for connections made there (2 Nov 2026).
        base = settings.sales_xray_host_origin(request.url.hostname) or ""
        async with ctx.sessions() as db:
            platform = await tiers.read_platform(db)
        return (
            f'resource_metadata="{base}/.well-known/oauth-protected-resource/v1/mcp", '
            f'scope="{connect_scopes(platform)}"'
        )

    async def refused(error: ApiError, request: Request) -> JSONResponse:
        headers = {"Cache-Control": "no-store"}
        if error.status == 401:
            invalid = ', error="invalid_token"' if error.code == "key_invalid" else ""
            headers["WWW-Authenticate"] = (
                f'Bearer realm="sales-xray", {await challenge(request)}{invalid}'
            )
        if error.retry_after is not None:
            headers["Retry-After"] = str(error.retry_after)
        return JSONResponse(
            {"error": {"code": error.code, "message": error.message}},
            status_code=error.status,
            headers=headers,
        )

    @router.post("")
    async def mcp(request: Request) -> Response:
        # Any Origin: bearer tokens only, never cookies (see the module docstring).
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
            return await refused(error, request)
        if answer is None:
            return Response(status_code=202)
        return JSONResponse(answer, headers={"Cache-Control": "no-store"})

    @router.get("")
    async def no_stream() -> Response:
        return Response(status_code=405, headers={"Allow": "POST"})

    application.include_router(router)
