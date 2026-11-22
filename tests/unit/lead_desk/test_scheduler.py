"""When a task reminds (work-memory engine, section 5; acceptance 1, 9, 10, 11): one
reminder per due, overdue from a minute after it, quiet hours, snooze, rollover."""

from __future__ import annotations

import random
from datetime import datetime, time, timedelta
from typing import get_args

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.commitments import IST
from ac_platform.lead_desk.scheduler import (
    Reminder,
    Snooze,
    TaskFacts,
    due_now,
    minutes_overdue,
    overdue,
    plan,
    rolled_over,
    snoozed,
)

FRIDAY = datetime(2026, 10, 23, tzinfo=IST)  # a Friday
WORK = work_hours.WorkHours((0, 1, 2, 3, 4, 5), time(10, 0), time(19, 0), False)


def at(hour: int, minute: int = 0, days: int = 0) -> datetime:
    return FRIDAY.replace(hour=hour, minute=minute) + timedelta(days=days)


def test_at01_a_5_30_call_back_reminds_once_at_5_25_and_is_late_from_5_31() -> None:
    task = TaskFacts("t1", "call_back", at(17, 30))
    assert plan(task, WORK) == [Reminder("t1", "before", at(17, 30), at(17, 25))]
    sent: set = set()
    pushed = []
    for minute in range(0, 120):
        now = at(17, 0) + timedelta(minutes=minute)
        for reminder in due_now([task], sent, now, WORK):
            sent.add(reminder.key)
            pushed.append(now)
    assert pushed == [at(17, 25)]
    assert not overdue(task, at(17, 30))
    assert not overdue(task, at(17, 30) + timedelta(seconds=59))
    assert overdue(task, at(17, 31))
    assert minutes_overdue(task, at(17, 50)) == 20


def test_a_whatsapp_task_reminds_at_its_due_and_a_meeting_two_hours_before() -> None:
    assert plan(TaskFacts("w", "whatsapp", at(12, 0)))[0].send_at == at(12, 0)
    meeting = TaskFacts("m", "meeting", at(16, 0), in_person=True)
    assert plan(meeting)[0].send_at == at(14, 0)
    online = TaskFacts("o", "meeting", at(16, 0))
    assert plan(online)[0].send_at == at(15, 30)


def test_at09_snoozes_remind_once_for_each_new_due() -> None:
    task = TaskFacts("t2", "call_back", at(12, 0))
    sent: set = set()
    pushed: list[Reminder] = []

    def tick(start: datetime, until: datetime) -> None:
        now = start
        while now <= until:
            for reminder in due_now([task], sent, now, WORK):
                sent.add(reminder.key)
                pushed.append(reminder)
            now += timedelta(minutes=1)

    tick(at(11, 50), at(12, 2))
    task = TaskFacts("t2", "call_back", snoozed(task, "15m", at(12, 2)))
    tick(at(12, 3), at(12, 20))
    task = TaskFacts("t2", "call_back", snoozed(task, "15m", at(12, 20)))
    tick(at(12, 21), at(12, 40))
    assert [reminder.send_at for reminder in pushed] == [at(11, 55), at(12, 12), at(12, 30)]
    keys = [reminder.key for reminder in pushed]
    assert len(keys) == len(set(keys))
    # Done after the second snooze: nothing more.
    assert plan(TaskFacts("t2", "call_back", task.starts_at, status="done")) == []


def test_at10_a_late_night_due_reminds_at_the_start_of_work_and_says_overdue() -> None:
    task = TaskFacts("t3", "call_back", at(22, 30))
    [reminder] = plan(task, WORK)
    assert reminder.send_at == at(10, 0, days=1)
    assert (reminder.kind, reminder.deferred) == ("overdue", True)
    assert overdue(task, at(22, 31))


def test_a_meeting_reminds_even_outside_work_hours() -> None:
    task = TaskFacts("m", "meeting", at(20, 0))
    assert plan(task, WORK)[0].send_at == at(19, 30)


def test_at11_yesterdays_open_tasks_roll_into_today_once() -> None:
    tasks = [
        TaskFacts("a", "call_back", at(15, 0)),
        TaskFacts("b", "whatsapp", at(18, 0)),
        TaskFacts("c", "email", at(9, 0, days=1)),
        TaskFacts("d", "call_back", at(16, 0), status="done"),
    ]
    assert [task.task_id for task in rolled_over(tasks, at(9, 0, days=1))] == ["a", "b"]


def test_snooze_choices() -> None:
    task = TaskFacts("s", "call_back", at(12, 0))
    assert snoozed(task, "15m", at(12, 5)) == at(12, 20)
    assert snoozed(task, "1h", at(12, 5)) == at(13, 5)
    assert snoozed(task, "evening", at(12, 5)) == at(18, 0)
    # After the evening: tomorrow at the start of work.
    assert snoozed(task, "evening", at(18, 30), WORK) == at(10, 0, days=1)
    # Saturday's tomorrow is a Sunday off: Monday.
    assert snoozed(task, "tomorrow", at(12, 0, days=1), WORK) == at(10, 0, days=3)
    # Next week: the same day a week on, at the start of work (Home's swipe-left).
    assert snoozed(task, "week", at(12, 5)) == at(10, 0, days=7)
    assert snoozed(task, "week", at(12, 5), WORK) == at(10, 0, days=7)


