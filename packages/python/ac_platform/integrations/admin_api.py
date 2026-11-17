"""An organisation's admin primitives for API keys and MCP (owner, 17 Nov 2026: "every
base-level primitive in CLI, MCP and API"; the CLI is scripts/data-changes/admin.py, the
notes docs/product/lead-desk/admin-cli.md).

- GET  /workspace                 the workspace: name, members by role, pending invites, lead
                                  counts (on the desk, Archived, Bin, waiting for an owner) and
                                  the owner's AI-apps switch (team:read; an organisation's key,
                                  or a person whose role sees the team)
- GET  /team/invites              pending invites: id, role, masked e-mail (team:read; the same)
- POST /team/invites              invite a person by e-mail with a role; the app's invitation
                                  e-mail, accepted by them (team:manage)
- POST /team/invites/{id}/resend  a new invitation e-mail: the pending one is revoked and sent
                                  again (team:manage)
- POST /team/invites/{id}/revoke  the invite stops working (team:manage)
- POST /team/{person_id}/role     admin, manager, member, viewer or finance; never the owner's;
                                  the owner's key only, as in the app (team:manage)
- POST /team/{person_id}/remove   the membership ends; never the owner (team:manage)
- POST /leads/shelf               archive, restore from Archived, move to the Bin or restore from
                                  it, up to 2,000 leads by id or by the Leads list's filter
                                  (leads:archive); the Bin's purge stays in Sales X-Ray
- POST /leads/reassign            every lead one person owns (or the ones waiting for an owner)
                                  to another person, or by the lead rules (leads:assign)

Every change here is an organisation's API key held by an owner or admin (as the app's own
Organisation page and Leads bulk bar are theirs; ai-writes.md, "Amended 15 Nov"); a connected
app or a seller's key is refused. Each goes through the app's own service
(OrganisationService for people, the Leads bulk job for leads), which records it, so the
audit history names the key's person. Each takes a ``request_id``: the same one again returns
the first answer and changes nothing. A lead change over 5 leads is previewed first
(``preview: true`` gives the counts and a ``preview_sha``; send it back to apply), the
owner's pause in Organisation -> AI apps stops them, and each can be undone in Sales X-Ray
for 30 minutes.

Not here, by design (the CLI's, for an operator with the owner's approval): moving
ownership, renaming a person's account, the workspace's name, its verified e-mail domains
(the app proves those by DNS), the AI-apps switch itself (a key never widens what keys may do)
and making or listing workspaces (a key belongs to one).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select

from ac_platform.http.routes import RouteContext
from ac_platform.integrations.ai_writes import IN_APP, AiWrites
from ac_platform.integrations.api_http import PRIVATE, ApiError, Reader, make_opener
from ac_platform.kernel.errors import DomainError
from ac_platform.lead_desk import bulk_jobs
from ac_platform.lead_desk.contracts import BulkJobCommand, LeadFilter
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead
from ac_platform.organisations.invitations import active_pending_invites
from ac_platform.organisations.seats import seat_exempt
from ac_platform.organisations.service import OrganisationService
from ac_platform.tenancy.models import Membership, OrganisationInvite, Tenant

TEAM_MANAGE = "team:manage"
ARCHIVE = "leads:archive"
ASSIGN = "leads:assign"
# Above this many leads a change is previewed first (write_policy.PREVIEW_ABOVE).
PREVIEW_ABOVE = 5
MAX_LEADS = 2000
_NAMESPACE = UUID("6f1c2b7e-3a51-4c1b-9e2f-0a7d1c5b9e44")
# The application these routes serve, for the internal testers' seat exemption that the app's
# own Organisation page applies (http/organisation.py); set when the routes are installed.
_SERVED: list[Any] = []
Role = Literal["admin", "manager", "member", "viewer", "finance"]
ShelfAction = Literal["archive", "restore_archive", "bin", "restore_bin"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=8, max_length=80)


class InviteBody(_Body):
    email: str = Field(min_length=3, max_length=320)
    role: Role = "member"


class RoleBody(_Body):
    role: Role


class RequestBody(_Body):
    pass


class ShelfBody(_Body):
    """Leads by id, or the Leads list's own filter (GET /v1/lead-desk/leads's options)."""

    action: ShelfAction
    lead_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=MAX_LEADS)
    filter: LeadFilter | None = None
    preview: bool = False
    preview_sha: str | None = Field(default=None, min_length=64, max_length=64)


class ReassignBody(_Body):
    """Every lead ``from_person_id`` owns (none: the leads waiting for an owner) goes to
    ``to_person_id`` (none: whom the lead rules pick)."""

    from_person_id: UUID | None = None
    to_person_id: UUID | None = None
    preview: bool = False
    preview_sha: str | None = Field(default=None, min_length=64, max_length=64)


def _mask(email: str) -> str:
    return f"{email[:1]}***@{email.rsplit('@', 1)[-1]}"


def _command(reader: Reader, route: str, request_id: str) -> UUID:
    return uuid5(_NAMESPACE, f"{reader.key.key_id}:{route}:{request_id}")


def _sees_team(reader: Reader) -> None:
    reader.require("team:read")
    if not reader.caller.sees_team:
        raise ApiError(403, "team_only", "Your role doesn't see the team.")


async def _manager(reader: Reader, scope: str) -> None:
    reader.require(scope)
    if not await reader._manager_key():
        raise ApiError(
            403,
            "managers_only",
            "This change is made with an organisation's API key held by an owner or admin.",
        )


def _service(reader: Reader) -> OrganisationService:
    settings = reader.settings
    if (
        settings is None
        or settings.operations_tenant_id is None
        or settings.public_learner_tenant_id is None
    ):
        raise ApiError(503, "not_ready", "Team changes aren't set up on this server yet.")
    state = _SERVED[-1].state if _SERVED else None
    return OrganisationService(
        reader.session,
        operations_tenant_id=settings.operations_tenant_id,
        public_learner_tenant_id=settings.public_learner_tenant_id,
        seat_exempt=lambda tenant_id: seat_exempt(
            tenant_id,
            policy=getattr(state, "internal_tester_policy", None),
            environment=settings.environment,
        ),
    )


async def _domain(change: Any) -> Any:
    try:
        return await change
    except DomainError as error:
        raise ApiError(error.status, error.code, error.detail) from None


# ----- the workspace and its people ----------------------------------------------------------


async def _count(reader: Reader, *where: Any) -> int:
    return int(
        await reader.session.scalar(
            select(func.count())
            .select_from(Lead)
            .where(Lead.tenant_id == reader.key.tenant_id, *where)
        )
        or 0
    )


async def workspace(reader: Reader) -> dict[str, Any]:
    _sees_team(reader)
    tenant_id = reader.key.tenant_id
    tenant = await reader.session.get(Tenant, tenant_id)
    if tenant is None:
        raise ApiError(404, "workspace_missing", "This workspace is not here.")
    rows = await reader.session.execute(
        select(Membership.role, func.count())
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
            Membership.role != "processing",
        )
        .group_by(Membership.role)
    )
    roles = {role: int(count) for role, count in rows.all()}
    invites = await active_pending_invites(reader.session, tenant_id=tenant_id)
    _, switch = await AiWrites(reader._desk(), IN_APP).settings()
    on_desk = (Lead.archived_at.is_(None), Lead.binned_at.is_(None))
    return {
        "workspace": {"id": str(tenant_id), "name": tenant.name, "status": tenant.status},
        "members_by_role": dict(sorted(roles.items())),
        "pending_invites": len(invites),
        "leads": {
            "on_desk": await _count(reader, *on_desk),
            "archived": await _count(reader, Lead.archived_at.is_not(None), on_desk[1]),
            "bin": await _count(reader, Lead.binned_at.is_not(None)),
            "unassigned": await _count(reader, Lead.owner_person_id.is_(None), *on_desk),
        },
        "ai_apps_switch": switch,
    }


async def invites(reader: Reader) -> dict[str, Any]:
    _sees_team(reader)
    rows = await active_pending_invites(reader.session, tenant_id=reader.key.tenant_id)
    return {
        "invites": [
            {
                "invite_id": str(row.id),
                "email": _mask(row.email_normalized),
                "role": row.role,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
    }


async def invite(reader: Reader, body: InviteBody) -> dict[str, Any]:
    await _manager(reader, TEAM_MANAGE)
    if "@" not in body.email:
        raise ApiError(422, "email", "A valid email is required.")
    result = await _domain(
        _service(reader).request_member(
            reader.key.tenant_id,
            body.email,
            body.role,
            _command(reader, "invite", body.request_id),
            actor_person_id=reader.key.acting_person_id,
            require_acceptance=True,
        )
    )
    return {
        "invite_id": str(result.get("invite_id")) if result.get("invite_id") else None,
        "person_id": str(result["person_id"]) if result.get("person_id") else None,
        "role": body.role,
        "email": _mask(body.email.strip().lower()),
        "status": result.get("status", "invited"),
    }


async def _pending(reader: Reader, invite_id: UUID) -> OrganisationInvite:
    for row in await active_pending_invites(reader.session, tenant_id=reader.key.tenant_id):
        if row.id == invite_id:
            return row
    raise ApiError(404, "invite_missing", "No pending invite with that id.")


async def revoke(reader: Reader, invite_id: UUID, body: RequestBody) -> dict[str, Any]:
    await _manager(reader, TEAM_MANAGE)
    command = _command(reader, f"revoke:{invite_id}", body.request_id)
    found = await reader.session.get(OrganisationInvite, invite_id)
    if found is None or found.tenant_id != reader.key.tenant_id:
        raise ApiError(404, "invite_missing", "No pending invite with that id.")
    await _domain(
        _service(reader).revoke_invite(
            reader.key.tenant_id, invite_id, command, actor_person_id=reader.key.acting_person_id
        )
    )
    return {"invite_id": str(invite_id), "status": "revoked"}


async def resend(reader: Reader, invite_id: UUID, body: RequestBody) -> dict[str, Any]:
    """The app has no resend: the pending invite is revoked and a new one sent, so the
    person gets a fresh invitation e-mail. A retry returns the first answer."""
    await _manager(reader, TEAM_MANAGE)
    command = _command(reader, f"resend:{invite_id}", body.request_id)
    found = await reader.session.get(OrganisationInvite, invite_id)
    if found is None or found.tenant_id != reader.key.tenant_id:
        raise ApiError(404, "invite_missing", "No pending invite with that id.")
    replaced = await reader.session.scalar(
        select(OrganisationInvite).where(
            OrganisationInvite.command_id == uuid5(command, "invite"),
        )
    )
    if replaced is None:
        pending = await _pending(reader, invite_id)
        service = _service(reader)
        await _domain(
            service.revoke_invite(
                reader.key.tenant_id,
                invite_id,
                uuid5(command, "revoke"),
                actor_person_id=reader.key.acting_person_id,
            )
        )
        await _domain(
            service.request_member(
                reader.key.tenant_id,
                pending.email_normalized,
                pending.role,
                uuid5(command, "invite"),
                actor_person_id=reader.key.acting_person_id,
                require_acceptance=True,
            )
        )
        replaced = await reader.session.scalar(
            select(OrganisationInvite).where(
                OrganisationInvite.command_id == uuid5(command, "invite")
            )
        )
    assert replaced is not None
    return {
        "invite_id": str(replaced.id),
        "revoked": str(invite_id),
        "role": replaced.role,
        "email": _mask(replaced.email_normalized),
        "status": "sent",
    }


async def set_role(reader: Reader, person_id: UUID, body: RoleBody) -> dict[str, Any]:
    await _manager(reader, TEAM_MANAGE)
    result = await _domain(
        _service(reader).change_member_role(
            reader.key.tenant_id,
            person_id,
            body.role,
            _command(reader, f"role:{person_id}", body.request_id),
            actor_person_id=reader.key.acting_person_id,
        )
    )
    # The app's member row (as PATCH /v1/organisation/members/{id} answers), without its e-mail.
    return {
        "person_id": str(person_id),
        "role": str(result.get("role", body.role)),
        "status": str(result.get("status", "active")),
    }


async def remove(reader: Reader, person_id: UUID, body: RequestBody) -> dict[str, Any]:
    await _manager(reader, TEAM_MANAGE)
    await _domain(
        _service(reader).remove_member(
            reader.key.tenant_id,
            person_id,
            _command(reader, f"remove:{person_id}", body.request_id),
            actor_person_id=reader.key.acting_person_id,
        )
    )
    return {"person_id": str(person_id), "status": "removed"}


# ----- leads ---------------------------------------------------------------------------------


async def _not_paused(reader: Reader) -> None:
    _, switch = await AiWrites(reader._desk(), IN_APP).settings()
    if switch.get("paused"):
        raise ApiError(403, "writes_paused", "The owner has paused changes from apps.")


def _sha(spec: dict[str, Any], job: Any) -> str:
    seen = {**spec, "would_change": sorted(str(lead) for lead in job.lead_ids)}
    return hashlib.sha256(json.dumps(seen, sort_keys=True, default=str).encode()).hexdigest()


def _answer(job: Any) -> dict[str, Any]:
    return {
        "job_id": str(job.job_id),
        "action": job.action,
        "selected": job.selected,
        "changed": job.changed,
        "unchanged": job.unchanged,
        "not_found": job.not_found,
        "failed": [{"reason": item.reason, "count": item.count} for item in job.failed],
        "lead_ids": [str(lead) for lead in job.lead_ids],
        "words": job.words,
        "undo_until": job.undo_until.isoformat(),
    }


async def _job(
    reader: Reader,
    command: BulkJobCommand,
    spec: dict[str, Any],
    preview: bool,
    preview_sha: str | None,
) -> dict[str, Any]:
    """One bulk job (lead_desk/bulk_jobs.py): a preview runs it and takes it back; over 5
    leads, the change applies only with the preview's sha."""
    desk = reader._desk()
    # A retry returns the first answer (the job is recorded under the request's id).
    try:
        return _answer(await bulk_jobs.one_job(desk, command.command_id))
    except DeskError:
        pass
    try:
        savepoint = await reader.session.begin_nested()
        rehearsal = await bulk_jobs.run(desk, command)
        await savepoint.rollback()
        sha = _sha(spec, rehearsal)
        if preview:
            return {**_answer(rehearsal), "preview": True, "preview_sha": sha}
        if rehearsal.changed > PREVIEW_ABOVE and preview_sha != sha:
            raise ApiError(
                409,
                "preview_first",
                f"This changes {rehearsal.changed} leads: preview it first and send its "
                "preview_sha.",
            )
        return _answer(await bulk_jobs.run(desk, command))
    except DeskError as error:
        raise ApiError(error.status, "lead_desk", str(error)) from None


