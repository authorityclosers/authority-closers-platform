"""Many leads at once through the API, MCP and CLI (owner, 14 Nov 2026: "pushing thousands
of leads using Claude, uploading leads from Claude to Sales X-Ray").

``POST /v1/api/leads/imports`` takes up to ``MAX_ROWS`` leads as JSON and answers at once
with a job; the API files the rows in the background, ``CHUNK_ROWS`` at a time, through the
Lead Desk's own file import (``Intake.commit``). So an import made here dedupes, assigns,
places stages and owners, and can be undone for 48 hours exactly like a file uploaded in
the app, and shows in its Import history.

- **Idempotent:** an ``Idempotency-Key`` with the same rows answers with the same job; with
  other rows, 409. A row's ``external_id`` is that row's own id: the same id again is the
  same lead, in this import or a later one (``source_ref "ref:<id>"``).
- **Dedupe:** a row whose phone (or, without one, email) is already a lead is not a new
  lead; ``duplicates`` says whether its empty details are filled or replaced.
- **Report:** each row's outcome (created, updated, skipped with why, failed) and its lead.
- **Bounded:** 10,000 rows a job, 5 jobs waiting and 50,000 rows a day per workspace.
- **Private:** rows wait in the database only until their chunk is filed; then only the
  outcomes stay. Leads' details never stay in the job.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.integrations.import_models import (
    IntegrationLeadImport,
    IntegrationLeadImportChunk,
)
from ac_platform.integrations.models import IntegrationApiKey, IntegrationOAuthGrant

log = logging.getLogger(__name__)

MAX_ROWS: Final = 10_000
CHUNK_ROWS: Final = 250
MAX_WAITING: Final = 5
DAY_ROWS: Final = 50_000
MAX_ATTEMPTS: Final = 3
ROWS_PAGE: Final = 1_000
IDLE_SECONDS: Final = 5.0
# The row fields an import takes; the Lead Desk's file import reads them by these names.
MAPPING: Final[dict[str, str]] = {
    name: name
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
    )
}


class ImportLead(BaseModel):
    """One lead to import. At least a name, phone or email; the rest as the app's file import
    reads it: ``stage`` is a stage's name or key, ``owner`` a teammate's email or name,
    ``source`` the list it came from."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    company: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    language: str | None = Field(default=None, max_length=40)
    interest: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=80)
    owner: str | None = Field(default=None, max_length=320)
    source: str | None = Field(default=None, max_length=120)
    external_id: str | None = Field(default=None, min_length=1, max_length=120)


class ImportBody(BaseModel):
    """An import: the leads and how to file them."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="API import", min_length=1, max_length=200)
    leads: list[ImportLead] = Field(min_length=1, max_length=MAX_ROWS)
    # Inbound leads, or a Cold list.
    side: Literal["inbound", "cold"] = "inbound"
    # The workspace's lead rules give new leads out, or nobody gets them yet. A row's
    # ``owner`` gives that row's lead to that teammate either way.
    assign: Literal["rules", "none"] = "rules"
    # A lead already here: left as it is, its empty details filled, or its details replaced.
    duplicates: Literal["skip", "fill", "replace"] = "skip"
    # A pipeline's key; none: the one that takes file imports.
    pipeline: str | None = Field(default=None, max_length=40)
    # The stage new leads start in (a stage key); none: the first stage.
    stage: str | None = Field(default=None, max_length=40)


class ImportRefused(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True, slots=True)
class Door:
    """Who asks: a key or an app's connection, the person it acts for and how far it reaches."""

    via: Literal["key", "connection"]
    door_id: UUID
    tenant_id: UUID
    acting_person_id: UUID
    role: str
    label: str


