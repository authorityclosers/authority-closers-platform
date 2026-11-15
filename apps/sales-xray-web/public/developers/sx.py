#!/usr/bin/env python3
"""sx: the Sales X-Ray command line and MCP server, on the public API (/v1/api).

Download: https://app.salesxray.in/developers/sx.py

One file, Python 3.10+ standard library only. Uses an API key made in Sales X-Ray
under Organisation -> Integrations; the key is read from SX_API_KEY (never a
command-line argument, so it stays out of shell history and process lists).

    export SX_API_KEY=sxk_live_...            # or sxk_test_... on staging
    export SX_API_BASE=https://api.salesxray.in/v1/api         # the default

    sx me                                     # the key's organisation and scopes
    sx calls [--before CALL_ID]               # calls, newest first, 50 a page
    sx facts CALL_ID                          # the facts found in one call
    sx reports [--saved] [--before CALL_ID]   # calls with a ready report, 50 a page
    sx report CALL_ID [--docx FILE | --transcript]     # one call's report, its Word
                                              # file, or its transcript (reports:read)
    sx coaching [--call CALL_ID | --team]     # Coaching: yours (as a person), one of
                                              # your calls, or the team's counts
    sx minutes [--team]                       # analysis time given, used and left
                                              # (calls:read; --team: each member's use)
    sx leads [--stage KEY|open] [--offset N]  # KEY: one of the stages each page lists
    sx lead LEAD_ID
    sx add-lead --name NAME [--phone P] [--email E] [--company C] [--city C]
                [--interest I] [--note N] [--external-id ID]
    sx note LEAD_ID TEXT [--request-id ID] [--preview]       # needs leads:notes
    sx task LEAD_ID --kind call_back|whatsapp|email|send_file|meeting|other
            --due 2026-10-27T10:00:00+05:30 [--title T] [--note N] [--ends AT]
            [--remind MINUTES] [--request-id ID] [--preview]  # needs leads:tasks
    sx stage LEAD_ID STEP --reason WHY [--reason-code CODE] [--next AT]
            [--request-id ID] [--preview]     # needs leads:stage; STEP: a stage key
                                              # from `sx leads`; Won, Lost and Junk
                                              # need a person; undone with `sx undo`
    sx tasks [--view overdue|today|upcoming] [--person PERSON_ID]   # open tasks
    sx done TASK_ID [--request-id ID] [--preview]                   # needs leads:tasks
    sx snooze TASK_ID 15m|1h|evening|tomorrow|week [--request-id ID] [--preview]
                                              # both undone with `sx undo`
    sx import-leads FILE.csv|FILE.json [--name NAME] [--side inbound|cold]
            [--assign rules|none] [--duplicates skip|fill|replace]
            [--per-import N] [--wait] [--failures OUT.csv]
                                              # many leads at once (needs leads:write):
                                              # filed in the background like a file
                                              # uploaded in the app, undone there in 48 h
    sx import LEAD_IMPORT_ID [--rows skipped|failed|created|updated]
    sx changes [--lead LEAD_ID]               # notes and tasks this key added (30 days)
    sx undo CHANGE_ID                         # within 7 days: a note stops showing,
                                              # an open task is cancelled
    sx assign LEAD_ID [--to PERSON_ID]        # give a lead to a teammate (none: the lead
                                              # rules); an owner's or admin's org key
    sx bulk (--ids FILE | --where-stage KEY) (--stage STEP --reason WHY | --assign
            PERSON_ID|rules) [--reason-code C] [--next AT] [--amount N] [--yes]
                                              # up to 1,000 leads; previews, applies with
                                              # --yes; an owner's or admin's org key
    sx undo-request REQUEST_ID                # undo every change one bulk request made
    sx dipak search [WORDS]                   # Ask Dipak: his 150 sales questions
    sx dipak lesson QUESTION_ID               # one lesson in Dipak's words (e.g. PB03)
    sx dipak improve [--skills a,b] [--objections c]   # his questions for a report's
                                              # weaknesses
    sx dipak missions | calls                 # needs coaching:read, as a person
    sx dipak team                             # every seller's missions (org key)
    sx dipak save|tick|active QUESTION_ID [--off]      # needs coaching:write
    sx dipak answer CALL_ID QUESTION_ID yes|no         # after a call
    sx upload FILE --seller EMAIL|PERSON_ID [--lead LEAD_ID] [--called-at AT]
            [--language en] [--wait]          # a seller's call, analysed as it arrives
                                              # (an organisation key with
                                              # recordings:write); the people on the
                                              # call must know it is recorded
    sx recording UPLOAD_ID                    # where an uploaded call is
    sx mcp                                    # an MCP server on stdio (for AI assistants)

A change sent again with the same --request-id changes nothing; without one, sx makes
a new one each time. Every change shows "via API key sxk_..." in the lead's history.

import-leads reads a CSV whose header names the fields (name, phone, email, company, city,
language, interest, stage, owner, source, external_id; other columns are left out) or a
JSON list of such objects. It sends up to --per-import rows (default 5,000) per import,
each with an Idempotency-Key made from the file, so running it again on the same file
creates nothing twice. --wait follows each import to the end and prints the totals;
--failures writes the rows that were skipped or failed, with why, to a CSV.

upload sends the file (up to 100 MB and 60 minutes) with its SHA-256, stating that the
people on the call know it is recorded; the call is then the seller's own, in their Calls.
--wait follows it until its report is ready (or it is held, with why) and prints where it
ended.

Output is JSON. Exit status 0 on success, 1 when the API refused (its error code and
message are printed), 2 on a usage or connection problem.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

DEFAULT_BASE = "https://api.salesxray.in/v1/api"
VERSION = "1.0.0"
TIMEOUT = 30
UPLOAD_TIMEOUT = 900
MAX_UPLOAD_BYTES = 100_000_000
# Where an uploaded call stops moving (GET /recordings/{id}).
SETTLED = ("report_ready", "held", "failed", "expired")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.status, self.code, self.message = status, code, message


Transport = Callable[[urllib.request.Request], tuple[int, bytes]]


def _urlopen(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        timeout = getattr(request, "sx_timeout", TIMEOUT)
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
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
        headers: dict[str, str] | None = None,
        raw: bytes | None = None,
    ) -> Any:
        clean = {k: v for k, v in (query or {}).items() if v is not None}
        url = self.base + path + ("?" + urllib.parse.urlencode(clean) if clean else "")
        data = raw if raw is not None else None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)  # noqa: S310
        request.add_header("Authorization", f"Bearer {self.key}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", f"sx/{VERSION}")
        if raw is not None:
            request.add_header("Content-Type", "application/octet-stream")
            request.sx_timeout = UPLOAD_TIMEOUT  # type: ignore[attr-defined]
        elif data is not None:
            request.add_header("Content-Type", "application/json")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
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

    def analysis_time(self, team: bool = False) -> Any:
        return self.call("GET", "/analysis-time/team" if team else "/analysis-time")

    def reports(self, saved: bool = False, before: str | None = None) -> Any:
        return self.call("GET", "/reports", {"saved": "true" if saved else None, "before": before})

    def report(self, call_id: str) -> Any:
        return self.call("GET", f"/calls/{_part(call_id)}/report")

    def transcript(self, call_id: str) -> Any:
        return self.call("GET", f"/calls/{_part(call_id)}/transcript")

    def coaching(self, call_id: str | None = None, team: bool = False) -> Any:
        if call_id:
            return self.call("GET", f"/coaching/calls/{_part(call_id)}")
        return self.call("GET", "/coaching/team" if team else "/coaching")

    def report_docx(self, call_id: str) -> bytes:
        """The report as a Word file: the bytes, not JSON."""
        url = f"{self.base}/calls/{_part(call_id)}/report.docx"
        request = urllib.request.Request(url, method="GET")  # noqa: S310
        request.add_header("Authorization", f"Bearer {self.key}")
        request.add_header("User-Agent", f"sx/{VERSION}")
        status, raw = self.transport(request)
        if not 200 <= status < 300:
            try:
                payload = json.loads(raw or b"null")
            except ValueError:
                payload = None
            error = (payload or {}).get("error", {}) if isinstance(payload, dict) else {}
            raise ApiError(status, error.get("code", "http_error"), error.get("message", ""))
        return raw

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

    def tasks(self, view: str | None = None, person: str | None = None) -> Any:
        return self.call("GET", "/tasks", {"view": view, "person": person})

    def task_action(self, task_id: str, action: str, **fields: Any) -> Any:
        body = {k: v for k, v in fields.items() if v is not None}
        path = f"/tasks/{urllib.parse.quote(task_id, safe='')}/{action}"
        return self.call("POST", path, body=body)

    def move_stage(self, lead_id: str, **fields: Any) -> Any:
        body = {k: v for k, v in fields.items() if v is not None}
        return self.call("POST", f"/leads/{urllib.parse.quote(lead_id, safe='')}/stage", body=body)

    def changes(self, lead_id: str | None = None) -> Any:
        return self.call("GET", "/changes", {"lead_id": lead_id})

    def import_leads(self, body: dict[str, Any], idempotency_key: str | None = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self.call("POST", "/leads/imports", body=body, headers=headers)

    def lead_import(self, import_id: str) -> Any:
        return self.call("GET", f"/leads/imports/{urllib.parse.quote(import_id, safe='')}")

    def lead_import_rows(
        self, import_id: str, outcome: str | None = None, after: int | None = None
    ) -> Any:
        path = f"/leads/imports/{urllib.parse.quote(import_id, safe='')}/rows"
        return self.call("GET", path, {"outcome": outcome, "after": after})

    def undo(self, change_id: str, request_id: str | None = None) -> Any:
        body = {"request_id": request_id} if request_id else {}
        return self.call(
            "POST", f"/changes/{urllib.parse.quote(change_id, safe='')}/undo", body=body
        )

    def assign(self, lead_id: str, **fields: Any) -> Any:
        body = {k: v for k, v in fields.items() if v is not None}
        return self.call("POST", f"/leads/{urllib.parse.quote(lead_id, safe='')}/assign", body=body)

    def bulk(self, body: dict[str, Any]) -> Any:
        return self.call(
            "POST", "/leads/bulk", body={k: v for k, v in body.items() if v is not None}
        )

    def undo_request(self, request_id: str) -> Any:
        return self.call("POST", "/changes/undo-request", body={"request_id": request_id})

    # Ask Dipak (/v1/api/ask-dipak): lessons with any key; missions with coaching:read
    # and coaching:write, which act as a person (a connected app's sxa_ token).
    def create_recording(self, **fields: Any) -> Any:
        body = {k: v for k, v in fields.items() if v is not None}
        return self.call("POST", "/recordings", body=body)

    def send_recording(self, upload_id: str, data: bytes) -> Any:
        return self.call(
            "PUT",
            f"/recordings/{urllib.parse.quote(upload_id, safe='')}/source",
            headers={
                "X-Source-SHA256": hashlib.sha256(data).hexdigest(),
                "X-Recording-Consent": "participants-informed",
            },
            raw=data,
        )

    def recording(self, upload_id: str) -> Any:
        return self.call("GET", f"/recordings/{urllib.parse.quote(upload_id, safe='')}")

    def dipak_search(self, words: str = "") -> Any:
        return self.call("GET", "/ask-dipak/lessons", {"q": words or None})

    def dipak_lesson(self, question_id: str) -> Any:
        return self.call("GET", f"/ask-dipak/lessons/{_part(question_id)}")

    def dipak_improve(self, skills: str | None = None, objections: str | None = None) -> Any:
        query = {"skills": skills, "objections": objections}
        return self.call("GET", "/ask-dipak/how-to-improve", query)

    def dipak_missions(self) -> Any:
        return self.call("GET", "/ask-dipak/missions")

    def dipak_team(self) -> Any:
        return self.call("GET", "/ask-dipak/team")

    def dipak_calls(self) -> Any:
        return self.call("GET", "/ask-dipak/calls")

    def dipak_switch(self, what: str, question_id: str, on: bool) -> Any:
        # what: saved, ticked or active.
        return self.call("PUT", f"/ask-dipak/{what}/{_part(question_id)}", body={"on": on})

    def dipak_answer(self, call_id: str, question_id: str, done: bool) -> Any:
        body = {"answers": [{"question_id": question_id, "done": done}]}
        return self.call("PUT", f"/ask-dipak/calls/{_part(call_id)}/check", body=body)


def _part(value: str) -> str:
    return urllib.parse.quote(value, safe="")


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
        "description": (
            "Leads in the organisation's Lead Desk, newest change first. Each answer lists "
            "the organisation's own stages (key and label) under stages; pass one key as "
            "stage for that stage alone, or open for every open lead."
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
        "name": "move_stage",
        "description": "Moves one lead to another stage, with the reason. step is a stage "
        "key from list_leads' stages; Won, Lost and Junk need a person. It can be undone "
        "for 7 days unless the lead moved again. Needs leads:stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "step": {"type": "string"},
                "reason": {"type": "string", "minLength": 1, "maxLength": 500},
                "reason_code": {"type": "string"},
                "next_action_at": {
                    "type": "string",
                    "description": "e.g. 2026-10-27T10:00:00+05:30",
                },
                "expected_revision": {"type": "integer"},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["lead_id", "step", "reason", "request_id"],
        },
    },
    {
        "name": "list_my_changes",
        "description": "Notes, tasks and stage moves this key made in the last 30 days, "
        "and whether each can still be undone.",
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


IMPORT_FIELDS = (
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
TOOLS += [
    {
        "name": "import_leads",
        "description": (
            "Imports up to 250 leads per call, filed in the background like a file uploaded "
            "in Sales X-Ray: duplicates (same phone, or same email without one) are not new "
            "leads, and the import can be undone in the app for 48 hours. Answers with an "
            "import id for get_lead_import. For thousands, call again with the next 250 and "
            "a new request_id; the same request_id with the same leads changes nothing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "leads": {
                    "type": "array",
                    "maxItems": 250,
                    "items": {
                        "type": "object",
                        "properties": {name: {"type": "string"} for name in IMPORT_FIELDS},
                    },
                },
                "name": {"type": "string"},
                "side": {"type": "string", "enum": ["inbound", "cold"]},
                "assign": {"type": "string", "enum": ["rules", "none"]},
                "duplicates": {"type": "string", "enum": ["skip", "fill", "replace"]},
                "request_id": {"type": "string"},
            },
            "required": ["leads"],
        },
    },
    {
        "name": "get_lead_import",
        "description": "Where an import stands, with the rows skipped or failed and why "
        "when problem_rows is true.",
        "inputSchema": {
            "type": "object",
            "properties": {"import_id": {"type": "string"}, "problem_rows": {"type": "boolean"}},
            "required": ["import_id"],
        },
    },
    {
        "name": "analysis_time",
        "description": "The workspace's analysis time: given, used and left, in seconds, and "
        "the longest call. Time only. team: what each member used (owners and admins).",
        "inputSchema": {"type": "object", "properties": {"team": {"type": "boolean"}}},
    },
    {
        "name": "list_tasks",
        "description": "Open tasks as the Tasks list shows them: view overdue, today or "
        "upcoming, with how many of each; person for an owner's look at a seller.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "view": {"type": "string", "enum": ["overdue", "today", "upcoming"]},
                "person": {"type": "string"},
            },
        },
    },
    {
        "name": "complete_task",
        "description": "Marks one open task on a lead done; undone for 7 days with "
        "undo_change. Needs leads:tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["task_id", "request_id"],
        },
    },
    {
        "name": "snooze_task",
        "description": "Moves one open task on a lead later (15m, 1h, evening, tomorrow, "
        "week); undone for 7 days with undo_change. Needs leads:tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "choice": {
                    "type": "string",
                    "enum": ["15m", "1h", "evening", "tomorrow", "week"],
                },
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["task_id", "choice", "request_id"],
        },
    },
    {
        "name": "assign_lead",
        "description": "Gives one lead to a teammate (person_id), or with none to whom the "
        "lead rules pick. An owner's or admin's organisation key with leads:assign.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_id": {"type": "string"},
                "person_id": {"type": "string"},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
            },
            "required": ["lead_id", "request_id"],
        },
    },
    {
        "name": "update_leads",
        "description": "One stage move (step, reason) or one assign (person_id) for up to "
        "1,000 leads: lead_ids or a filter {stage}. Above 5 leads, preview first and send "
        "its preview_sha. An owner's or admin's organisation key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lead_ids": {"type": "array", "items": {"type": "string"}},
                "filter": {"type": "object"},
                "change": {"type": "object"},
                "request_id": {"type": "string", "minLength": 8, "maxLength": 80},
                "preview": {"type": "boolean"},
                "preview_sha": {"type": "string"},
            },
            "required": ["change", "request_id"],
        },
    },
]


_CALL_ID = {"type": "string", "description": "A call id from list_calls or list_reports"}
TOOLS += [
    {
        "name": "list_reports",
        "description": "Calls with a ready report, newest first, 50 a page, and whether "
        "each is in the key's person's Saved reports. saved=true for Saved reports only; "
        "before=<the last id> for the next page. Needs reports:read.",
        "inputSchema": {
            "type": "object",
            "properties": {"saved": {"type": "boolean"}, "before": {"type": "string"}},
        },
    },
    {
        "name": "get_report",
        "description": "One call's report as the app shows it: summary, verdict, "
        "strengths, what to improve, next action, objections, closing and each skill's "
        "state. Sensitive parts are withheld; never an official score.",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": _CALL_ID},
            "required": ["call_id"],
        },
    },
    {
        "name": "get_transcript",
        "description": "One call's transcript, segment by segment with times in "
        "milliseconds. Sensitive parts are withheld.",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": _CALL_ID},
            "required": ["call_id"],
        },
    },
    {
        "name": "my_coaching",
        "description": "This person's Coaching from their analysed calls: the skills to "
        "work on and each call's state. A connected app acting as a person only.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "call_coaching",
        "description": "The coaching for one of this person's own calls.",
        "inputSchema": {
            "type": "object",
            "properties": {"call_id": _CALL_ID},
            "required": ["call_id"],
        },
    },
    {
        "name": "team_coaching",
        "description": "The team's Coaching: how often each recommendation came up, as "
        "counts, and the reps who chose to share. Owners, admins and organisation keys.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def read_leads(path: str) -> list[dict[str, str]]:
    """The leads in a CSV (a header row naming the fields) or a JSON list of objects; only
    the fields an import takes, as text, empty cells left out."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        if path.lower().endswith(".json"):
            loaded = json.load(handle)
            items = loaded.get("leads") if isinstance(loaded, dict) else loaded
            if not isinstance(items, list):
                raise ValueError("The JSON file holds a list of leads.")
        else:
            items = list(csv.DictReader(handle))
    leads = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Each lead is an object of fields.")
        lead = {}
        for key, value in item.items():
            field = str(key or "").strip().lower().replace(" ", "_")
            field = "external_id" if field in ("id", "external_id", "externalid") else field
            text = "" if value is None else str(value).strip()
            if field in IMPORT_FIELDS and text:
                lead[field] = text
        leads.append(lead)
    if not leads:
        raise ValueError("The file has no leads.")
    return leads


