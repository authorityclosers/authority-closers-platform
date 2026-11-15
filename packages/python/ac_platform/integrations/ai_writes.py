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
import json
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
    LeadEdit,
    NoteCommand,
    Reassign,
    StageMove,
    TaskAction,
    TaskChange,
    TaskCommand,
    TaskKind,
    TaskSnooze,
    TaskSnoozeChoice,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.journey import model as journeys
from ac_platform.lead_desk.models import Lead, LeadDeskSettings, LeadEvent, LeadTask
from ac_platform.lead_desk.store import LeadDesk
from ac_platform.lead_desk.tasks import TaskBook

# Command ids for app changes: the same request from the same connection is the same
# command, so a retry does nothing twice.
_NAMESPACE = UUID("6f0c8a52-3d1e-4b8e-9a7c-2d5b1e0f4a91")
Via = Literal["connection", "key", "app"]


class AiWritesSettings(BaseModel):
    """The owner's switch (Organisation -> AI apps): pause everything, or one action. An
    action left out keeps what is saved (a page that doesn't show it yet can't turn it off)."""

    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    paused: bool
    note: bool
    task: bool
    outcome: bool
    update: bool = False
    stage: bool = False


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
    # An organisation's API key held by an owner or admin, checked live (ai-writes.md,
    # "Amended 15 Nov"): it acts as the owner, may assign and change leads in bulk.
    manager_key: bool = False

    @property
    def is_app(self) -> bool:
        return self.via == "app"


IN_APP = Door(via="app", door_id=None, label="Sales X-Ray")

# A change to a task on a lead is a ``task`` write in the ledger (ai-writes.md: leads:tasks
# adds a task and marks one done); what it changed tells them apart, since adding one
# always names its kind.
TASK_DONE: tuple[str, ...] = ("status",)
TASK_SNOOZED: tuple[str, ...] = ("starts_at",)


def task_change(row: IntegrationWrite) -> Literal["added", "done", "snoozed"]:
    """Which change a ``task`` ledger row records."""
    fields = tuple(row.fields or ())
    if fields == TASK_DONE:
        return "done"
    if fields == TASK_SNOOZED:
        return "snoozed"
    return "added"


def _refuse(decision: policy.Decision) -> None:
    if not decision.allowed:
        raise AiWriteError(decision.status, decision.code, decision.message)