def request_digest(body: ImportBody) -> str:
    """The rows and choices, canonically: the same import gives the same digest."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row(lead: ImportLead) -> dict[str, Any]:
    fields = lead.model_dump(exclude={"external_id"})
    return {
        "fields": {
            name: value.strip() for name, value in fields.items() if value and value.strip()
        },
        "ref": lead.external_id,
    }


async def create(
    session: AsyncSession,
    door: Door,
    body: ImportBody,
    *,
    idempotency_key: str | None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    """Queue an import; the answer is its view and 202, or the same job again and 200."""
    now = now or datetime.now(UTC)
    if idempotency_key is not None and not 8 <= len(idempotency_key) <= 120:
        raise ImportRefused(422, "idempotency_key", "Idempotency-Key is 8 to 120 characters.")
    digest = request_digest(body)
    job_table = IntegrationLeadImport
    if idempotency_key:
        earlier = await session.scalar(
            select(job_table).where(
                job_table.tenant_id == door.tenant_id,
                job_table.door_id == door.door_id,
                job_table.idempotency_key == idempotency_key,
            )
        )
        if earlier is not None:
            if earlier.request_sha256 != digest:
                raise ImportRefused(
                    409,
                    "idempotency_reused",
                    "This Idempotency-Key was used for another import.",
                )
            return {**await view(session, earlier), "replayed": True}, 200
    chunk = IntegrationLeadImportChunk
    waiting = await session.scalar(
        select(func.count(func.distinct(chunk.import_id)))
        .join(job_table, job_table.id == chunk.import_id)
        .where(job_table.tenant_id == door.tenant_id, chunk.state == "pending")
    )
    if (waiting or 0) >= MAX_WAITING:
        raise ImportRefused(
            429,
            "imports_busy",
            f"{MAX_WAITING} imports are still being filed here. Try again when one finishes.",
        )
    today = await session.scalar(
        select(func.coalesce(func.sum(job_table.total), 0)).where(
            job_table.tenant_id == door.tenant_id,
            job_table.created_at > now - timedelta(days=1),
        )
    )
    if int(today or 0) + len(body.leads) > DAY_ROWS:
        raise ImportRefused(
            429,
            "import_daily_limit",
            f"A workspace imports up to {DAY_ROWS:,} leads a day through the API.",
        )
    rows = [_row(lead) for lead in body.leads]
    job = job_table(
        id=uuid4(),
        tenant_id=door.tenant_id,
        via=door.via,
        door_id=door.door_id,
        acting_person_id=door.acting_person_id,
        role=door.role,
        label=door.label[:120],
        name=body.name.strip()[:200] or "API import",
        idempotency_key=idempotency_key,
        request_sha256=digest,
        options=body.model_dump(mode="json", exclude={"leads", "name"}),
        total=len(rows),
        chunks=(len(rows) + CHUNK_ROWS - 1) // CHUNK_ROWS,
        created_at=now,
    )
    session.add(job)
    await session.flush()
    for position, first in enumerate(range(0, len(rows), CHUNK_ROWS)):
        part = rows[first : first + CHUNK_ROWS]
        session.add(
            chunk(
                id=uuid4(),
                import_id=job.id,
                position=position,
                first_row=first,
                size=len(part),
                state="pending",
                rows=part,
                result=None,
                attempts=0,
                error=None,
                created_at=now,
                finished_at=None,
            )
        )
    await session.flush()
    return await view(session, job), 202


async def _chunks(session: AsyncSession, import_id: UUID) -> Sequence[IntegrationLeadImportChunk]:
    chunk = IntegrationLeadImportChunk
    return (
        await session.scalars(
            select(chunk).where(chunk.import_id == import_id).order_by(chunk.position)
        )
    ).all()


def _status(chunks: Sequence[IntegrationLeadImportChunk]) -> str:
    states = [part.state for part in chunks]
    if all(state == "pending" for state in states):
        return "queued"
    if any(state == "pending" for state in states):
        return "running"
    if all(state == "failed" for state in states):
        return "failed"
    return "partly_failed" if any(state == "failed" for state in states) else "done"


async def view(session: AsyncSession, job: IntegrationLeadImport) -> dict[str, Any]:
    """Where an import stands: counts so far and what the Lead Desk said about it."""
    chunks = await _chunks(session, job.id)
    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    totals = {"assigned": 0, "staged": 0, "owned": 0}
    warnings: list[str] = []
    stages: list[str] = []
    owners: list[str] = []
    undo_until: str | None = None
    processed = 0
    finished: datetime | None = None
    for part in chunks:
        if part.state == "pending":
            continue
        processed += part.size
        finished = max(filter(None, (finished, part.finished_at)), default=None)
        result = part.result or {}
        for key in counts:
            counts[key] += int(result.get(key, 0))
        for key in totals:
            totals[key] += int(result.get(key, 0))
        warnings += [item for item in result.get("warnings", []) if item not in warnings]
        stages += [item for item in result.get("unmatched_stages", []) if item not in stages]
        owners += [item for item in result.get("unmatched_owners", []) if item not in owners]
        undo_until = max(filter(None, (undo_until, result.get("undo_until"))), default=None)
    status = _status(chunks)
    return {
        "id": str(job.id),
        "name": job.name,
        "status": status,
        "total": job.total,
        "processed": processed,
        **counts,
        **totals,
        "warnings": warnings[:10],
        "unmatched_stages": stages[:10],
        "unmatched_owners": owners[:10],
        # Undo import in the app, for owners and admins (lead_desk/imports.py).
        "undo_until": undo_until,
        "created_at": job.created_at.isoformat(),
        "finished_at": finished.isoformat()
        if finished is not None and status not in ("queued", "running")
        else None,
    }


async def find(
    session: AsyncSession, door: Door, import_id: UUID, *, every_door: bool
) -> IntegrationLeadImport | None:
    """One import of this workspace: the caller's own, or any when it sees the team's."""
    job_table = IntegrationLeadImport
    query = select(job_table).where(
        job_table.id == import_id, job_table.tenant_id == door.tenant_id
    )
    if not every_door:
        query = query.where(job_table.door_id == door.door_id)
    found: IntegrationLeadImport | None = await session.scalar(query)
    return found


async def recent(session: AsyncSession, door: Door, *, every_door: bool) -> dict[str, Any]:
    """The last 50 imports, newest first."""
    job_table = IntegrationLeadImport
    query = select(job_table).where(job_table.tenant_id == door.tenant_id)
    if not every_door:
        query = query.where(job_table.door_id == door.door_id)
    jobs = (await session.scalars(query.order_by(job_table.created_at.desc()).limit(50))).all()
    return {"imports": [await view(session, job) for job in jobs]}


OUTCOMES: Final = frozenset({"created", "updated", "skipped", "failed", "waiting"})


async def rows(
    session: AsyncSession,
    job: IntegrationLeadImport,
    *,
    outcome: str | None = None,
    after: int = -1,
    limit: int = ROWS_PAGE,
) -> dict[str, Any]:
    """Each row's outcome, in order: its index, external id, outcome, why and its lead."""
    if outcome is not None and outcome not in OUTCOMES:
        raise ImportRefused(
            422, "outcome", "outcome is created, updated, skipped, failed or waiting."
        )
    limit = max(1, min(limit, ROWS_PAGE))
    found: list[dict[str, Any]] = []
    more = False
    for part in await _chunks(session, job.id):
        if part.first_row + part.size - 1 <= after:
            continue
        items: list[dict[str, Any]]
        if part.state == "pending":
            items = [
                {
                    "row": part.first_row + index,
                    "external_id": item.get("ref"),
                    "outcome": "waiting",
                }
                for index, item in enumerate(part.rows or [])
            ]
        else:
            items = list((part.result or {}).get("rows", []))
        for item in items:
            if item["row"] <= after or (outcome is not None and item["outcome"] != outcome):
                continue
            if len(found) == limit:
                more = True
                break
            found.append(item)
        if more:
            break
    return {"rows": found, "next_after": found[-1]["row"] if more and found else None}