def import_file(
    client: Client,
    path: str,
    *,
    name: str | None = None,
    side: str = "inbound",
    assign: str = "rules",
    duplicates: str = "skip",
    per_import: int = 5000,
    wait: bool = False,
    failures: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Send a file's leads as one or more imports and, with wait, follow them to the end."""
    leads = read_leads(path)
    per_import = max(1, min(per_import, 10_000))
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    title = name or os.path.basename(path)[:200]
    sent = []
    for part, first in enumerate(range(0, len(leads), per_import)):
        body = {
            "name": title,
            "leads": leads[first : first + per_import],
            "side": side,
            "assign": assign,
            "duplicates": duplicates,
        }
        key = f"sx-{digest[:40]}-{part}"
        for attempt in range(8):
            try:
                answer = client.import_leads(body, key)
                break
            except ApiError as error:
                # Five imports already waiting here, or a busy minute: wait and try again.
                if error.status != 429 or attempt == 7:
                    raise
                sleep(min(60, 5 * 2**attempt))
        sent.append({"first_row": first, **answer})
    if wait:
        for index, item in enumerate(sent):
            while item.get("status") in ("queued", "running"):
                sleep(2)
                item = {"first_row": item["first_row"], **client.lead_import(item["id"])}
            sent[index] = item
    totals = {
        key: sum(int(item.get(key, 0)) for item in sent)
        for key in ("total", "created", "updated", "skipped", "failed")
    }
    if wait and failures:
        with open(failures, "w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(["row", "external_id", "outcome", "reason"])
            for item in sent:
                for outcome in ("skipped", "failed"):
                    after = None
                    while True:
                        page = client.lead_import_rows(item["id"], outcome, after)
                        for row in page["rows"]:
                            writer.writerow(
                                [
                                    item["first_row"] + row["row"] + 1,
                                    row.get("external_id") or "",
                                    row["outcome"],
                                    row.get("reason") or "",
                                ]
                            )
                        after = page.get("next_after")
                        if after is None:
                            break
    return {"imports": sent, "totals": totals}


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
    if name == "move_stage":
        moves = ("step", "reason", "reason_code", "next_action_at", "expected_revision")
        return client.move_stage(
            str(args["lead_id"]),
            request_id=str(args["request_id"]),
            preview=bool(args.get("preview", False)),
            **{key: args.get(key) for key in moves},
        )
    if name == "import_leads":
        body = {
            key: args[key]
            for key in ("leads", "name", "side", "assign", "duplicates")
            if key in args
        }
        return client.import_leads(body, args.get("request_id") or _request_id())
    if name == "analysis_time":
        return client.analysis_time(args.get("team") is True)
    if name == "list_tasks":
        return client.tasks(args.get("view"), args.get("person"))
    if name == "assign_lead":
        return client.assign(
            str(args["lead_id"]),
            person_id=args.get("person_id"),
            request_id=str(args["request_id"]),
            preview=bool(args.get("preview", False)),
        )
    if name == "update_leads":
        keys = ("lead_ids", "filter", "change", "request_id", "preview", "preview_sha")
        return client.bulk({key: args.get(key) for key in keys})
    if name in ("complete_task", "snooze_task"):
        return client.task_action(
            str(args["task_id"]),
            "done" if name == "complete_task" else "snooze",
            choice=args.get("choice"),
            request_id=str(args["request_id"]),
            preview=bool(args.get("preview", False)),
        )
    if name == "get_lead_import":
        answer = client.lead_import(str(args["import_id"]))
        if args.get("problem_rows") is True:
            problems = []
            for outcome in ("skipped", "failed"):
                problems += client.lead_import_rows(str(args["import_id"]), outcome)["rows"]
            answer["problem_rows"] = sorted(problems, key=lambda row: row["row"])[:200]
        return answer
    if name == "list_reports":
        return client.reports(args.get("saved") is True, args.get("before"))
    if name == "get_report":
        return client.report(str(args["call_id"]))
    if name == "get_transcript":
        return client.transcript(str(args["call_id"]))
    if name == "my_coaching":
        return client.coaching()
    if name == "call_coaching":
        return client.coaching(str(args["call_id"]))
    if name == "team_coaching":
        return client.coaching(team=True)
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


def upload_call(
    client: Client,
    path: str,
    *,
    seller: str,
    lead: str | None = None,
    called_at: str | None = None,
    language: str | None = None,
    wait: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    wait_seconds: float = 900,
) -> Any:
    """Send one call for a seller; with ``wait``, follow it until it settles."""
    size = os.path.getsize(path)
    if not 0 < size <= MAX_UPLOAD_BYTES:
        raise ValueError("Choose an audio or video file up to 100 MB.")
    with open(path, "rb") as source:
        data = source.read()
    who = {"seller_email": seller} if "@" in seller else {"seller_id": seller}
    opened = client.create_recording(
        **who,
        lead_id=lead,
        called_at=called_at,
        report_language=language,
        file_name=os.path.basename(path)[:200] or None,
    )
    state = client.send_recording(opened["id"], data)
    waited = 0.0
    while wait and state.get("state") not in SETTLED and waited < wait_seconds:
        sleep(5)
        waited += 5
        state = client.recording(opened["id"])
    return state


def _request_id() -> str:
    return f"sx-{uuid.uuid4().hex}"


def bulk_change(client: Client, args: Any) -> Any:
    """`sx bulk`: preview the change, then (with --yes, or 5 leads or fewer) apply exactly
    what the preview showed. Without --yes above 5 leads, it prints the preview only."""
    body: dict[str, Any] = {"request_id": args.request_id or _request_id()}
    if args.ids:
        with open(args.ids, encoding="utf-8") as handle:
            body["lead_ids"] = [line.strip() for line in handle if line.strip()]
    else:
        body["filter"] = {"stage": args.where_stage}
    if args.stage:
        stage = {
            "step": args.stage,
            "reason": args.reason,
            "reason_code": args.reason_code,
            "next_action_at": args.next,
            "amount": args.amount,
        }
        body["change"] = {"stage": {k: v for k, v in stage.items() if v is not None}}
    else:
        body["change"] = {"assign": {} if args.assign == "rules" else {"person_id": args.assign}}
    shown = client.bulk({**body, "preview": True})
    if shown.get("leads", 0) > 5 and not args.yes:
        return {**shown, "next": "Check the preview, then run again with --yes."}
    return client.bulk({**body, "preview_sha": shown.get("preview_sha")})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sx", description="Sales X-Ray from the command line.")
    parser.add_argument("--version", action="version", version=f"sx {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("me")
    calls = commands.add_parser("calls")
    calls.add_argument("--before")
    facts = commands.add_parser("facts")
    facts.add_argument("call_id")
    reports = commands.add_parser("reports")
    reports.add_argument("--saved", action="store_true")
    reports.add_argument("--before")
    report = commands.add_parser("report")
    report.add_argument("call_id")
    report_as = report.add_mutually_exclusive_group()
    report_as.add_argument("--docx", metavar="FILE")
    report_as.add_argument("--transcript", action="store_true")
    coaching = commands.add_parser("coaching")
    coaching_of = coaching.add_mutually_exclusive_group()
    coaching_of.add_argument("--call", metavar="CALL_ID")
    coaching_of.add_argument("--team", action="store_true")
    minutes = commands.add_parser("minutes")
    minutes.add_argument("--team", action="store_true")
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
    stage = commands.add_parser("stage")
    stage.add_argument("lead_id")
    stage.add_argument("step")
    stage.add_argument("--reason", required=True)
    for name in ("reason-code", "next", "request-id"):
        stage.add_argument(f"--{name}")
    stage.add_argument("--preview", action="store_true")
    task_list = commands.add_parser("tasks")
    task_list.add_argument("--view", choices=["overdue", "today", "upcoming"])
    task_list.add_argument("--person")
    finish = commands.add_parser("done")
    finish.add_argument("task_id")
    finish.add_argument("--request-id")
    finish.add_argument("--preview", action="store_true")
    later = commands.add_parser("snooze")
    later.add_argument("task_id")
    later.add_argument("choice", choices=["15m", "1h", "evening", "tomorrow", "week"])
    later.add_argument("--request-id")
    later.add_argument("--preview", action="store_true")
    imports = commands.add_parser("import-leads")
    imports.add_argument("file")
    imports.add_argument("--name")
    imports.add_argument("--side", choices=["inbound", "cold"], default="inbound")
    imports.add_argument("--assign", choices=["rules", "none"], default="rules")
    imports.add_argument("--duplicates", choices=["skip", "fill", "replace"], default="skip")
    imports.add_argument("--per-import", type=int, default=5000)
    imports.add_argument("--wait", action="store_true")
    imports.add_argument("--failures")
    one_import = commands.add_parser("import")
    one_import.add_argument("import_id")
    one_import.add_argument(
        "--rows", choices=["created", "updated", "skipped", "failed", "waiting"]
    )
    changes = commands.add_parser("changes")
    changes.add_argument("--lead")
    undo = commands.add_parser("undo")
    undo.add_argument("change_id")
    undo.add_argument("--request-id")
    undo_all = commands.add_parser("undo-request")
    undo_all.add_argument("request_id")
    give = commands.add_parser("assign")
    give.add_argument("lead_id")
    give.add_argument("--to", help="a person_id from `sx team`; leave out for the lead rules")
    give.add_argument("--request-id")
    give.add_argument("--preview", action="store_true")
    many = commands.add_parser("bulk")
    which = many.add_mutually_exclusive_group(required=True)
    which.add_argument("--ids", help="a file of lead ids, one a line")
    which.add_argument("--where-stage", help="every lead at this stage key (or open)")
    what = many.add_mutually_exclusive_group(required=True)
    what.add_argument("--stage", help="move them to this stage key")
    what.add_argument("--assign", help="give them to this person_id, or `rules`")
    many.add_argument("--reason")
    many.add_argument("--reason-code")
    many.add_argument("--next")
    many.add_argument("--amount", type=int)
    many.add_argument("--request-id")
    many.add_argument("--yes", action="store_true", help="apply after the preview")
    dipak = commands.add_parser("dipak", help="Ask Dipak: lessons and Next-call missions")
    asks = dipak.add_subparsers(dest="ask", required=True)
    search = asks.add_parser("search")
    search.add_argument("words", nargs="*")
    asks.add_parser("lesson").add_argument("question_id")
    improve = asks.add_parser("improve")
    improve.add_argument("--skills")
    improve.add_argument("--objections")
    for name in ("missions", "team", "calls"):
        asks.add_parser(name)
    for name in ("save", "tick", "active"):
        switch = asks.add_parser(name)
        switch.add_argument("question_id")
        switch.add_argument("--off", action="store_true")
    answer = asks.add_parser("answer")
    answer.add_argument("call_id")
    answer.add_argument("question_id")
    answer.add_argument("done", choices=("yes", "no"))
    upload = commands.add_parser("upload", help="a seller's call, analysed as it arrives")
    upload.add_argument("file")
    upload.add_argument("--seller", required=True)
    upload.add_argument("--lead")
    upload.add_argument("--called-at")
    upload.add_argument("--language", choices=["en", "hi-Deva+en", "mr-Deva+en"])
    upload.add_argument("--wait", action="store_true")
    commands.add_parser("recording").add_argument("upload_id")
    commands.add_parser("mcp")
    return parser


def _report(client: Client, args: argparse.Namespace) -> Any:
    if args.docx:
        document = client.report_docx(args.call_id)
        with open(args.docx, "wb") as handle:
            handle.write(document)
        return {"saved_to": args.docx, "bytes": len(document)}
    if args.transcript:
        return client.transcript(args.call_id)
    return client.report(args.call_id)


def _dipak(client: Client, args: argparse.Namespace) -> Any:
    if args.ask == "search":
        return client.dipak_search(" ".join(args.words))
    if args.ask == "lesson":
        return client.dipak_lesson(args.question_id)
    if args.ask == "improve":
        return client.dipak_improve(args.skills, args.objections)
    if args.ask == "missions":
        return client.dipak_missions()
    if args.ask == "team":
        return client.dipak_team()
    if args.ask == "calls":
        return client.dipak_calls()
    if args.ask == "answer":
        return client.dipak_answer(args.call_id, args.question_id, args.done == "yes")
    what = {"save": "saved", "tick": "ticked", "active": "active"}[args.ask]
    return client.dipak_switch(what, args.question_id, not args.off)


def main(
    argv: list[str] | None = None,
    environ: dict[str, str] | None = None,
    transport: Transport = _urlopen,
    sleep: Callable[[float], None] = time.sleep,
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
        elif args.command == "reports":
            out = client.reports(args.saved, args.before)
        elif args.command == "report":
            out = _report(client, args)
        elif args.command == "coaching":
            out = client.coaching(args.call, args.team)
        elif args.command == "minutes":
            out = client.analysis_time(args.team)
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
        elif args.command == "stage":
            out = client.move_stage(
                args.lead_id,
                step=args.step,
                reason=args.reason,
                reason_code=args.reason_code,
                next_action_at=args.next,
                request_id=args.request_id or _request_id(),
                preview=args.preview,
            )
        elif args.command == "tasks":
            out = client.tasks(args.view, args.person)
        elif args.command in ("done", "snooze"):
            out = client.task_action(
                args.task_id,
                args.command,
                choice=getattr(args, "choice", None),
                request_id=args.request_id or _request_id(),
                preview=args.preview,
            )
        elif args.command == "import-leads":
            out = import_file(
                client,
                args.file,
                name=args.name,
                side=args.side,
                assign=args.assign,
                duplicates=args.duplicates,
                per_import=args.per_import,
                wait=args.wait or bool(args.failures),
                failures=args.failures,
                sleep=sleep,
            )
        elif args.command == "import":
            out = (
                client.lead_import_rows(args.import_id, args.rows)
                if args.rows
                else client.lead_import(args.import_id)
            )
        elif args.command == "changes":
            out = client.changes(args.lead)
        elif args.command == "undo":
            out = client.undo(args.change_id, args.request_id)
        elif args.command == "undo-request":
            out = client.undo_request(args.request_id)
        elif args.command == "assign":
            out = client.assign(
                args.lead_id,
                person_id=args.to,
                request_id=args.request_id or _request_id(),
                preview=args.preview,
            )
        elif args.command == "bulk":
            out = bulk_change(client, args)
        elif args.command == "dipak":
            out = _dipak(client, args)
        elif args.command == "upload":
            out = upload_call(
                client,
                args.file,
                seller=args.seller,
                lead=args.lead,
                called_at=args.called_at,
                language=args.language,
                wait=args.wait,
                sleep=sleep,
            )
        elif args.command == "recording":
            out = client.recording(args.upload_id)
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
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    except OSError as error:
        print(f"Could not reach Sales X-Ray: {type(error).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