async def shelve(reader: Reader, body: ShelfBody) -> dict[str, Any]:
    await _manager(reader, ARCHIVE)
    await _not_paused(reader)
    if (body.lead_ids is None) == (body.filter is None):
        raise ApiError(422, "leads", "Send lead_ids or a filter, one of them.")
    command = BulkJobCommand(
        command_id=_command(reader, "shelf", body.request_id),
        lead_ids=tuple(dict.fromkeys(body.lead_ids)) if body.lead_ids else None,
        filter=body.filter,
        action=body.action,
    )
    spec = body.model_dump(mode="json", exclude={"preview", "preview_sha"})
    return await _job(reader, command, spec, body.preview, body.preview_sha)


async def reassign(reader: Reader, body: ReassignBody) -> dict[str, Any]:
    await _manager(reader, ASSIGN)
    await _not_paused(reader)
    if body.from_person_id is not None and body.from_person_id == body.to_person_id:
        raise ApiError(422, "same_person", "Those leads are with that person already.")
    if body.to_person_id is not None:
        member = await reader.session.scalar(
            select(Membership.role).where(
                Membership.tenant_id == reader.key.tenant_id,
                Membership.person_id == body.to_person_id,
                Membership.status == "active",
                Membership.ended_at.is_(None),
            )
        )
        if member is None:
            raise ApiError(422, "person", "Leads go only to an active member (GET /team).")
    chosen = (
        LeadFilter(scope="unassigned")
        if body.from_person_id is None
        else LeadFilter(scope="team", owner=body.from_person_id)
    )
    command = BulkJobCommand(
        command_id=_command(reader, "reassign", body.request_id),
        filter=chosen,
        action="assign",
        person_id=body.to_person_id,
    )
    spec = body.model_dump(mode="json", exclude={"preview", "preview_sha"})
    return await _job(reader, command, spec, body.preview, body.preview_sha)


