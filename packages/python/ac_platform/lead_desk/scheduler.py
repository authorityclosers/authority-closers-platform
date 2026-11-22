"""When to remind a seller of a task (work-memory engine, section 5;
docs/product/lead-desk/work-memory-engine.md).

Each due of an open task reminds once (orchestrator, 24 Oct 2026: "a promise at 5:30
makes a reminder at 5:25, overdue at 5:31, one notification only"): a little before it is
due when its kind wants that (a call back, a meeting), else when it is due. From a minute
after the due it shows as overdue everywhere, without another push. Outside the seller's
work hours the reminder waits for work to start, and says overdue if the due has passed by
then; a meeting still reminds, its time was agreed.

Each reminder has a key, (task, kind, the due it is for): the sender records the key
before it sends, so a reminder goes once, a snoozed task reminds once for each new due,
and two senders never both send (the ledger, ``lead_desk_task_reminders``).

Pure: tasks, work hours and a clock in; reminders, overdue and rollover out. India time,
which has no daylight saving.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.commitments import TaskKind

IST: Final = ZoneInfo("Asia/Kolkata")

ReminderKind = Literal["before", "due", "overdue"]
TaskStatus = Literal["open", "done", "cancelled"]
Snooze = Literal["15m", "1h", "evening", "tomorrow", "week"]

# A reminder before the due time, by kind (design, 2.4). A meeting in person needs the
# drive; an online one, a few minutes.
REMIND_BEFORE: Final[dict[TaskKind, timedelta]] = {
    "call_back": timedelta(minutes=5),
    "whatsapp": timedelta(0),
    "email": timedelta(0),
    "send_file": timedelta(0),
    "meeting": timedelta(minutes=30),
    "other": timedelta(0),
}
MEETING_IN_PERSON_BEFORE: Final = timedelta(hours=2)
# Overdue shows from a minute after the due.
OVERDUE_FROM: Final = timedelta(minutes=1)
# Nothing older than this is sent (a phone that registers late is not flooded).
STALE: Final = timedelta(hours=2)
# A due set this close to now reminds at the due itself, never early (owner, 22 Nov 2026:
# "In 2 min" buzzed at once, 5 minutes before a due only 2 minutes away, and never at the
# time). A meeting keeps its early reminder: that is time to get there.
SHORT_NOTICE: Final = timedelta(hours=1)
_RANK: Final[dict[ReminderKind, int]] = {"before": 0, "due": 1, "overdue": 2}


@dataclass(frozen=True, slots=True)
class TaskFacts:
    """What the planner needs of a task."""

    task_id: str
    kind: TaskKind
    starts_at: datetime
    status: TaskStatus = "open"
    remind_before: timedelta | None = None
    in_person: bool = False
    # When the due was last set (the task's last change); None: unknown, the early
    # reminder stands.
    set_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Reminder:
    task_id: str
    kind: ReminderKind
    # The due this reminder is for: a snooze makes a new due, and new reminders.
    for_due_at: datetime
    send_at: datetime
    # Moved to the start of work.
    deferred: bool = False

    @property
    def key(self) -> tuple[str, ReminderKind, datetime]:
        return (self.task_id, self.kind, self.for_due_at)


def lead_time(task: TaskFacts) -> timedelta:
    if task.remind_before is not None:
        before = max(timedelta(0), task.remind_before)
    elif task.kind == "meeting" and task.in_person:
        before = MEETING_IN_PERSON_BEFORE
    else:
        before = REMIND_BEFORE[task.kind]
    if not before or task.set_at is None:
        return before
    gap = task.starts_at - task.set_at
    # Early would be at once (the due is closer than the lead time): at the due instead.
    if gap <= before + OVERDUE_FROM:
        return timedelta(0)
    # Set for soon by the seller: the time they picked is the reminder (not a meeting's).
    if task.kind != "meeting" and task.remind_before is None and gap <= SHORT_NOTICE:
        return timedelta(0)
    return before


def plan(task: TaskFacts, hours: work_hours.WorkHours | None = None) -> list[Reminder]:
    """The one reminder of a task's current due (none once it is done or cancelled)."""
    if task.status != "open":
        return []
    due = task.starts_at
    before = lead_time(task)
    reminder = Reminder(task.task_id, "before" if before else "due", due, due - before)
    if (
        hours is not None
        and task.kind != "meeting"
        and not work_hours.inside(hours, reminder.send_at)
    ):
        moved = work_hours.next_start(hours, reminder.send_at)
        reminder = replace(
            reminder,
            kind="overdue" if moved >= due + OVERDUE_FROM else reminder.kind,
            send_at=moved,
            deferred=True,
        )
    return [reminder]


def due_now(
    tasks: Iterable[TaskFacts],
    sent: set[tuple[str, ReminderKind, datetime]],
    now: datetime,
    hours: work_hours.WorkHours | None = None,
) -> list[Reminder]:
    """What to send now: due, not sent before, and not stale. When a task has more than
    one waiting (the sender was down), only the most pressing goes. A due that already
    reminded, of any kind, never reminds again (an edit that moves "before" to "due")."""
    reminded = {(task_id, for_due_at) for task_id, _, for_due_at in sent}
    out: list[Reminder] = []
    for task in tasks:
        waiting = [
            reminder
            for reminder in plan(task, hours)
            if reminder.send_at <= now
            and reminder.key not in sent
            and (reminder.task_id, reminder.for_due_at) not in reminded
            and now - reminder.send_at <= STALE
        ]
        if waiting:
            out.append(max(waiting, key=lambda item: (_RANK[item.kind], item.send_at)))
    return out


def overdue(task: TaskFacts, now: datetime) -> bool:
    """Late from a minute after its due, for as long as it is open."""
    return task.status == "open" and now >= task.starts_at + OVERDUE_FROM


def minutes_overdue(task: TaskFacts, now: datetime) -> int:
    if not overdue(task, now):
        return 0
    return int((now - task.starts_at).total_seconds() // 60)


def snoozed(
    task: TaskFacts,
    choice: Snooze,
    now: datetime,
    hours: work_hours.WorkHours | None = None,
) -> datetime:
    """The new due of a snooze: 15 minutes, an hour, this evening (18:00, or tomorrow's
    start when the evening has passed), tomorrow's start of work, or the same day next week
    at the start of work (10:00 without hours). Always after ``now``."""
    local = now.astimezone(IST)
    start = hours.start if hours is not None else time(10, 0)
    if choice == "week":
        # Home's swipe-left offers the after-call's times (competitor teardown #1).
        moment = datetime.combine(local.date() + timedelta(days=7), start, tzinfo=IST)
        return work_hours.next_start(hours, moment) if hours is not None else moment
    if choice == "15m":
        return now + timedelta(minutes=15)
    if choice == "1h":
        return now + timedelta(hours=1)
    if choice == "evening":
        evening = datetime.combine(local.date(), time(18, 0), tzinfo=IST)
        if evening > local + timedelta(minutes=15):
            return evening
    tomorrow = local.date() + timedelta(days=1)
    moment = datetime.combine(tomorrow, start, tzinfo=IST)
    if hours is not None:
        moment = work_hours.next_start(hours, moment)
    return moment


def day_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return datetime.combine(local.date(), time.min, tzinfo=IST)


def rolled_over(tasks: Iterable[TaskFacts], now: datetime) -> list[TaskFacts]:
    """Open tasks from before today: Today shows them as "from yesterday", once each, and
    nothing is copied."""
    start = day_start(now)
    return [task for task in tasks if task.status == "open" and task.starts_at < start]
