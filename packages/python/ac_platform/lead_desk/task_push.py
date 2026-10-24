"""Task reminders on the seller's phone (work-memory engine, section 5;
docs/product/lead-desk/work-memory-engine.md).

Each due of an open task reminds once: a little before it for a call back or a meeting,
else when it is due (``scheduler.plan``). The sender writes the reminder's key to the
ledger (``lead_desk_task_reminders``) before it sends, so a reminder goes once, a snoozed
task reminds once for its new due, and two senders never both send.

It runs inside the lead alerts' pass (``push.collect``), under the same lock: its leads
join that pass's alerts, so a seller still gets one push per pass. A task that is its
lead's next action also marks that lead's due alert as sent, so the same due never
pushes twice (orchestrator, 24 Oct 2026: "a promise at 5:30 makes a reminder at 5:25,
overdue at 5:31, one notification only").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final, cast
from uuid import uuid4

from sqlalchemy import and_, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ac_platform.lead_desk import scheduler
from ac_platform.lead_desk.models import Lead, LeadDevice, LeadTask, LeadTaskReminder

BATCH: Final = 200
# The longest a reminder goes before its due: a task's own lead time is at most a day.
LOOK_AHEAD: Final = timedelta(days=1)


def facts(task: LeadTask) -> scheduler.TaskFacts:
    """What the planner needs of a stored task."""
    place = (task.location or "").strip().lower()
    return scheduler.TaskFacts(
        task_id=str(task.id),
        kind=task.kind,  # type: ignore[arg-type]
        starts_at=task.starts_at,
        status=task.status,  # type: ignore[arg-type]
        remind_before=(
            None
            if task.remind_before_minutes is None
            else timedelta(minutes=task.remind_before_minutes)
        ),
        # A meeting at a place, not a link: the drive needs more time.
        in_person=task.kind == "meeting" and bool(place) and not place.startswith("http"),
    )


async def collect(database: AsyncSession, now: datetime) -> list[Lead]:
    """The leads whose task reminds now, each reminder recorded in the ledger (the caller
    commits, then sends)."""
    has_device = exists().where(
        LeadDevice.tenant_id == LeadTask.tenant_id,
        LeadDevice.person_id == LeadTask.owner_person_id,
    )
    rows = (
        await database.execute(
            select(LeadTask, Lead)
            .join(Lead, and_(Lead.tenant_id == LeadTask.tenant_id, Lead.id == LeadTask.lead_id))
            .where(
                LeadTask.status == "open",
                LeadTask.owner_person_id.is_not(None),
                LeadTask.starts_at > now - scheduler.STALE,
                LeadTask.starts_at <= now + LOOK_AHEAD,
                has_device,
            )
            .order_by(LeadTask.starts_at, LeadTask.id)
            .limit(BATCH)
            .with_for_update(of=LeadTask, skip_locked=True)
        )
    ).all()
    if not rows:
        return []
    tasks = {str(task.id): (task, lead) for task, lead in rows}
    sent = {
        (str(task_id), cast(scheduler.ReminderKind, kind), for_due_at)
        for task_id, kind, for_due_at in (
            await database.execute(
                select(
                    LeadTaskReminder.task_id, LeadTaskReminder.kind, LeadTaskReminder.for_due_at
                ).where(LeadTaskReminder.task_id.in_([task.id for task, _ in rows]))
            )
        ).tuples()
    }
    leads: list[Lead] = []
    for reminder in scheduler.due_now((facts(task) for task, _ in rows), sent, now):
        task, lead = tasks[reminder.task_id]
        claimed = await database.scalar(
            insert(LeadTaskReminder)
            .values(
                id=uuid4(),
                tenant_id=task.tenant_id,
                task_id=task.id,
                kind=reminder.kind,
                for_due_at=reminder.for_due_at,
                send_at=reminder.send_at,
                deferred=reminder.deferred,
                claimed_at=now,
                sent_at=now,
            )
            .on_conflict_do_nothing(index_elements=["task_id", "kind", "for_due_at"])
            .returning(LeadTaskReminder.id)
        )
        if claimed is None:
            continue
        # The lead's own due alert is this same promise: it is sent now.
        if lead.next_action_at == task.starts_at:
            lead.alerted_due_at = lead.next_action_at
        if lead.owner_person_id == task.owner_person_id:
            leads.append(lead)
    return leads