# ----- MCP tools -----------------------------------------------------------------------------

_ID = {"type": "string", "description": "The id from a list."}
_REQUEST = {
    "type": "string",
    "minLength": 8,
    "maxLength": 80,
    "description": "Your own id for this change: the same one again changes nothing.",
}
_PREVIEW = {"type": "boolean", "description": "Only say what would change."}
_SHA = {"type": "string", "description": "preview_sha from the preview (over 5 leads)."}
_READS = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
_WRITES = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
_ROLE = {"type": "string", "enum": ["admin", "manager", "member", "viewer", "finance"]}
_FILTER = {
    "type": "object",
    "description": (
        "The Leads list's filter: scope (team, unassigned), side (inbound, cold), step, "
        "search, owner (a person_id), pipeline, source, shelf (archived, bin)."
    ),
}
TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_workspace",
        "title": "Read the workspace",
        "description": (
            "The workspace: its name, members by role, pending invites, how many leads are on "
            "the desk, Archived, in the Bin and waiting for an owner, and the owner's AI-apps "
            "switch."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": "team:read",
    },
    {
        "name": "list_invites",
        "title": "List pending invites",
        "description": "Invites not yet accepted: id, role and a masked e-mail.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": _READS,
        "scope": "team:read",
    },
    {
        "name": "invite_member",
        "title": "Invite a person",
        "description": (
            "Invites a person by e-mail with a role; they get Sales X-Ray's invitation e-mail "
            "and accept it. An owner's or admin's organisation key only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"email": {"type": "string"}, "role": _ROLE, "request_id": _REQUEST},
            "required": ["email", "request_id"],
        },
        "annotations": _WRITES,
        "scope": TEAM_MANAGE,
    },
    {
        "name": "resend_invite",
        "title": "Send an invite again",
        "description": "A fresh invitation e-mail for a pending invite (the old link stops).",
        "inputSchema": {
            "type": "object",
            "properties": {"invite_id": _ID, "request_id": _REQUEST},
            "required": ["invite_id", "request_id"],
        },
        "annotations": _WRITES,
        "scope": TEAM_MANAGE,
    },
    {
        "name": "revoke_invite",
        "title": "Cancel an invite",
        "description": "The pending invite stops working.",
        "inputSchema": {
            "type": "object",
            "properties": {"invite_id": _ID, "request_id": _REQUEST},
            "required": ["invite_id", "request_id"],
        },
        "annotations": {**_WRITES, "destructiveHint": True},
        "scope": TEAM_MANAGE,
    },
    {
        "name": "set_member_role",
        "title": "Change a person's role",
        "description": (
            "admin, manager, member, viewer or finance, for a person from list_team; never "
            "the owner's."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"person_id": _ID, "role": _ROLE, "request_id": _REQUEST},
            "required": ["person_id", "role", "request_id"],
        },
        "annotations": _WRITES,
        "scope": TEAM_MANAGE,
    },
    {
        "name": "remove_member",
        "title": "Remove a person",
        "description": (
            "The person leaves the workspace (never the owner). Give their leads to someone "
            "first with reassign_leads."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"person_id": _ID, "request_id": _REQUEST},
            "required": ["person_id", "request_id"],
        },
        "annotations": {**_WRITES, "destructiveHint": True},
        "scope": TEAM_MANAGE,
    },
    {
        "name": "shelve_leads",
        "title": "Archive, bin or restore leads",
        "description": (
            "archive, restore_archive, bin (Delete, kept 30 days) or restore_bin, for leads by "
            "id or by the Leads list's filter, up to 2,000. Over 5 leads, preview first and "
            "send its preview_sha. It can be undone in Sales X-Ray for 30 minutes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["archive", "restore_archive", "bin", "restore_bin"],
                },
                "lead_ids": {"type": "array", "items": _ID, "maxItems": MAX_LEADS},
                "filter": _FILTER,
                "request_id": _REQUEST,
                "preview": _PREVIEW,
                "preview_sha": _SHA,
            },
            "required": ["action", "request_id"],
        },
        "annotations": {**_WRITES, "destructiveHint": True},
        "scope": ARCHIVE,
    },
    {
        "name": "reassign_leads",
        "title": "Give one person's leads to another",
        "description": (
            "Every lead from_person_id owns (none: the leads waiting for an owner) goes to "
            "to_person_id (none: whom the lead rules pick). Over 5 leads, preview first and "
            "send its preview_sha. It can be undone in Sales X-Ray for 30 minutes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "from_person_id": _ID,
                "to_person_id": _ID,
                "request_id": _REQUEST,
                "preview": _PREVIEW,
                "preview_sha": _SHA,
            },
            "required": ["request_id"],
        },
        "annotations": _WRITES,
        "scope": ASSIGN,
    },
)
NAMES = frozenset(tool["name"] for tool in TOOLS)