def test_stale_reminders_are_not_sent() -> None:
    task = TaskFacts("x", "whatsapp", at(9, 0))
    assert due_now([task], set(), at(12, 0)) == []


def test_property_one_reminder_per_due_through_any_snooze_chain() -> None:
    """1,000 seeded chains of snoozes and reschedules, a sender ticking every minute,
    sometimes twice (two workers): never two reminders for one (task, kind, due), and
    an open task past its due is always overdue."""
    chooser = random.Random(24)  # noqa: S311 (seeded test cases, not security)
    choices = get_args(Snooze)
    for chain in range(1000):
        due = at(9, 0) + timedelta(minutes=chooser.randrange(0, 36 * 60))
        task = TaskFacts(f"t{chain}", chooser.choice(["call_back", "whatsapp", "meeting"]), due)
        sent: set = set()
        keys: list = []
        now = due - timedelta(hours=3)
        for _ in range(chooser.randrange(1, 5)):
            end = task.starts_at + timedelta(minutes=chooser.randrange(0, 90))
            while now <= end:
                for _worker in range(chooser.choice([1, 2])):
                    for reminder in due_now([task], sent, now, WORK):
                        if reminder.key in sent:
                            continue
                        sent.add(reminder.key)
                        keys.append(reminder.key)
                if now >= task.starts_at + timedelta(minutes=1):
                    assert overdue(task, now)
                now += timedelta(minutes=1)
            task = TaskFacts(
                task.task_id, task.kind, snoozed(task, chooser.choice(choices), now, WORK)
            )
            assert task.starts_at > now - timedelta(minutes=1)
        assert len(keys) == len(set(keys))
        per_due = [(key[0], key[2]) for key in keys]
        assert len(per_due) == len(set(per_due))


# Owner, 22 Nov 2026: "In 2 min" buzzed at once (5 minutes early for a due 2 minutes away)
# and never at the time. A due set for soon reminds at the time the seller picked.
def test_a_call_back_set_for_soon_reminds_at_its_due() -> None:
    set_at = at(20, 40)
    for minutes in (1, 2, 5, 15, 30, 60):
        due = set_at + timedelta(minutes=minutes)
        task = TaskFacts("q", "call_back", due, set_at=set_at)
        assert plan(task) == [Reminder("q", "due", due, due)], minutes
    # Set well ahead: the heads-up 5 minutes before stays.
    later = TaskFacts("q", "call_back", at(22, 0), set_at=set_at)
    assert plan(later)[0].send_at == at(21, 55)
    # Unknown when it was set: as before.
    assert plan(TaskFacts("q", "call_back", at(20, 42)))[0].send_at == at(20, 37)


def test_an_early_reminder_that_would_come_at_once_comes_at_the_due() -> None:
    set_at = at(12, 0)
    # "Remind me 15 minutes early" on a task 10 minutes away: at the due.
    soon = TaskFacts(
        "e", "whatsapp", at(12, 10), remind_before=timedelta(minutes=15), set_at=set_at
    )
    assert plan(soon)[0].send_at == at(12, 10)
    # 40 minutes away: the seller asked for early, so 15 minutes before.
    asked = TaskFacts(
        "e", "whatsapp", at(12, 40), remind_before=timedelta(minutes=15), set_at=set_at
    )
    assert plan(asked)[0].send_at == at(12, 25)
    # A meeting in 45 minutes keeps its 30 minutes to get ready.
    meeting = TaskFacts("m", "meeting", at(12, 45), set_at=set_at)
    assert plan(meeting)[0].send_at == at(12, 15)
    # A meeting in 20 minutes: at its time, not at once.
    close = TaskFacts("m", "meeting", at(12, 20), set_at=set_at)
    assert plan(close)[0].send_at == at(12, 20)


def test_a_due_that_reminded_never_reminds_again_after_an_edit() -> None:
    due = at(18, 0)
    early = TaskFacts("x", "call_back", due, set_at=at(15, 0))
    [first] = due_now([early], set(), at(17, 55))
    assert first.kind == "before"
    # A note edit at 17:56 makes it "set for soon"; the due already reminded.
    edited = TaskFacts("x", "call_back", due, set_at=at(17, 56))
    assert due_now([edited], {first.key}, at(18, 0)) == []


def test_short_reminders_go_within_the_senders_tick() -> None:
    # The sender looks every 10 seconds: a 1-minute reminder goes 60 to 70 s after it is set.
    set_at = at(9, 0) + timedelta(seconds=37)
    task = TaskFacts("t", "call_back", set_at + timedelta(minutes=1), set_at=set_at)
    sent: set = set()
    pushed = []
    for tick in range(0, 30):
        now = at(9, 0) + timedelta(seconds=10 * tick)
        for reminder in due_now([task], sent, now):
            sent.add(reminder.key)
            pushed.append(now)
    assert len(pushed) == 1
    assert timedelta(0) <= pushed[0] - task.starts_at < timedelta(seconds=10)
