"""Archive and Bin (owner, 16 Nov 2026: "deleting old leads, managing the leads at a higher
level is not there"; docs/design/research/lead-import-and-management-20261116/
02-management-findings-and-spec.md §4.5, M4 and §6; docs/product/lead-desk/lead-management-api.md).

- **Archive** is the normal clean-up. An archived lead leaves every work list, count, queue,
  timer and push (``history.on_desk``); it keeps its stage, owner, follow-ups and history; a
  search and the Archived list (``/leads?shelf=archived``) still find it; Restore puts it back
  as it was. Owners, admins and sales managers archive and restore.
- **Bin** is Delete. A binned lead is in no list but the Bin (``/leads?shelf=bin``) and no
  page opens it. Owners and admins move leads to the Bin, restore them within 30 days, or
  purge them at once; after 30 days the purge job deletes them for good. The purge is the old
  hard delete (deletion.py), audited the same way.
- A person who enquires again (an ad's or a website's form) brings an archived or binned lead
  back to the desk (store ``_repeat``), so a returning customer is never lost.

Every move is one audit event per request (ids and counts, never a name, number or word) that
doubles as the request's idempotency record, and one ``edited`` event per lead, so the lead's
history shows it. Nothing here overwrites history: a restore is a new event.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.contracts import LeadsDeleted, LeadsShelved
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ac_platform.lead_desk.store import LeadDesk

log = logging.getLogger(__name__)

ShelfAction = Literal["archive", "bin", "restore_archive", "restore_bin"]
MAX_LEADS: Final = 2000
BIN_DAYS: Final = 30
AUDIT_RESOURCE: Final = "lead_desk.lead_shelf"
AUDIT_ACTIONS: Final[dict[ShelfAction, str]] = {
    "archive": "lead_desk.leads.archived",
    "bin": "lead_desk.leads.binned",
    "restore_archive": "lead_desk.leads.unarchived",
    "restore_bin": "lead_desk.leads.restored",
}
# What the lead's history says (``LeadEventView.shelf``).
EVENT_WORDS: Final[dict[ShelfAction, str]] = {
    "archive": "Archived",
    "bin": "Moved to the Bin",
    "restore_archive": "Brought back from Archived",
    "restore_bin": "Restored from the Bin",
}
PURGE_ACTOR: Final = "lead_desk.bin_purge"
_TICK: Final = 3600.0
_PURGE_BATCH: Final = 500


def allowed(desk: LeadDesk, action: ShelfAction) -> None:
    """Archive: owners, admins and sales managers. The Bin: owners and admins only."""
    if action in ("archive", "restore_archive"):
        if not desk.viewer.can_manage:
            raise DeskError(403, "Only owners, admins and managers archive leads.")
    elif not desk.viewer.can_delete:
        raise DeskError(403, "Only owners and admins delete or restore leads.")


def _wants(action: ShelfAction, lead: Lead) -> bool:
    """Whether this lead changes: one already where it is asked to go stays as it is."""
    if action == "archive":
        return lead.archived_at is None and lead.binned_at is None
    if action == "bin":
        return lead.binned_at is None
    if action == "restore_archive":
        return lead.archived_at is not None and lead.binned_at is None
    return lead.binned_at is not None


def apply(desk: LeadDesk, action: ShelfAction, lead: Lead, command_id: UUID) -> None:
    """One lead moves (the caller checked ``_wants`` and holds its row lock)."""
    me = desk.viewer.person_id
    if action == "archive":
        lead.archived_at, lead.archived_by_person_id = desk.now, me
    elif action == "bin":
        # A binned lead keeps whether it was archived: restoring it puts it back there.
        lead.binned_at, lead.binned_by_person_id = desk.now, me
    elif action == "restore_archive":
        lead.archived_at, lead.archived_by_person_id = None, None
    else:
        lead.binned_at, lead.binned_by_person_id = None, None
    lead.revision += 1
    lead.updated_at = desk.now
    desk._event(
        lead,
        "edited",
        {"changed": ["shelf"], "shelf": action, "reason_text": EVENT_WORDS[action]},
        actor=me,
        command_id=uuid5(command_id, f"shelf:{lead.id}"),
    )


async def _done_before(db: AsyncSession, tenant_id: UUID, command_id: UUID) -> AuditEvent | None:
    event: AuditEvent | None = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.resource_type == AUDIT_RESOURCE,
            AuditEvent.resource_id == str(command_id),
        )
    )
    return event


def _answer(action: ShelfAction, payload: dict[str, Any]) -> LeadsShelved:
    return LeadsShelved(
        action=action,
        changed=int(payload.get("changed", 0)),
        unchanged=int(payload.get("unchanged", 0)),
        not_found=int(payload.get("not_found", 0)),
        lead_ids=tuple(UUID(value) for value in payload.get("lead_ids", ())),
    )


async def locked(desk: LeadDesk, lead_ids: Sequence[UUID]) -> list[Lead]:
    """The workspace's leads among these ids this person may change, locked in id order (two
    requests never deadlock). Sellers never reach here (``allowed``); scoping stays anyway."""
    scope = desk._visible()
    return list(
        await desk.db.scalars(
            select(Lead)
            .where(scope, Lead.id.in_(list(lead_ids)))
            .order_by(Lead.id)
            .with_for_update()
        )
    )


async def move(
    desk: LeadDesk,
    action: ShelfAction,
    command_id: UUID,
    lead_ids: Sequence[UUID],
    *,
    via: str = "leads",
) -> LeadsShelved:
    """Archive, bin or restore these leads in the request's one transaction."""
    allowed(desk, action)
    wanted = list(dict.fromkeys(lead_ids))
    if not 0 < len(wanted) <= MAX_LEADS:
        raise DeskError(422, f"Choose 1 to {MAX_LEADS:,} leads.")
    before = await _done_before(desk.db, desk.tenant_id, command_id)
    if before is not None:
        return _answer(action, before.payload)
    leads = await locked(desk, wanted)
    # A twin request (a second tap, a retry) may have finished while this one waited.
    before = await _done_before(desk.db, desk.tenant_id, command_id)
    if before is not None:
        return _answer(action, before.payload)
    changed: list[UUID] = []
    for lead in leads:
        if _wants(action, lead):
            apply(desk, action, lead, command_id)
            changed.append(lead.id)
    order = {lead_id: index for index, lead_id in enumerate(wanted)}
    changed.sort(key=lambda lead_id: order[lead_id])
    payload = {
        "changed": len(changed),
        "unchanged": len(leads) - len(changed),
        "not_found": len(wanted) - len(leads),
        "lead_ids": [str(lead_id) for lead_id in changed],
        "via": via,
    }
    await AuditRepository(desk.db).append(
        tenant_id=desk.tenant_id,
        actor_person_id=desk.viewer.person_id,
        session_id=desk.viewer.session_id,
        action=AUDIT_ACTIONS[action],
        resource_type=AUDIT_RESOURCE,
        resource_id=str(command_id),
        payload=payload,
        reason=f"{EVENT_WORDS[action]} in Leads",
        now=desk.now,
    )
    await desk.db.flush()
    return _answer(action, payload)