def _args(model: Any, args: dict[str, Any], fields: tuple[str, ...]) -> Any:
    try:
        return model(**{name: args[name] for name in fields if args.get(name) is not None})
    except ValidationError:
        raise ApiError(422, "argument", "Check the tool's arguments.") from None


def _uuid(args: dict[str, Any], name: str) -> UUID:
    try:
        return UUID(str(args.get(name, "")))
    except ValueError:
        raise ApiError(422, "argument", f"{name} must be an id from a list.") from None


async def run_tool(reader: Reader, name: str, args: dict[str, Any]) -> Any:
    if name == "get_workspace":
        return await workspace(reader)
    if name == "list_invites":
        return await invites(reader)
    if name == "invite_member":
        return await invite(reader, _args(InviteBody, args, ("email", "role", "request_id")))
    if name == "resend_invite":
        return await resend(
            reader, _uuid(args, "invite_id"), _args(RequestBody, args, ("request_id",))
        )
    if name == "revoke_invite":
        return await revoke(
            reader, _uuid(args, "invite_id"), _args(RequestBody, args, ("request_id",))
        )
    if name == "set_member_role":
        return await set_role(
            reader, _uuid(args, "person_id"), _args(RoleBody, args, ("role", "request_id"))
        )
    if name == "remove_member":
        return await remove(
            reader, _uuid(args, "person_id"), _args(RequestBody, args, ("request_id",))
        )
    if name == "shelve_leads":
        shelf = ("action", "lead_ids", "filter", "request_id", "preview", "preview_sha")
        return await shelve(reader, _args(ShelfBody, args, shelf))
    if name == "reassign_leads":
        moving = ("from_person_id", "to_person_id", "request_id", "preview", "preview_sha")
        return await reassign(reader, _args(ReassignBody, args, moving))
    raise KeyError(name)


