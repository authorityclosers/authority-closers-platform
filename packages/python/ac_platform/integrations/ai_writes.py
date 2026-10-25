"""Changes AI apps, API keys and the CLI make to leads, behind one set of guardrails
(owner order, 25 Oct 2026; design: docs/product/ai-writes.md; first slice: notes and tasks).

Every change goes through the lead desk's own commands (same permission checks, same
history, same idempotency) after ``write_policy.decide`` allows it, and leaves three marks
in the same transaction: the lead's history says which app sent it ("via ChatGPT"), a row
in ``integration_writes`` (the ledger the caps and the 7-day undo read), and an event in
the workspace's hash-chained audit log (ids and field names, never the text).

An undo never deletes: it is a marker event in the lead's history, a cancel for a task,
and its own ledger row pointing at the change. A person's later change wins: a task
someone has touched since is not undone.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ac_platform.audit.service import AuditRepository
from ac_platform.integrations import write_policy as policy
from ac_platform.integrations.models import IntegrationWrite
from ac_platform.lead_desk.contracts import (
    NoteCommand,
    TaskAction,
    TaskCommand,
    TaskKind,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent, LeadTask
from ac_platform.lead_desk.store import LeadDesk
from ac_platform.lead_desk.tasks import TaskBook

# Command ids for app changes: the same request from the same connection is the same
# command, so a retry does nothing twice.
_NAMESPACE = UUID("6f0c8a52-3d1e-4b8e-9a7c-2d5b1e0f4a91")
Via = Literal["connection", "key", "app"]


class AiWritesSettings(BaseModel):
    """The owner's switch (Organisation -> AI apps): pause everything, or one action."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    paused: bool
    note: bool
    task: bool
    outcome: bool