class AiWrites:
    def __init__(self, desk: LeadDesk, door: Door) -> None:
        self.desk, self.door = desk, door
        self.db, self.tenant_id, self.now = desk.db, desk.tenant_id, desk.now
        self.person_id = desk.viewer.person_id
        # While a manager's bulk change runs, its leads preview instead of counting.
        self._in_bulk = False

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
        # One lead of a manager's bulk change previews instead of counting (write_policy).
        bulk = self._in_bulk and self.door.manager_key
        _refuse(
            policy.decide(
                action,
                scopes=self.door.scopes,
                settings=switch,
                counts=None if bulk else await self._counts(action, lead_id),
                manager_key=self.door.manager_key,
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
            **({"task_change": task_change(row)} if row.action == "task" else {}),
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

    async def update(
        self,
        lead_id: UUID,
        fields: dict[str, Any],
        *,
        request_id: object,
        expected_revision: int | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        """Change a lead's allowed details (name, company, city, interest, language).

        Phone and email are refused with ``needs_review``: they decide duplicates and
        who a call matches, so they wait for the review queue (ai-writes.md, section 8).
        Undo restores what was there, unless a person changed those fields since."""
        request = self._request(request_id)
        unknown = sorted(set(fields) - set(policy.UPDATE_FIELDS) - set(policy.REVIEW_FIELDS))
        if unknown:
            raise AiWriteError(422, "field_not_allowed", f"Apps can't change {', '.join(unknown)}.")
        if set(fields) & set(policy.REVIEW_FIELDS):
            raise AiWriteError(
                422,
                "needs_review",
                "Phone and email changes from apps need a person's review, which isn't open"
                " yet. Add a note with the new details instead.",
            )
        if not fields:
            raise AiWriteError(422, "fields", "Send at least one field to change.")
        cleaned: dict[str, str | None] = {}
        for name, value in fields.items():
            if value is not None and not isinstance(value, str):
                raise AiWriteError(422, "field_value", f"{name} must be text.")
            text = policy.clean_text(value)[:200] if value else ""
            if name == "name" and not text:
                raise AiWriteError(422, "field_value", "A lead needs a name.")
            cleaned[name] = text
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.lead_id != lead_id or seen.action != "update":
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        await self._check("update", lead_id)
        lead = await self.desk._lead(lead_id)
        revision = lead.revision if expected_revision is None else expected_revision
        if revision != lead.revision:
            raise AiWriteError(409, "changed_since", "This lead changed. Read it and try again.")
        changing = {
            name: value
            for name, value in cleaned.items()
            if (getattr(lead, name) or "") != (value or "")
        }
        if preview:
            return {
                "preview": True,
                "action": "update",
                "lead_id": str(lead_id),
                "lead_name": lead.name,
                "would_change": changing,
                "via": self.door.label,
            }
        if not changing:
            raise AiWriteError(409, "no_change", "The lead already has those details.")
        change_id = uuid4()
        await self.desk.edit(
            lead_id,
            LeadEdit(command_id=command_id, expected_revision=revision, **changing),
            by_app=self._by_app(change_id),
        )
        row = await self._record(
            change_id,
            action="update",
            lead_id=lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=None,
            fields=sorted(changing),
        )
        return await self._answer(row)

    async def stage(
        self,
        lead_id: UUID,
        step: str,
        *,
        reason: object,
        request_id: object,
        reason_code: str | None = None,
        next_action_at: datetime | None = None,
        expected_revision: int | None = None,
        preview: bool = False,
        amount: int | None = None,
    ) -> dict[str, Any]:
        """Move a lead to one of its pipeline's stages, with the reason (ai-writes.md,
        "stage"). Won, Lost and Junk wait for a person (``needs_review``), except from an
        owner's or admin's organisation key ("Amended 15 Nov"), which closes with the
        reason (and Won's amount); the stage list's own rules still decide what a move
        needs (a reason code, a next action). Undo puts the lead back where it was, unless
        it moved again since."""
        request = self._request(request_id)
        why = policy.clean_text(reason)[: policy.REASON_LIMIT] if isinstance(reason, str) else ""
        if not why:
            raise AiWriteError(
                422, "reason", f"Say why the lead moves (1 to {policy.REASON_LIMIT} characters)."
            )
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.lead_id != lead_id or seen.action != "stage":
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        await self._check("stage", lead_id)
        lead = await self.desk._lead(lead_id)
        journey = await self.desk._labels(journeys.pipeline_of(lead))
        target = journey.stage_for(step)
        if target is None:
            keys = ", ".join(stage.key for stage in journey.board())
            raise AiWriteError(422, "stage_unknown", f"step is one of {keys}.")
        if target.kind in policy.REVIEW_STAGES and not self.door.manager_key:
            raise AiWriteError(
                422,
                "needs_review",
                "Moves to Won, Lost or Junk from apps need a person's review, which isn't open"
                " yet. Add a note or a task instead.",
            )
        revision = lead.revision if expected_revision is None else expected_revision
        if revision != lead.revision:
            raise AiWriteError(409, "changed_since", "This lead changed. Read it and try again.")
        current = journey.resolve(lead.stage, lead.step)
        if current is not None and current.key == target.key:
            raise AiWriteError(409, "no_change", "The lead is already at that stage.")
        if preview:
            return {
                "preview": True,
                "action": "stage",
                "lead_id": str(lead_id),
                "lead_name": lead.name,
                "would_move": {
                    "from": current.label if current is not None else lead.stage,
                    "to": target.label,
                    "reason": why,
                },
                "via": self.door.label,
            }
        change_id = uuid4()
        await self.desk.move(
            lead_id,
            StageMove(
                command_id=command_id,
                expected_revision=revision,
                step=target.key,
                note=why,
                outcome_reason=reason_code,
                next_action_at=next_action_at,
                via="api",
                amount=amount,
            ),
            by_app=self._by_app(change_id),
        )
        fields = ["reason", "step"]
        if reason_code is not None:
            fields.append("reason_code")
        if next_action_at is not None:
            fields.append("next_action_at")
        row = await self._record(
            change_id,
            action="stage",
            lead_id=lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=None,
            fields=sorted(fields),
        )
        return await self._answer(row)

    async def assign(
        self,
        lead_id: UUID,
        person_id: UUID | None,
        *,
        request_id: object,
        expected_revision: int | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        """Give a lead to a teammate, or (``person_id`` None) to whom the lead rules pick,
        from an owner's or admin's organisation key only ("Amended 15 Nov"). The lead's
        open tasks go with it. Undo gives it back, unless it moved to someone else since."""
        request = self._request(request_id)
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.lead_id != lead_id or seen.action != "assign":
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        await self._check("assign", lead_id)
        lead = await self.desk._lead(lead_id)
        revision = lead.revision if expected_revision is None else expected_revision
        if revision != lead.revision:
            raise AiWriteError(409, "changed_since", "This lead changed. Read it and try again.")
        if person_id is not None and person_id == lead.owner_person_id:
            raise AiWriteError(409, "no_change", "The lead is already theirs.")
        if preview:
            return {
                "preview": True,
                "action": "assign",
                "lead_id": str(lead_id),
                "lead_name": lead.name,
                "would_change": {
                    "owner": str(person_id) if person_id is not None else "the lead rules"
                },
                "via": self.door.label,
            }
        change_id = uuid4()
        await self.desk.reassign(
            lead_id,
            Reassign(command_id=command_id, expected_revision=revision, person_id=person_id),
        )
        row = await self._record(
            change_id,
            action="assign",
            lead_id=lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=None,
            fields=["owner"],
        )
        return await self._answer(row)

    async def _undo_assign(self, row: IntegrationWrite, command_id: UUID) -> None:
        """Give the lead back to whom it had, if it is still where the assign put it."""
        event = await self.db.get(LeadEvent, row.event_id) if row.event_id else None
        data = event.data if event is not None and isinstance(event.data, dict) else {}
        lead = await self.desk._lead(row.lead_id)
        given, before = data.get("to"), data.get("from")
        if event is None or not isinstance(given, str) or str(lead.owner_person_id) != given:
            raise AiWriteError(
                409,
                "changed_since",
                "Someone gave this lead to someone else since. Change it in Sales X-Ray instead.",
            )
        if not isinstance(before, str):
            raise AiWriteError(
                409, "cannot_undo", "This lead had no owner before; give it to someone instead."
            )
        try:
            await self.desk.reassign(
                row.lead_id,
                Reassign(
                    command_id=uuid5(command_id, "give-back"),
                    expected_revision=lead.revision,
                    person_id=UUID(before),
                ),
            )
        except AiWriteError:
            raise
        except DeskError as error:
            raise AiWriteError(error.status, "cannot_undo", str(error)) from None

    # ----- many leads at once (an owner's or admin's organisation key) -------------

    @staticmethod
    def _each(request: str, lead_id: UUID) -> str:
        """One lead's own request id within a bulk request: retried, it is the same change."""
        return "bulk-" + hashlib.sha256(f"{request}|{lead_id}".encode()).hexdigest()[:60]

    @staticmethod
    def bulk_sha(lead_ids: list[UUID], change: dict[str, Any]) -> str:
        """What a preview showed, so the change applies to exactly those leads."""
        body = json.dumps(
            {"leads": sorted(str(item) for item in lead_ids), "change": change},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()

    async def bulk(
        self,
        lead_ids: list[UUID],
        change: dict[str, Any],
        *,
        request_id: object,
        preview: bool = False,
        preview_sha: str | None = None,
    ) -> dict[str, Any]:
        """One change to many leads (up to 1,000) from an owner's or admin's organisation
        key ("Amended 15 Nov"): a stage move with its reason, or an assign. Above 5 leads
        the change previews first and applies only with that preview's ``preview_sha``.
        Each lead is its own change in the ledger (undone one by one, or all of this
        request together), and a lead that can't change is said, never hidden."""
        request = self._request(request_id)
        if not self.door.manager_key:
            raise AiWriteError(
                403,
                "managers_only",
                "Many leads at once come with an organisation's API key held by an owner or admin.",
            )
        ids = list(dict.fromkeys(lead_ids))
        if not 1 <= len(ids) <= policy.BULK_MAX:
            raise AiWriteError(
                422, "lead_count", f"Send 1 to {policy.BULK_MAX} leads (or a stage filter)."
            )
        kind = next(iter(change)) if len(change) == 1 else None
        if kind not in ("stage", "assign"):
            raise AiWriteError(422, "change", "The change is one stage move or one assign.")
        _, switch = await self.settings()
        _refuse(
            policy.decide(
                kind, scopes=self.door.scopes, settings=switch, counts=None, manager_key=True
            )
        )
        sha = self.bulk_sha(ids, change)
        if preview:
            found = (
                await self.db.execute(
                    select(Lead.id, Lead.name).where(
                        Lead.tenant_id == self.tenant_id, Lead.id.in_(ids)
                    )
                )
            ).all()
            return {
                "preview": True,
                "action": kind,
                "leads": len(ids),
                "found": len(found),
                "first": [{"lead_id": str(item), "name": name} for item, name in found[:20]],
                "would_change": change,
                "preview_sha": sha,
                "via": self.door.label,
            }
        if len(ids) > policy.PREVIEW_ABOVE and preview_sha != sha:
            raise AiWriteError(
                409,
                "preview_first",
                f"Above {policy.PREVIEW_ABOVE} leads, preview first and send its preview_sha.",
            )
        spec = change[kind]
        applied, unchanged = 0, 0
        failed: list[dict[str, str]] = []
        changes: list[str] = []
        self._in_bulk = True
        try:
            for lead_id in ids:
                each = self._each(request, lead_id)
                try:
                    async with self.db.begin_nested():
                        if kind == "stage":
                            answer = await self.stage(
                                lead_id,
                                str(spec.get("step") or ""),
                                reason=spec.get("reason"),
                                request_id=each,
                                reason_code=spec.get("reason_code"),
                                next_action_at=spec.get("next_action_at"),
                                amount=spec.get("amount"),
                            )
                        else:
                            owner = spec.get("person_id")
                            answer = await self.assign(
                                lead_id,
                                UUID(str(owner)) if owner else None,
                                request_id=each,
                            )
                except AiWriteError as error:
                    if error.code == "no_change":
                        unchanged += 1
                        continue
                    failed.append(
                        {"lead_id": str(lead_id), "code": error.code, "message": str(error)}
                    )
                    continue
                except DeskError as error:
                    failed.append(
                        {"lead_id": str(lead_id), "code": "lead_desk", "message": str(error)}
                    )
                    continue
                applied += 1
                changes.append(str(answer["change_id"]))
        finally:
            self._in_bulk = False
        return {
            "action": kind,
            "request_id": request,
            "leads": len(ids),
            "applied": applied,
            "unchanged": unchanged,
            "failed": failed[:200],
            "failed_count": len(failed),
            "changes": changes,
            "undo_until": (self.now + policy.UNDO_WINDOW).isoformat(),
            "via": self.door.label,
        }

    async def undo_request(self, request_id: object) -> dict[str, Any]:
        """Undo every change one bulk request made, each as its own undo; a lead someone
        changed since stays as it is and is said."""
        request = self._request(request_id)
        rows = (
            await self.db.scalars(
                select(IntegrationWrite)
                .where(
                    IntegrationWrite.tenant_id == self.tenant_id,
                    self._mine(),
                    IntegrationWrite.action.in_(("stage", "assign")),
                    IntegrationWrite.created_at >= self.now - policy.UNDO_WINDOW,
                )
                .order_by(IntegrationWrite.created_at.desc(), IntegrationWrite.id)
            )
        ).all()
        # This request's own rows first (each lead's change carries the request's per-lead
        # id), then one per lead: another change to the same lead from this key (another
        # request) must never stand in for it (Codex P2 on release PR 619).
        mine: list[IntegrationWrite] = []
        seen: set[UUID] = set()
        for row in rows:
            wanted = hashlib.sha256(self._each(request, row.lead_id).encode()).hexdigest()
            if row.request_sha256 == wanted and row.lead_id not in seen:
                seen.add(row.lead_id)
                mine.append(row)
        if not mine:
            raise AiWriteError(404, "change_missing", "No changes from that request to undo.")
        undone, kept = 0, []
        for row in mine:
            try:
                async with self.db.begin_nested():
                    await self.undo(row.id)
            except AiWriteError as error:
                kept.append(
                    {"lead_id": str(row.lead_id), "code": error.code, "message": str(error)}
                )
                continue
            except DeskError as error:
                kept.append(
                    {"lead_id": str(row.lead_id), "code": "lead_desk", "message": str(error)}
                )
                continue
            undone += 1
        return {"request_id": request, "changes": len(mine), "undone": undone, "kept": kept[:200]}

    async def _lead_task(self, task_id: UUID) -> LeadTask:
        """A task on a lead this workspace holds; a task of your own stays in Sales X-Ray."""
        task: LeadTask | None = await self.db.get(LeadTask, task_id)
        if task is None or task.tenant_id != self.tenant_id:
            raise AiWriteError(404, "task_missing", "No such task.")
        if task.lead_id is None:
            raise AiWriteError(
                422, "own_task", "Apps change tasks on leads; a task of your own stays in the app."
            )
        return task

    async def _task_write(
        self,
        change: Literal["done", "snoozed"],
        task_id: UUID,
        *,
        request_id: object,
        expected_revision: int | None,
        preview: bool,
        choice: TaskSnoozeChoice | None = None,
    ) -> dict[str, Any]:
        """Mark a task on a lead done, or snooze it (ai-writes.md: leads:tasks also marks
        a task done), as the person this connection acts for: a ``task`` write, under the
        owner's task switch and the task caps. Undo reopens it, or puts its due back,
        unless someone changed it since."""
        request = self._request(request_id)
        command_id = self._command(request)
        seen = await self._replay(command_id)
        if seen is not None:
            if seen.task_id != task_id or seen.action != "task" or task_change(seen) != change:
                raise AiWriteError(
                    409, "request_reused", "That request_id was used for another change."
                )
            return await self._answer(seen, replayed=True)
        task = await self._lead_task(task_id)
        assert task.lead_id is not None
        await self._check("task", task.lead_id)
        if task.status != "open":
            raise AiWriteError(409, "not_open", "This task isn't open any more.")
        revision = task.revision if expected_revision is None else expected_revision
        if revision != task.revision:
            raise AiWriteError(409, "changed_since", "This task changed. Read it and try again.")
        if preview:
            lead = await self.desk._lead(task.lead_id)
            would = {"status": "done"} if change == "done" else {"snooze": choice}
            return {
                "preview": True,
                "action": "task",
                "task_change": change,
                "lead_id": str(task.lead_id),
                "lead_name": lead.name,
                "task_id": str(task.id),
                "would_change": would,
                "via": self.door.label,
            }
        change_id = uuid4()
        book = TaskBook(self.desk)
        if change == "done":
            await book.done(task.id, TaskAction(command_id=command_id, expected_revision=revision))
            fields = list(TASK_DONE)
        else:
            assert choice is not None
            await book.snooze(
                task.id,
                TaskSnooze(command_id=command_id, expected_revision=revision, choice=choice),
            )
            fields = list(TASK_SNOOZED)
        row = await self._record(
            change_id,
            action="task",
            lead_id=task.lead_id,
            request_id=request,
            command_id=command_id,
            event_id=await self._event_for(command_id),
            task_id=task.id,
            fields=fields,
        )
        return await self._answer(row)

    async def task_done(
        self,
        task_id: UUID,
        *,
        request_id: object,
        expected_revision: int | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        return await self._task_write(
            "done",
            task_id,
            request_id=request_id,
            expected_revision=expected_revision,
            preview=preview,
        )

    async def task_snooze(
        self,
        task_id: UUID,
        choice: TaskSnoozeChoice,
        *,
        request_id: object,
        expected_revision: int | None = None,
        preview: bool = False,
    ) -> dict[str, Any]:
        return await self._task_write(
            "snoozed",
            task_id,
            request_id=request_id,
            expected_revision=expected_revision,
            preview=preview,
            choice=choice,
        )

    async def _undo_task_change(self, row: IntegrationWrite, command_id: UUID) -> None:
        """Reopen a task an app marked done, or put back the due an app's snooze moved,
        if nobody changed the task since (it was last touched by that change)."""
        task: LeadTask | None = (
            await self.db.get(LeadTask, row.task_id, with_for_update=True)
            if row.task_id is not None
            else None
        )
        event = await self.db.get(LeadEvent, row.event_id) if row.event_id else None
        data = event.data if event is not None and isinstance(event.data, dict) else {}
        unchanged = task is not None and event is not None and task.updated_at <= event.created_at
        if task_change(row) == "done":
            if not unchanged or task is None or task.status != "done":
                raise AiWriteError(
                    409,
                    "changed_since",
                    "Someone changed this task since. Change it in Sales X-Ray instead.",
                )
            await TaskBook(self.desk).undo(
                task.id,
                TaskAction(command_id=uuid5(command_id, "reopen"), expected_revision=task.revision),
            )
            return
        before = data.get("from_due_at")
        if not unchanged or task is None or task.status != "open" or not isinstance(before, str):
            raise AiWriteError(
                409,
                "changed_since",
                "Someone changed this task since. Change it in Sales X-Ray instead.",
            )
        try:
            await TaskBook(self.desk).change(
                task.id,
                TaskChange(
                    command_id=uuid5(command_id, "unsnooze"),
                    expected_revision=task.revision,
                    starts_at=datetime.fromisoformat(before),
                ),
            )
        except AiWriteError:
            raise
        except DeskError as error:
            raise AiWriteError(error.status, "cannot_undo", str(error)) from None

    async def _undo_update(self, row: IntegrationWrite, command_id: UUID) -> None:
        """Put back what an app's update replaced, if nobody changed those fields since."""
        event = await self.db.get(LeadEvent, row.event_id) if row.event_id else None
        data = event.data if event is not None and isinstance(event.data, dict) else {}
        before, after = data.get("before"), data.get("after")
        if not isinstance(before, dict) or not isinstance(after, dict) or not before:
            raise AiWriteError(409, "cannot_undo", "This change can't be undone here.")
        lead = await self.desk._lead(row.lead_id)
        if any(getattr(lead, name) != value for name, value in after.items()):
            raise AiWriteError(
                409,
                "changed_since",
                "Someone changed this lead since. Change it in Sales X-Ray instead.",
            )
        restore = {name: value if value is not None else "" for name, value in before.items()}
        if not restore.get("name", "x"):
            restore.pop("name")
        await self.desk.edit(
            row.lead_id,
            LeadEdit(
                command_id=uuid5(command_id, "restore"),
                expected_revision=lead.revision,
                **restore,
            ),
        )

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
                    **({"task_change": task_change(row)} if row.action == "task" else {}),
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
        if row.action == "update":
            await self._undo_update(row, command_id)
        if row.action == "assign":
            await self._undo_assign(row, command_id)
        if row.action == "task" and task_change(row) != "added":
            await self._undo_task_change(row, command_id)
        elif row.action == "task" and row.task_id is not None:
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
        if row.action == "stage" and row.event_id is not None:
            # The move's own undo puts the lead back and marks the move in one line.
            try:
                marker = await self.desk.undo_app_move(
                    row.lead_id, row.event_id, command_id, change_id=row.id
                )
            except AiWriteError:
                raise
            except DeskError as error:
                raise AiWriteError(error.status, "cannot_undo", str(error)) from None
        elif row.event_id is not None:
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
        """An owner or admin pauses changes from apps, or turns actions on or off. An action
        not in ``values`` keeps what is saved."""
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
        saved = policy.switch((row.config or {}).get("ai_writes") if row else None)
        chosen = policy.switch({**saved, **values})
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
