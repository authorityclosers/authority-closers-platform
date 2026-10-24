"""The task writer (work-memory engine, section 3; docs/product/lead-desk/work-memory-engine.md).

A task is what a seller must do for a lead: call back, WhatsApp, email, send a file, a
meeting, or something else. The row is the task as it stands; each change also writes
one ``task`` event on the lead, so the lead's history and My work show it.

- Every command carries the device's command id. The same command twice changes nothing
  the second time and answers the task as it is (a retry, a queued write sent again).
- A change made on an older revision is merged, not refused: the change made later on its
  device wins, and the other is kept in the history as superseded.
- The lead's next action is a projection: its earliest open task, so every reader and the
  phone alerts keep working. A follow-up set the old way (no task) is left alone.
- A task follows its lead: reassigning the lead moves its open tasks to the new owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, update

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk import scheduler
from ac_platform.lead_desk.commitments import IST, TASK_KINDS, title_for
from ac_platform.lead_desk.contracts import (
    TaskAction,
    TaskBucket,
    TaskChange,
    TaskCommand,
    TaskList,
    TaskSnooze,
    TaskView,
)
from ac_platform.lead_desk.errors import DeskError
from ac_platform.lead_desk.models import Lead, LeadTask

if TYPE_CHECKING:
    from ac_platform.lead_desk.store import LeadDesk

OPEN: Final = "open"
# How far ahead a due may be, and how far back (a note written late in the evening about
# this morning's promise).
LATEST: Final = timedelta(days=366)
EARLIEST: Final = timedelta(days=1)
LIST_LIMIT: Final = 200

Action = Literal[
    "created",
    "changed",
    "snoozed",
    "done",
    "undone",
    "cancelled",
    "reassigned",
    "rolled_over",
    "superseded",
]


def bucket(task: LeadTask, now: datetime) -> TaskBucket | None:
    """Overdue, today or upcoming, in the business's day (India time)."""
    if task.status != OPEN:
        return None
    if now >= task.starts_at + scheduler.OVERDUE_FROM:
        return "overdue"
    today_end = datetime.combine(
        now.astimezone(IST).date() + timedelta(days=1), time.min, tzinfo=IST
    )
    return "today" if task.starts_at < today_end else "upcoming"


def view(task: LeadTask, lead_name: str, now: datetime) -> TaskView:
    return TaskView(
        task_id=task.id,
        lead_id=task.lead_id,
        lead_name=lead_name,
        kind=task.kind,
        title=task.title,
        note=task.note,
        starts_at=task.starts_at,
        ends_at=task.ends_at,
        location=task.location,
        status=task.status,
        done_at=task.done_at,
        original_due_at=task.original_due_at,
        snoozes=task.snoozes,
        rollovers=task.rollovers,
        source=task.source,
        revision=task.revision,
        owner_person_id=task.owner_person_id,
        overdue=bucket(task, now) == "overdue",
        bucket=bucket(task, now),
    )


@dataclass(frozen=True, slots=True)
class _Change:
    task: LeadTask
    lead: Lead | None  # None: nothing to change (a replay, or superseded)