# ----- the runner ---------------------------------------------------------------------


async def _door_open(session: AsyncSession, job: IntegrationLeadImport, now: datetime) -> bool:
    """The key or connection that asked is still in force: revoking it stops what waits."""
    if job.via == "key":
        key = await session.get(IntegrationApiKey, job.door_id)
        return (
            key is not None
            and key.revoked_at is None
            and (key.expires_at is None or key.expires_at > now)
        )
    grant = await session.get(IntegrationOAuthGrant, job.door_id)
    return grant is not None and grant.revoked_at is None


# The lesser of the role an import was queued with and the role its person holds when a
# chunk is filed decides (Codex P1 on release PR 617, 15 Nov 2026: a person removed, or
# whose role was lowered, after queueing an import still had it filed with the old role).
_ROLE_RANK: Final[dict[str, int]] = {"owner": 4, "admin": 3, "manager": 2, "member": 1}


async def acting_role(session: AsyncSession, job: IntegrationLeadImport) -> str | None:
    """The role a chunk is filed with now: the lesser of the one the import was queued with
    and the one its person holds this moment. None when they are no longer an active member
    of the workspace, or their role can only view (nothing is filed)."""
    from ac_platform.tenancy.models import Membership
    from ac_platform.tenancy.roles import READ_ONLY_ROLES

    current = await session.scalar(
        select(Membership.role).where(
            Membership.tenant_id == job.tenant_id,
            Membership.person_id == job.acting_person_id,
            Membership.status == "active",
            Membership.ended_at.is_(None),
        )
    )
    if current is None or current in READ_ONLY_ROLES or current not in _ROLE_RANK:
        return None
    queued = job.role if job.role in _ROLE_RANK else "member"
    return min((queued, current), key=lambda role: _ROLE_RANK[role])


def failed_rows(part: IntegrationLeadImportChunk, why: str) -> dict[str, Any]:
    return {
        "failed": part.size,
        "rows": [
            {
                "row": part.first_row + index,
                "external_id": item.get("ref"),
                "outcome": "failed",
                "reason": why,
                "lead_id": None,
            }
            for index, item in enumerate(part.rows or [])
        ],
    }


