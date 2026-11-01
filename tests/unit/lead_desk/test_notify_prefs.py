"""Each person's notification choices (competitor teardown 26, 1 Nov 2026): every type is on
and on time, and quiet hours off, until the person changes it; quiet hours follow the team's
working hours, except a follow-up the person set themselves; a follow-up can come 15 minutes
or an hour early."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from ac_platform.lead_desk import notify_prefs

IST = ZoneInfo("Asia/Kolkata")
HOURS = {"days": [0, 1, 2, 3, 4, 5], "start": "10:30", "end": "19:00"}
MONDAY_NOON = datetime(2026, 11, 2, 12, 0, tzinfo=IST)
MONDAY_NIGHT = datetime(2026, 11, 2, 22, 0, tzinfo=IST)


def test_everything_on_and_on_time_by_default() -> None:
    person = uuid4()
    prefs = notify_prefs.read({}, person)
    assert all(prefs.on.values())
    assert prefs.due_lead_minutes == 0 and prefs.quiet is False
    assert notify_prefs.due_lead({}, person) == timedelta(0)
    # No working hours: every hour counts, so nothing is quiet.
    assert notify_prefs.allows({}, person, "new_enquiry", MONDAY_NIGHT)


def test_quiet_hours_follow_working_hours_but_not_a_follow_up() -> None:
    person = uuid4()
    # Off by default: outside working hours everything still reaches the phone.
    assert notify_prefs.allows({"work_hours": HOURS}, person, "new_enquiry", MONDAY_NIGHT)
    config = {"work_hours": HOURS, "notify": {str(person): {"quiet": True}}}
    assert notify_prefs.allows(config, person, "new_enquiry", MONDAY_NOON)
    assert not notify_prefs.allows(config, person, "new_enquiry", MONDAY_NIGHT)
    assert not notify_prefs.allows(config, person, "team_alerts", MONDAY_NIGHT)
    assert notify_prefs.allows(config, person, "follow_up_due", MONDAY_NIGHT)
    loud = {"work_hours": HOURS, "notify": {str(person): {"quiet": False}}}
    assert notify_prefs.allows(loud, person, "new_enquiry", MONDAY_NIGHT)


def test_a_person_turns_a_type_off_and_hears_follow_ups_early() -> None:
    person, other = uuid4(), uuid4()
    config = {
        "notify": {
            str(person): {"missed_follow_up": False, "due_lead_minutes": 60},
            str(other): {"due_lead_minutes": 7},
        }
    }
    assert not notify_prefs.allows(config, person, "missed_follow_up", MONDAY_NOON)
    assert notify_prefs.allows(config, other, "missed_follow_up", MONDAY_NOON)
    assert notify_prefs.due_lead(config, person) == timedelta(hours=1)
    # Only at the time, 15 minutes or an hour count.
    assert notify_prefs.due_lead(config, other) == timedelta(0)


def test_working_hours_in_words() -> None:
    assert notify_prefs.hours_words({"work_hours": HOURS}) == "10:30–7:00, Mon–Sat"
    assert notify_prefs.hours_words({}) is None