async def purge(desk: LeadDesk, command_id: UUID, lead_ids: Sequence[UUID]) -> LeadsDeleted:
    """Delete leads in the Bin for good now (owners and admins): the old hard delete, for
    binned leads only. A lead not in the Bin is counted as not found and left alone."""
    from ac_platform.lead_desk.contracts import DeleteLeads

    allowed(desk, "bin")
    wanted = list(dict.fromkeys(lead_ids))
    if not 0 < len(wanted) <= deletion.MAX_LEADS:
        raise DeskError(422, f"Choose 1 to {deletion.MAX_LEADS} leads.")
    if await deletion.done_before(desk.db, desk.tenant_id, command_id) is not None:
        # A retry: the first answer, as the delete recorded it.
        return await desk.delete_leads(DeleteLeads(command_id=command_id, lead_ids=tuple(wanted)))
    binned = set(
        await desk.db.scalars(
            select(Lead.id).where(
                Lead.tenant_id == desk.tenant_id,
                Lead.id.in_(wanted),
                Lead.binned_at.is_not(None),
            )
        )
    )
    if not binned:
        return LeadsDeleted(deleted=0, lead_ids=(), not_found=len(wanted))
    result = await desk.delete_leads(
        DeleteLeads(
            command_id=command_id,
            lead_ids=tuple(lead_id for lead_id in wanted if lead_id in binned),
        )
    )
    return result.model_copy(update={"not_found": result.not_found + len(wanted) - len(binned)})


async def purge_due(
    sessions: async_sessionmaker[AsyncSession], now: datetime, *, days: int = BIN_DAYS
) -> int:
    """Delete for good every lead in the Bin for longer than ``days``, a batch per workspace
    per transaction; returns how many went. Audited as the system, ids and counts only."""
    cutoff = now - timedelta(days=days)
    total = 0
    while True:
        async with sessions() as db, db.begin():
            tenant_id = await db.scalar(
                select(Lead.tenant_id).where(Lead.binned_at < cutoff).limit(1)
            )
            if tenant_id is None:
                return total
            ids = list(
                await db.scalars(
                    select(Lead.id)
                    .where(Lead.tenant_id == tenant_id, Lead.binned_at < cutoff)
                    .order_by(Lead.id)
                    .limit(_PURGE_BATCH)
                    .with_for_update(skip_locked=True)
                )
            )
            if not ids:
                return total
            removal = await deletion.remove(db, tenant_id, ids, now)
            await AuditRepository(db).append(
                tenant_id=tenant_id,
                actor_person_id=None,
                actor_type="system",
                action=deletion.AUDIT_ACTION,
                resource_type=deletion.AUDIT_RESOURCE,
                resource_id=str(uuid5(tenant_id, f"bin-purge:{now.isoformat()}:{ids[0]}")),
                payload={
                    "deleted": len(ids),
                    "lead_ids": [str(lead_id) for lead_id in ids],
                    "not_found": 0,
                    "removed": removal.removed,
                    "emptied": removal.emptied,
                    "kept": removal.kept,
                    "retired": removal.retired,
                    "by": PURGE_ACTOR,
                    "bin_days": days,
                },
                reason=f"In the Bin for more than {days} days",
                now=now,
            )
            total += len(ids)


async def _purger(sessions: async_sessionmaker[AsyncSession], stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            gone = await purge_due(sessions, datetime.now(UTC))
            if gone:
                log.info("lead bin purge: %d leads deleted", gone)
        except Exception:  # noqa: BLE001 - the loop must survive a bad tick
            log.warning("lead bin purge tick failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=_TICK)


def attach(
    application: FastAPI, sessions: async_sessionmaker[AsyncSession], environment: str
) -> None:
    """Run the Bin's purge hourly for the API's lifetime (not in local runs or tests)."""
    if environment in {"local", "test"}:
        return
    inner = application.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[Any]:
        async with inner(app) as state:
            stop = asyncio.Event()
            task = asyncio.create_task(_purger(sessions, stop), name="lead-bin-purge")
            try:
                yield state
            finally:
                stop.set()
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    application.router.lifespan_context = lifespan