class AiWriteError(DeskError):
    """A refusal with a code an app can act on (``cap_reached``, ``writes_paused``…)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(status, message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Door:
    """How a change came in: a Connect connection (ChatGPT, Claude), an API key (scripts,
    the CLI), or the app itself (an undo made in Sales X-Ray)."""

    via: Via
    door_id: UUID | None  # the connection (grant) or the key
    label: str  # what the lead's history shows: "ChatGPT", "API key sxk_live_ab12"
    scopes: frozenset[str] = frozenset()

    @property
    def is_app(self) -> bool:
        return self.via == "app"


IN_APP = Door(via="app", door_id=None, label="Sales X-Ray")


def _refuse(decision: policy.Decision) -> None:
    if not decision.allowed:
        raise AiWriteError(decision.status, decision.code, decision.message)


class AiWrites:
    def __init__(self, desk: LeadDesk, door: Door) -> None:
        self.desk, self.door = desk, door
        self.db, self.tenant_id, self.now = desk.db, desk.tenant_id, desk.now
        self.person_id = desk.viewer.person_id

    # ----- the guardrails ---------------------------------------------------------

    def _command(self, request_id: str) -> UUID:
        return uuid5(_NAMESPACE, f"{self.door.via}:{self.door.door_id}:{request_id}")

    def _request(self, request_id: object) -> str:
        if not policy.request_ok(request_id):
            raise AiWriteError(
                422,
                "request_id",
                "Send a request_id: 8 to 80 letters, digits or symbols, new for each change.",
            )
        return str(request_id)

    def _mine(self) -> Any:
        """This door's own ledger rows."""
        if self.door.via == "connection":
            return IntegrationWrite.grant_id == self.door.door_id
        if self.door.via == "key":
            return IntegrationWrite.key_id == self.door.door_id
        return IntegrationWrite.person_id == self.person_id

    async def _counts(self, action: str, lead_id: UUID) -> policy.Counts:
        day, minute = self.now - timedelta(hours=24), self.now - timedelta(minutes=1)
        base = (IntegrationWrite.tenant_id == self.tenant_id, IntegrationWrite.action != "undo")
        by_action = {
            str(name): int(count)
            for name, count in (
                await self.db.execute(
                    select(IntegrationWrite.action, func.count())
                    .where(*base, self._mine(), IntegrationWrite.created_at >= day)
                    .group_by(IntegrationWrite.action)
                )
            ).all()
        }

        async def count(*where: Any) -> int:
            return int(
                await self.db.scalar(
                    select(func.count()).select_from(IntegrationWrite).where(*where)
                )
                or 0
            )

        return policy.Counts(
            connection=by_action,
            lead=await count(
                *base,
                IntegrationWrite.lead_id == lead_id,
                IntegrationWrite.action == action,
                IntegrationWrite.created_at >= day,
            ),
            workspace=await count(*base, IntegrationWrite.created_at >= day),
            minute=await count(*base, self._mine(), IntegrationWrite.created_at >= minute),
        )

    async def settings(self) -> tuple[int, dict[str, bool]]:
        revision, config = await self.desk.settings()
        return revision, policy.switch(config.get("ai_writes"))

    async def _check(self, action: str, lead_id: UUID) -> None:
        _, switch = await self.settings()
        _refuse(
            policy.decide(
                action,
                scopes=self.door.scopes,
                settings=switch,
                counts=await self._counts(action, lead_id),
            )
        )

    async def _replay(self, command_id: UUID) -> IntegrationWrite | None:
        found: IntegrationWrite | None = await self.db.scalar(
            select(IntegrationWrite).where(
                IntegrationWrite.tenant_id == self.tenant_id,
                IntegrationWrite.command_id == command_id,
            )
        )
        return found

    async def _record(
        self,
        change_id: UUID,
        *,
        action: str,
        lead_id: UUID,
        request_id: str | None,
        command_id: UUID,
        event_id: UUID | None,
        task_id: UUID | None,
        fields: list[str],
        undoes: IntegrationWrite | None = None,
    ) -> IntegrationWrite:
        row = IntegrationWrite(
            id=change_id,
            tenant_id=self.tenant_id,
            person_id=self.person_id,
            via=self.door.via,
            grant_id=self.door.door_id if self.door.via == "connection" else None,
            key_id=self.door.door_id if self.door.via == "key" else None,
            app_label=self.door.label[:80],
            action=action,
            lead_id=lead_id,
            request_sha256=(
                hashlib.sha256(request_id.encode()).hexdigest() if request_id is not None else None
            ),
            command_id=command_id,
            event_id=event_id,
            task_id=task_id,
            fields=fields,
            undoes_id=undoes.id if undoes is not None else None,
            created_at=self.now,
        )
        self.db.add(row)
        await self.db.flush()
        await AuditRepository(self.db).append(
            tenant_id=self.tenant_id,
            actor_person_id=self.person_id,
            actor_type={"connection": "ai_app", "key": "api_key", "app": "person"}[self.door.via],
            action=f"ai_write.{action}",
            resource_type="lead",
            resource_id=lead_id,
            payload={
                "change_id": str(change_id),
                "via": self.door.via,
                "app": self.door.label[:80],
                "fields": fields,
                **({"undoes": str(undoes.id)} if undoes is not None else {}),
            },
            now=self.now,
        )
        return row

    async def _event_for(self, command_id: UUID) -> UUID | None:
        found: UUID | None = await self.db.scalar(
            select(LeadEvent.id).where(
                LeadEvent.tenant_id == self.tenant_id, LeadEvent.command_id == command_id
            )
        )
        return found

    def _by_app(self, change_id: UUID) -> dict[str, str]:
        return {"label": self.door.label[:80], "change": str(change_id)}

    async def _answer(self, row: IntegrationWrite, *, replayed: bool = False) -> dict[str, Any]:
        lead = await self.desk._lead(row.lead_id)
        undone = await self.db.scalar(
            select(IntegrationWrite.id).where(IntegrationWrite.undoes_id == row.id)
        )
        return {
            "change_id": str(row.id),
            "action": row.action,
            "lead_id": str(row.lead_id),
            "lead_name": lead.name,
            "via": row.app_label,
            "at": row.created_at.isoformat(),
            "undo_until": (row.created_at + policy.UNDO_WINDOW).isoformat(),
            "status": "undone" if undone is not None else "applied",
            "replayed": replayed,
            **({"task_id": str(row.task_id)} if row.task_id else {}),
        }

    # ----- the changes ------------------------------------------------------------

    async def note(
        self, lead_id: UUID, note: str, *, request_id: object, preview: bool = False
    ) -> dict[str, Any]:
        """Add a note to a lead, as the person this connection acts for."""
        request = self._request(request_id)
        text = policy.clean_text(note)
        if not 0 < len(text) <= policy.NOTE_LIMIT:
            raise AiWriteError(422, "note", f"A note is 1 to {policy.NOTE_LIMIT} characters.")
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.lead_id != lead_id or seen.action != "note":
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        await self._check("note", lead_id)
        if preview:
            lead = await self.desk._lead(lead_id)
            return {
                "preview": True,
                "action": "note",
                "lead_id": str(lead_id),
                "lead_name": lead.name,
                "would_add": {"note": text},
                "via": self.door.label,
            }
        change_id = uuid4()
        await self.desk.note(
            lead_id, NoteCommand(command_id=command_id, note=text), by_app=self._by_app(change_id)
        )
        row = await self._record(
            change_id,
            action="note",
            lead_id=lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=None,
            fields=["note"],
        )
        return await self._answer(row)

    async def task(
        self,
        lead_id: UUID,
        *,
        kind: TaskKind,
        starts_at: datetime,
        request_id: object,
        title: str | None = None,
        note: str | None = None,
        ends_at: datetime | None = None,
        remind_before_minutes: int | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        """Add a task or reminder to a lead; it is the lead owner's, like any other."""
        request = self._request(request_id)
        title = policy.clean_text(title)[:200] if title else None
        note = policy.clean_text(note)[: policy.NOTE_LIMIT] if note else None
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.lead_id != lead_id or seen.action != "task":
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        await self._check("task", lead_id)
        command = TaskCommand(
            command_id=command_id,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            title=title or None,
            note=note or None,
            remind_before_minutes=remind_before_minutes,
            source="assistant",
        )
        fields = [
            name
            for name, value in (
                ("kind", kind),
                ("starts_at", starts_at),
                ("ends_at", ends_at),
                ("title", title),
                ("note", note),
                ("remind_before_minutes", remind_before_minutes),
            )
            if value is not None
        ]
        if preview:
            lead = await self.desk._lead(lead_id)
            return {
                "preview": True,
                "action": "task",
                "lead_id": str(lead_id),
                "lead_name": lead.name,
                "would_add": command.model_dump(
                    mode="json", include=set(fields), exclude_none=True
                ),
                "via": self.door.label,
            }
        change_id = uuid4()
        made = await TaskBook(self.desk).create(lead_id, command, by_app=self._by_app(change_id))
        row = await self._record(
            change_id,
            action="task",
            lead_id=lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=made.task_id,
            fields=fields,
        )
        return await self._answer(row)

    # ----- what was changed, and undo ---------------------------------------------

    async def changes(self, *, lead_id: UUID | None = None, limit: int = 50) -> dict[str, Any]:
        """Recent changes from apps: a connection's or key's own; in the app, a person's
        own, or every one for a manager."""
        where: list[Any] = [
            IntegrationWrite.tenant_id == self.tenant_id,
            IntegrationWrite.action != "undo",
            IntegrationWrite.created_at >= self.now - timedelta(days=30),
        ]
        if not (self.door.is_app and self.desk.viewer.can_manage):
            where.append(self._mine())
        if lead_id is not None:
            where.append(IntegrationWrite.lead_id == lead_id)
        rows = (
            await self.db.scalars(
                select(IntegrationWrite)
                .where(*where)
                .order_by(IntegrationWrite.created_at.desc(), IntegrationWrite.id)
                .limit(max(1, min(100, limit)))
            )
        ).all()
        undone = {
            row_id
            for row_id in (
                await self.db.scalars(
                    select(IntegrationWrite.undoes_id).where(
                        IntegrationWrite.undoes_id.in_([row.id for row in rows])
                    )
                )
            ).all()
        }
        # A lead deleted since keeps its changes here, without a name.
        leads = {
            lead_id: (name, owner)
            for lead_id, name, owner in (
                await self.db.execute(
                    select(Lead.id, Lead.name, Lead.owner_person_id).where(
                        Lead.tenant_id == self.tenant_id,
                        Lead.id.in_({row.lead_id for row in rows}),
                    )
                )
            ).all()
        }
        items = []
        for row in rows:
            name, owner = leads.get(row.lead_id, (None, None))
            done = row.id in undone
            items.append(
                {
                    "change_id": str(row.id),
                    "action": row.action,
                    "lead_id": str(row.lead_id),
                    "lead_name": name,
                    "via": row.app_label,
                    "at": row.created_at.isoformat(),
                    "status": "undone" if done else "applied",
                    "can_undo": not done
                    and row.lead_id in leads
                    and policy.may_undo(
                        person_id=self.person_id,
                        manages=self.desk.viewer.can_manage,
                        made_by=row.person_id,
                        lead_owner=owner,
                        made_at=row.created_at,
                        now=self.now,
                    ).allowed,
                }
            )
        return {"changes": items}

    async def undo(self, change_id: UUID, *, request_id: object = None) -> dict[str, Any]:
        """Undo one change an app made: a note stops showing, an open task is cancelled.
        Both stay in the lead's history; a person's later change to the task wins."""
        row: IntegrationWrite | None = await self.db.scalar(
            select(IntegrationWrite)
            .where(
                IntegrationWrite.tenant_id == self.tenant_id,
                IntegrationWrite.id == change_id,
                IntegrationWrite.action != "undo",
            )
            .with_for_update()
        )
        if row is None or (not self.door.is_app and self._door_of(row) != self.door.door_id):
            raise AiWriteError(404, "change_missing", "No such change from this connection.")
        request = self._request(request_id) if request_id is not None else f"undo:{row.id}"
        done: IntegrationWrite | None = await self.db.scalar(
            select(IntegrationWrite).where(IntegrationWrite.undoes_id == row.id)
        )
        if done is not None:
            return {**await self._answer(row, replayed=True), "undo_change_id": str(done.id)}
        lead = await self.desk._lead(row.lead_id)
        _refuse(
            policy.may_undo(
                person_id=self.person_id,
                manages=self.desk.viewer.can_manage,
                made_by=row.person_id,
                lead_owner=lead.owner_person_id,
                made_at=row.created_at,
                now=self.now,
            )
        )
        command_id = self._command(request)
        if row.action == "task" and row.task_id is not None:
            task: LeadTask | None = await self.db.get(LeadTask, row.task_id, with_for_update=True)
            if task is None or task.status != "open" or task.revision != 1:
                raise AiWriteError(
                    409,
                    "changed_since",
                    "Someone changed this task since. Change it in Sales X-Ray instead.",
                )
            await TaskBook(self.desk).cancel(
                task.id,
                TaskAction(command_id=uuid5(command_id, "cancel"), expected_revision=task.revision),
            )
        marker = None
        if row.event_id is not None:
            marker = await self.desk.undo_app_change(
                row.lead_id, row.event_id, command_id, change_id=row.id
            )
        undo = await self._record(
            uuid4(),
            action="undo",
            lead_id=row.lead_id,
            request_id=None if self.door.is_app else request,
            command_id=command_id,
            event_id=marker.id if marker is not None else None,
            task_id=row.task_id,
            fields=[],
            undoes=row,
        )
        return {**await self._answer(row), "undo_change_id": str(undo.id)}

    def _door_of(self, row: IntegrationWrite) -> UUID | None:
        return row.grant_id if self.door.via == "connection" else row.key_id

    # ----- the owner's switch -----------------------------------------------------

    async def save_settings(
        self, expected_revision: int, values: dict[str, bool]
    ) -> dict[str, Any]:
        """An owner or admin pauses changes from apps, or turns actions on or off."""
        if not self.desk.viewer.can_manage:
            raise AiWriteError(403, "not_manager", "Only owners and admins change this.")
        row: LeadDeskSettings | None = await self.db.get(
            LeadDeskSettings, self.tenant_id, with_for_update=True
        )
        current = row.revision if row else 0
        if current != expected_revision:
            raise AiWriteError(
                409, "stale", "Someone changed these settings. Reload and try again."
            )
        chosen = policy.switch(values)
        if row is None:
            row = LeadDeskSettings(tenant_id=self.tenant_id, revision=0, config={})
            self.db.add(row)
        row.revision = current + 1
        row.config = {**(row.config or {}), "ai_writes": chosen}
        row.updated_by_person_id = self.person_id
        row.updated_at = self.now
        await self.db.flush()
        await AuditRepository(self.db).append(
            tenant_id=self.tenant_id,
            actor_person_id=self.person_id,
            action="ai_write.settings",
            resource_type="lead_desk_settings",
            resource_id=self.tenant_id,
            payload=chosen,
            now=self.now,
        )
        return {"revision": row.revision, **chosen}

    async def describe(self) -> dict[str, Any]:
        revision, chosen = await self.settings()
        return {
            "revision": revision,
            **chosen,
            "can_change": self.desk.viewer.can_manage,
            "caps": {
                "per_connection_per_day": dict(policy.PER_CONNECTION),
                "per_lead_per_day": dict(policy.PER_LEAD),
                "per_workspace_per_day": policy.PER_WORKSPACE,
                "per_minute": policy.PER_MINUTE,
            },
            "undo_days": policy.UNDO_WINDOW.days,
        }