# ----- routes --------------------------------------------------------------------------------


def install_admin_api(application: FastAPI, ctx: RouteContext) -> None:
    router = APIRouter(prefix="/v1/api", tags=["sales-xray-api"])
    open_reader = make_opener(ctx)
    _SERVED.append(application)

    def done(body: dict[str, Any]) -> JSONResponse:
        return JSONResponse(body, headers=PRIVATE)

    @router.get("/workspace")
    async def workspace_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await workspace(reader))

    @router.get("/team/invites")
    async def invites_route(request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await invites(reader))

    @router.post("/team/invites")
    async def invite_route(body: InviteBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await invite(reader, body))

    @router.post("/team/invites/{invite_id}/resend")
    async def resend_route(invite_id: UUID, body: RequestBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await resend(reader, invite_id, body))

    @router.post("/team/invites/{invite_id}/revoke")
    async def revoke_route(invite_id: UUID, body: RequestBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await revoke(reader, invite_id, body))

    @router.post("/team/{person_id}/role")
    async def role_route(person_id: UUID, body: RoleBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await set_role(reader, person_id, body))

    @router.post("/team/{person_id}/remove")
    async def remove_route(person_id: UUID, body: RequestBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await remove(reader, person_id, body))

    @router.post("/leads/shelf")
    async def shelf_route(body: ShelfBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await shelve(reader, body))

    @router.post("/leads/reassign")
    async def reassign_route(body: ReassignBody, request: Request) -> JSONResponse:
        async with open_reader(request) as reader:
            return done(await reassign(reader, body))

    application.include_router(router)


__all__ = ["NAMES", "TOOLS", "install_admin_api", "run_tool"]