async def _file(
    session: AsyncSession,
    job: IntegrationLeadImport,
    part: IntegrationLeadImportChunk,
    app_url: str,
    role: str,
) -> dict[str, Any]:
    """File one chunk through the Lead Desk's file import, as the key's own viewer, with the
    role its person holds now (``acting_role``)."""
    from ac_platform.conversation_intelligence.synthetic_import_models import (
        ConversationSandboxOrganisation,
    )
    from ac_platform.lead_desk.contracts import ImportCommand
    from ac_platform.lead_desk.intake import Intake
    from ac_platform.lead_desk.store import LeadDesk, Viewer

    sandbox = (
        await session.scalar(
            select(ConversationSandboxOrganisation.tenant_id).where(
                ConversationSandboxOrganisation.tenant_id == job.tenant_id
            )
        )
    ) is not None
    desk = LeadDesk(
        session,
        Viewer(
            person_id=job.acting_person_id,
            tenant_id=job.tenant_id,
            role=role,
            name=job.label,
        ),
        sandbox=sandbox,
    )
    items = part.rows or []
    refs = tuple(item.get("ref") for item in items)
    options = job.options
    command = ImportCommand(
        command_id=job.id,
        file_name=job.name,
        mapping=MAPPING,
        rows=tuple(item["fields"] for item in items),
        refs=refs if any(refs) else (),
        assign=options.get("assign", "rules"),
        side="cold" if options.get("side") == "cold" else "live",
        duplicates=options.get("duplicates", "skip"),
        pipeline=options.get("pipeline"),
        step=options.get("stage"),
        start_row=part.first_row,
    )
    report: list[tuple[str, UUID | None]] = []
    result = await Intake(desk, app_url=app_url).commit(command, report=report)
    why = {skip.row: skip.reason for skip in result.skipped_rows}
    outcomes = []
    counts = {"created": 0, "updated": 0, "skipped": 0}
    for index, (outcome, lead_id) in enumerate(report):
        if index in why:
            kind, reason = "skipped", why[index]
        elif outcome == "created":
            kind, reason = "created", None
        else:
            # Found already and changed by Fill blanks or Replace (the rest are skips).
            kind, reason = "updated", None
        counts[kind] += 1
        outcomes.append(
            {
                "row": part.first_row + index,
                "external_id": refs[index],
                "outcome": kind,
                "reason": reason,
                "lead_id": str(lead_id) if lead_id is not None and kind != "skipped" else None,
            }
        )
    return {
        **counts,
        "failed": 0,
        "assigned": result.assigned,
        "staged": result.staged,
        "owned": result.owned,
        "warnings": list(result.warnings),
        "unmatched_stages": list(result.unmatched_stages),
        "unmatched_owners": list(result.unmatched_owners),
        "undo_until": result.undo_until.isoformat() if result.undo_until else None,
        "rows": outcomes,
    }


async def process_next(
    sessions: async_sessionmaker[AsyncSession], *, app_url: str, now: datetime | None = None
) -> bool:
    """File the oldest waiting chunk, if any, in one transaction; True when there was one.
    Several API processes share the queue: a chunk another holds is skipped, and a chunk
    whose transaction died waits for the next pass."""
    async with sessions() as session, session.begin():
        chunk = IntegrationLeadImportChunk
        part = await session.scalar(
            select(chunk)
            .where(chunk.state == "pending")
            .order_by(chunk.created_at, chunk.import_id, chunk.position)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if part is None:
            return False
        moment = now or datetime.now(UTC)
        job = await session.get(IntegrationLeadImport, part.import_id)
        assert job is not None  # the chunk's import, by its foreign key
        part.attempts += 1
        role = await acting_role(session, job)
        if not await _door_open(session, job, moment):
            result, error = failed_rows(part, "The key or app was revoked"), "door_closed"
        elif role is None:
            why = "The person who sent it is no longer a member who can add leads"
            result, error = failed_rows(part, why), "person_removed"
        else:
            try:
                async with session.begin_nested():
                    result, error = await _file(session, job, part, app_url, role), None
            except Exception as failure:  # noqa: BLE001 - a bad chunk must not stop the queue
                from ac_platform.lead_desk.store import DeskError

                if part.attempts < MAX_ATTEMPTS and not isinstance(failure, DeskError):
                    log.warning("lead import chunk %s will be tried again", part.id)
                    return True
                message = str(failure) if isinstance(failure, DeskError) else "Could not be filed"
                result, error = failed_rows(part, message[:200]), type(failure).__name__[:200]
        part.state = "failed" if error else "done"
        part.result, part.error = result, error
        part.rows = None
        part.finished_at = moment
        return True


async def run(
    sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event, *, app_url: str
) -> None:
    """File waiting chunks until the API stops; idle a few seconds when there are none."""
    while not stop.is_set():
        try:
            worked = await process_next(sessions, app_url=app_url)
        except Exception:  # noqa: BLE001 - the loop must survive a bad pass
            log.exception("lead import pass failed")
            worked = False
        if not worked:
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=IDLE_SECONDS)


def attach(
    application: Any,
    sessions: async_sessionmaker[AsyncSession],
    environment: str,
    *,
    app_url: str,
) -> None:
    """Run the importer for the API's lifetime by wrapping its lifespan (servers only)."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(
                run(sessions, stop, app_url=app_url), name="integrations-lead-imports"
            )
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