class TaskBook:
    def __init__(self, desk: LeadDesk) -> None:
        self.desk = desk
        self.db = desk.db
        self.tenant_id = desk.tenant_id
        self.now = desk.now

    # ----- reading ------------------------------------------------------------------

    async def _hours(self) -> work_hours.WorkHours | None:
        return work_hours.parse((await self.desk.settings())[1])

    async def _task(self, task_id: UUID, *, lock: bool = False) -> LeadTask:
        query = select(LeadTask).where(LeadTask.tenant_id == self.tenant_id, LeadTask.id == task_id)
        if lock:
            query = query.with_for_update()
        task = await self.db.scalar(query)
        if task is None:
            raise DeskError(404, "This task isn't on your desk.")
        # The lead must be on the viewer's desk too.
        await self.desk._lead(task.lead_id)
        return task

    async def open_for(self, lead_id: UUID) -> list[LeadTask]:
        return list(
            (
                await self.db.scalars(
                    select(LeadTask)
                    .where(
                        LeadTask.tenant_id == self.tenant_id,
                        LeadTask.lead_id == lead_id,
                        LeadTask.status == OPEN,
                    )
                    .order_by(LeadTask.starts_at, LeadTask.id)
                )
            ).all()
        )

    async def listing(self, which: TaskBucket, person: UUID | None = None) -> TaskList:
        """A seller's open tasks: overdue, today or upcoming, earliest first, and how many
        of each."""
        who = person or self.desk.viewer.person_id
        if who != self.desk.viewer.person_id and not self.desk.viewer.can_manage:
            raise DeskError(403, "Only owners and admins see someone else's tasks.")
        mine = and_(
            LeadTask.tenant_id == self.tenant_id,
            LeadTask.owner_person_id == who,
            LeadTask.status == OPEN,
        )
        late = self.now - scheduler.OVERDUE_FROM
        today_end = datetime.combine(
            self.now.astimezone(IST).date() + timedelta(days=1), time.min, tzinfo=IST
        )
        windows = {
            "overdue": LeadTask.starts_at <= late,
            "today": and_(LeadTask.starts_at > late, LeadTask.starts_at < today_end),
            "upcoming": LeadTask.starts_at >= today_end,
        }
        counts = {
            name: int(await self.db.scalar(select(func.count()).where(mine, rule)) or 0)
            for name, rule in windows.items()
        }
        rows = (
            await self.db.execute(
                select(LeadTask, Lead.name)
                .join(Lead, and_(Lead.id == LeadTask.lead_id, Lead.tenant_id == LeadTask.tenant_id))
                .where(mine, windows[which], self.desk._visible())
                .order_by(LeadTask.starts_at, LeadTask.id)
                .limit(LIST_LIMIT)
            )
        ).all()
        return TaskList(
            tasks=tuple(view(task, name, self.now) for task, name in rows),
            counts=counts,
        )

    # ----- writing ------------------------------------------------------------------

    def _event(
        self,
        lead: Lead,
        task: LeadTask,
        action: Action,
        command_id: UUID | None,
        client_at: datetime | None,
        **extra: Any,
    ) -> None:
        self.desk._event(
            lead,
            "task",
            {
                "v": 1,
                "action": action,
                "task_id": str(task.id),
                "kind": task.kind,
                "title": task.title,
                "due_at": task.starts_at.isoformat(),
                "status": task.status,
                "source": task.source,
                "client_at": client_at.isoformat() if client_at else None,
                **extra,
            },
            actor=self.desk.viewer.person_id,
            command_id=command_id,
        )

    def _may_write(self, lead: Lead) -> None:
        viewer = self.desk.viewer
        if not (viewer.can_manage or lead.owner_person_id == viewer.person_id):
            raise DeskError(403, "Only the lead's owner or a manager can change its tasks.")

    def _when(self, moment: datetime) -> datetime:
        if not self.now - EARLIEST <= moment <= self.now + LATEST:
            raise DeskError(422, "Pick a time in the next year.")
        return moment

    async def project(self, lead: Lead, closed_due: datetime | None = None) -> None:
        """The lead's next action is its earliest open task. When the last open task
        closes, a next action that was that task's due is cleared; one set the old way is
        left alone."""
        first = await self.db.scalar(
            select(LeadTask)
            .where(
                LeadTask.tenant_id == self.tenant_id,
                LeadTask.lead_id == lead.id,
                LeadTask.status == OPEN,
            )
            .order_by(LeadTask.starts_at, LeadTask.id)
            .limit(1)
        )
        if first is not None:
            lead.next_action_at = first.starts_at
            lead.next_action_note = first.title[:500]
        elif closed_due is not None and lead.next_action_at == closed_due:
            lead.next_action_at = None
            lead.next_action_note = None
        lead.updated_at = self.now

    async def create(self, lead_id: UUID, command: TaskCommand) -> TaskView:
        same = await self.db.scalar(
            select(LeadTask).where(
                LeadTask.tenant_id == self.tenant_id, LeadTask.command_id == command.command_id
            )
        )
        if same is not None:
            if same.lead_id != lead_id:
                raise DeskError(409, "That request was already used for another lead.")
            lead = await self.desk._lead(lead_id)
            return view(same, lead.name, self.now)
        lead = await self.desk._lead(lead_id, lock=True)
        self._may_write(lead)
        if command.kind not in TASK_KINDS:
            raise DeskError(422, "Pick what kind of task this is.")
        starts_at = self._when(command.starts_at)
        if command.ends_at is not None and command.ends_at <= starts_at:
            raise DeskError(422, "End the meeting after it starts.")
        task = LeadTask(
            id=uuid4(),
            tenant_id=self.tenant_id,
            lead_id=lead.id,
            owner_person_id=lead.owner_person_id,
            created_by_person_id=self.desk.viewer.person_id,
            command_id=command.command_id,
            revision=1,
            kind=command.kind,
            title=(command.title or title_for(command.kind, lead.name))[:200],
            note=command.note,
            starts_at=starts_at,
            ends_at=command.ends_at,
            location=command.location,
            status=OPEN,
            original_due_at=starts_at,
            snoozes=0,
            rollovers=0,
            source=command.source,
            source_event_id=command.source_event_id,
            remind_before_minutes=command.remind_before_minutes,
            client_at=command.client_at,
            created_at=self.now,
            updated_at=self.now,
        )
        self.db.add(task)
        self._event(lead, task, "created", command.command_id, command.client_at)
        await self.db.flush()
        await self.project(lead)
        await self.db.flush()
        return view(task, lead.name, self.now)

    async def _changing(self, task_id: UUID, command: TaskAction, action: Action) -> _Change:
        """The task, locked, and its lead when the change goes ahead. A replayed command
        answers the task as it is; a change older than the last one is kept in the
        history as superseded."""
        seen = await self.desk._command_seen(command.command_id)
        task = await self._task(task_id, lock=seen is None)
        if seen is not None:
            if str(seen.data.get("task_id")) != str(task_id):
                raise DeskError(409, "That request was already used for another task.")
            return _Change(task, None)
        lead = await self.desk._lead(task.lead_id, lock=True)
        self._may_write(lead)
        stale = (
            command.expected_revision != task.revision
            and command.client_at is not None
            and task.client_at is not None
            and command.client_at < task.client_at
        )
        if stale:
            self._event(
                lead,
                task,
                "superseded",
                command.command_id,
                command.client_at,
                tried=action,
            )
            await self.db.flush()
            return _Change(task, None)
        return _Change(task, lead)

    def _touch(self, task: LeadTask, client_at: datetime | None) -> None:
        task.revision += 1
        task.updated_at = self.now
        task.client_at = min(client_at, self.now) if client_at else self.now

    async def _answer(self, change: _Change) -> TaskView:
        lead = change.lead or await self.desk._lead(change.task.lead_id)
        return view(change.task, lead.name, self.now)

    async def done(self, task_id: UUID, command: TaskAction) -> TaskView:
        change = await self._changing(task_id, command, "done")
        task, lead = change.task, change.lead
        if lead is not None and task.status != "done":
            due = task.starts_at
            task.status = "done"
            task.done_at = self.now
            task.done_by_person_id = self.desk.viewer.person_id
            self._touch(task, command.client_at)
            self._event(lead, task, "done", command.command_id, command.client_at)
            await self.db.flush()
            await self.project(lead, closed_due=due)
            await self.db.flush()
        return await self._answer(change)

    async def undo(self, task_id: UUID, command: TaskAction) -> TaskView:
        change = await self._changing(task_id, command, "undone")
        task, lead = change.task, change.lead
        if lead is not None and task.status != OPEN:
            task.status = OPEN
            task.done_at = None
            task.done_by_person_id = None
            self._touch(task, command.client_at)
            self._event(lead, task, "undone", command.command_id, command.client_at)
            await self.db.flush()
            await self.project(lead)
            await self.db.flush()
        return await self._answer(change)

    async def cancel(self, task_id: UUID, command: TaskAction) -> TaskView:
        change = await self._changing(task_id, command, "cancelled")
        task, lead = change.task, change.lead
        if lead is not None and task.status == OPEN:
            due = task.starts_at
            task.status = "cancelled"
            self._touch(task, command.client_at)
            self._event(lead, task, "cancelled", command.command_id, command.client_at)
            await self.db.flush()
            await self.project(lead, closed_due=due)
            await self.db.flush()
        return await self._answer(change)

    async def snooze(self, task_id: UUID, command: TaskSnooze) -> TaskView:
        change = await self._changing(task_id, command, "snoozed")
        task, lead = change.task, change.lead
        if lead is not None and task.status == OPEN:
            before = task.starts_at
            facts = scheduler.TaskFacts(str(task.id), task.kind, task.starts_at)  # type: ignore[arg-type]
            task.starts_at = scheduler.snoozed(facts, command.choice, self.now, await self._hours())
            if task.ends_at is not None:
                task.ends_at = task.starts_at + (task.ends_at - before)
            task.snoozes += 1
            self._touch(task, command.client_at)
            self._event(
                lead,
                task,
                "snoozed",
                command.command_id,
                command.client_at,
                from_due_at=before.isoformat(),
                choice=command.choice,
            )
            await self.db.flush()
            await self.project(lead)
            await self.db.flush()
        return await self._answer(change)

    async def change(self, task_id: UUID, command: TaskChange) -> TaskView:
        change = await self._changing(task_id, command, "changed")
        task, lead = change.task, change.lead
        if lead is not None and task.status == OPEN:
            before = task.starts_at
            if command.starts_at is not None:
                task.starts_at = self._when(command.starts_at)
            if command.ends_at is not None:
                task.ends_at = command.ends_at
            if task.ends_at is not None and task.ends_at <= task.starts_at:
                raise DeskError(422, "End the meeting after it starts.")
            for name in ("kind", "location", "note", "title"):
                value = getattr(command, name)
                if value is not None:
                    setattr(task, name, value)
            self._touch(task, command.client_at)
            self._event(
                lead,
                task,
                "changed",
                command.command_id,
                command.client_at,
                from_due_at=before.isoformat() if before != task.starts_at else None,
            )
            await self.db.flush()
            await self.project(lead)
            await self.db.flush()
        return await self._answer(change)


async def follow_owner(desk: LeadDesk, lead: Lead, person_id: UUID | None) -> int:
    """A reassigned lead's open tasks go with it to its new owner, with one history line
    each. How many moved."""
    moved = (
        await desk.db.scalars(
            update(LeadTask)
            .where(
                LeadTask.tenant_id == desk.tenant_id,
                LeadTask.lead_id == lead.id,
                LeadTask.status == OPEN,
                LeadTask.owner_person_id.is_distinct_from(person_id),
            )
            .values(
                owner_person_id=person_id,
                revision=LeadTask.revision + 1,
                updated_at=desk.now,
            )
            .returning(LeadTask)
            .execution_options(synchronize_session=False)
        )
    ).all()
    for task in moved:
        desk._event(
            lead,
            "task",
            {
                "v": 1,
                "action": "reassigned",
                "task_id": str(task.id),
                "kind": task.kind,
                "title": task.title,
                "due_at": task.starts_at.isoformat(),
                "status": task.status,
                "source": task.source,
                "to": str(person_id) if person_id else None,
            },
            actor=desk.viewer.person_id,
        )
    return len(moved)


def day_of(moment: datetime) -> date:
    return moment.astimezone(IST).date()
