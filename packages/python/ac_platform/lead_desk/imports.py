"""Import history and Undo import (competitor teardown 22, 1 Nov 2026).

A file import tags each lead it made: the lead's "captured" event carries the import's id
(its command id) and file name (store.ingest's ``batch``). Owners and admins see the last
48 hours of imports and may undo one in that time:

- **Removed:** the import's leads nobody has worked yet, through the same delete as Leads'
  Delete (deletion.py): their history goes, others' rows about them are emptied.
- **Kept:** a lead someone already worked (a call, a note, a stage they moved it to, a
  task, a meeting, an enquiry again), with why. Being given out (the import's own
  assignment, or a manager's later) and the import's own stage are not work.
- **Audit:** one audit event names who undid which import, with ids and counts; never a
  name, a number or a word. Audit history is never deleted.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select

from ac_platform.audit.models import AuditEvent
from ac_platform.audit.service import AuditRepository
from ac_platform.lead_desk import deletion
from ac_platform.lead_desk.contracts import (
    ImportKept,
    Imports,
    ImportUndone,
    ImportView,
    UndoImport,
)
from ac_platform.lead_desk.models import Lead, LeadEvent, LeadMeeting, LeadTask
from ac_platform.lead_desk.store import DeskError, LeadDesk

UNDO_FOR: Final = timedelta(hours=48)
AUDIT_ACTION: Final = "lead_desk.import.undone"
AUDIT_RESOURCE: Final = "lead_desk.import_undo"
# The import's own doing, and being handed out: not work on the lead.
NOT_WORK: Final = frozenset({"captured", "assigned", "reassigned", "unassigned"})
# Why a lead stayed, in the seller's words, by the first kind of work found on it.
WHY: Final = {
    "call": "Called",
    "result": "Called",
    "note": "Has a note",
    "stage": "Moved to another stage",
    "repeat": "Enquired again",
    "task": "Has a task",
    "meeting": "Has a meeting",
    "edited": "Details edited",
}


def _tag() -> Any:
    return LeadEvent.data["import"].as_string()


class ImportBook:
    """One workspace's recent file imports, as its owners and admins see them."""

    def __init__(self, desk: LeadDesk) -> None:
        self.desk = desk
        self.db = desk.db
        self.tenant_id = desk.tenant_id

    def _require(self) -> None:
        if not self.desk.viewer.can_delete:
            raise DeskError(403, "Only owners and admins undo an import.")

    async def recent(self) -> Imports:
        """Imports of the last 48 hours, newest first; nothing for anyone else."""
        if not self.desk.viewer.can_delete:
            return Imports(imports=())
        tag = _tag()
        rows = (
            await self.db.execute(
                select(
                    tag,
                    func.max(LeadEvent.data["import_file"].as_string()),
                    func.min(LeadEvent.created_at),
                    func.count(),
                    LeadEvent.actor_person_id,
                )
                .where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "captured",
                    tag.is_not(None),
                    LeadEvent.created_at >= self.desk.now - UNDO_FOR,
                )
                .group_by(tag, LeadEvent.actor_person_id)
                .order_by(func.min(LeadEvent.created_at).desc())
                .limit(20)
            )
        ).all()
        undone = await self._undone([UUID(row[0]) for row in rows])
        views = []
        for import_id, file_name, at, leads, actor in rows:
            ended = at + UNDO_FOR
            views.append(
                ImportView(
                    import_id=UUID(import_id),
                    file_name=file_name or "File",
                    at=at,
                    by_name=await self.desk._name(actor),
                    leads=int(leads),
                    undone=UUID(import_id) in undone,
                    undo_until=ended if ended > self.desk.now else None,
                )
            )
        return Imports(imports=tuple(views))

    async def _undone(self, import_ids: list[UUID]) -> set[UUID]:
        if not import_ids:
            return set()
        found = await self.db.scalars(
            select(AuditEvent.payload["import_id"].as_string()).where(
                AuditEvent.tenant_id == self.tenant_id,
                AuditEvent.resource_type == AUDIT_RESOURCE,
                AuditEvent.payload["import_id"]
                .as_string()
                .in_([str(import_id) for import_id in import_ids]),
            )
        )
        return {UUID(value) for value in found if value}

    async def undo(self, import_id: UUID, command: UndoImport) -> ImportUndone:
        """Remove the import's untouched leads; keep the worked ones and say why."""
        self._require()
        before = await self._done_before(command.command_id)
        if before is not None:
            return await self._answer(before)
        tag = _tag()
        made = (
            await self.db.execute(
                select(LeadEvent.lead_id, LeadEvent.created_at).where(
                    LeadEvent.tenant_id == self.tenant_id,
                    LeadEvent.kind == "captured",
                    tag == str(import_id),
                )
            )
        ).all()
        if not made:
            raise DeskError(404, "That import isn't here, or its leads are gone.")
        if min(at for _, at in made) + UNDO_FOR <= self.desk.now:
            raise DeskError(409, "An import can be undone for 48 hours. This one is older.")
        found = await deletion.lock(self.db, self.tenant_id, [lead_id for lead_id, _ in made])
        # A twin request (a second tap, a retry) may have finished while this one waited.
        before = await self._done_before(command.command_id)
        if before is not None:
            return await self._answer(before)
        worked = await self._worked(found)
        kept = await self._kept([lead_id for lead_id in found if lead_id in worked], worked)
        gone = [lead_id for lead_id in found if lead_id not in worked]
        removal = (
            await deletion.remove(self.db, self.tenant_id, gone, self.desk.now) if gone else None
        )
        # Ids and counts only: never a lead's name, number or words.
        await AuditRepository(self.db).append(
            tenant_id=self.tenant_id,
            actor_person_id=self.desk.viewer.person_id,
            session_id=self.desk.viewer.session_id,
            action=AUDIT_ACTION,
            resource_type=AUDIT_RESOURCE,
            resource_id=str(command.command_id),
            payload={
                "import_id": str(import_id),
                "deleted": len(gone),
                "lead_ids": [str(lead_id) for lead_id in gone],
                "kept": len(kept),
                "kept_ids": [str(item.lead_id) for item in kept],
                "removed": removal.removed if removal else {},
                "emptied": removal.emptied if removal else {},
                "retired": removal.retired if removal else {},
            },
            reason="Import undone in Leads after a confirm",
            now=self.desk.now,
        )
        return ImportUndone(removed=len(gone), kept=kept)

    async def _answer(self, before: AuditEvent) -> ImportUndone:
        """A retry's answer: the same counts, the kept leads read again by their ids."""
        ids = [UUID(value) for value in before.payload.get("kept_ids", ())]
        return ImportUndone(
            removed=int(before.payload.get("deleted", 0)),
            kept=await self._kept(ids, await self._worked(ids)),
        )

    async def _kept(self, lead_ids: list[UUID], worked: dict[UUID, str]) -> tuple[ImportKept, ...]:
        """The kept leads with their names, in the order given."""
        if not lead_ids:
            return ()
        rows = await self.db.execute(
            select(Lead.id, Lead.name).where(
                Lead.tenant_id == self.tenant_id, Lead.id.in_(lead_ids)
            )
        )
        names = {lead_id: name for lead_id, name in rows.tuples()}
        return tuple(
            ImportKept(lead_id=lead_id, name=names[lead_id], why=worked.get(lead_id, "Worked on"))
            for lead_id in lead_ids
            if lead_id in names
        )

    async def _done_before(self, command_id: UUID) -> AuditEvent | None:
        event: AuditEvent | None = await self.db.scalar(
            select(AuditEvent).where(
                AuditEvent.tenant_id == self.tenant_id,
                AuditEvent.resource_type == AUDIT_RESOURCE,
                AuditEvent.resource_id == str(command_id),
            )
        )
        return event

    async def _worked(self, lead_ids: list[UUID]) -> dict[UUID, str]:
        """The leads someone already worked, each with why."""
        if not lead_ids:
            return {}
        why: dict[UUID, str] = {}
        events = await self.db.execute(
            select(LeadEvent.lead_id, LeadEvent.kind, LeadEvent.data["source"].as_string())
            .where(
                LeadEvent.tenant_id == self.tenant_id,
                LeadEvent.lead_id.in_(lead_ids),
                LeadEvent.kind.not_in(NOT_WORK),
            )
            .order_by(LeadEvent.created_at, LeadEvent.id)
        )
        for lead_id, kind, source in events.tuples():
            if kind == "stage" and source == "import":
                continue  # the file said where it stands: the import's own move
            why.setdefault(lead_id, WHY.get(kind, "Worked on"))
        for model, words in ((LeadTask, "Has a task"), (LeadMeeting, "Has a meeting")):
            for lead_id in await self.db.scalars(
                select(model.lead_id).where(
                    model.tenant_id == self.tenant_id, model.lead_id.in_(lead_ids)
                )
            ):
                if lead_id is not None:
                    why.setdefault(lead_id, words)
        for lead_id in await self.db.scalars(
            select(Lead.id).where(
                Lead.tenant_id == self.tenant_id,
                Lead.id.in_(lead_ids),
                (Lead.attempts > 0) | (Lead.calls > 0),
            )
        ):
            why.setdefault(lead_id, "Called")
        return why
