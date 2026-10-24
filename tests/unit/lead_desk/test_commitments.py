"""Promises become proposals (work-memory engine, section 4; acceptance 1-7). Times are
India time; a promise is never in the past."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta

from ac_platform.lead_desk import hours as work_hours
from ac_platform.lead_desk.commitments import IST, Proposal, propose

# Friday 23 Oct 2026.
FRIDAY = datetime(2026, 10, 23, tzinfo=IST)


def at(hour: int, minute: int = 0, days: int = 0) -> datetime:
    return FRIDAY.replace(hour=hour, minute=minute) + timedelta(days=days)


def one(
    text: str,
    written: datetime,
    after_call: bool = False,
    inside: Callable[[datetime], bool] | None = None,
) -> Proposal:
    found = propose(text, written, lead_name="Asha Fictional", after_call=after_call, inside=inside)
    assert len(found) == 1, found
    return found[0]


def test_at01_call_back_at_5_30_after_a_call() -> None:
    proposal = one("Busy now. Call back at 5:30", at(16, 10), after_call=True)
    assert proposal.kind == "call_back"
    assert proposal.starts_at == at(17, 30)
    assert proposal.title == "Call back Asha Fictional"
    assert proposal.confidence == 0.9


def test_at02_tomorrow_evening_typed_at_night() -> None:
    proposal = one("Call tomorrow evening", at(21, 0))
    assert (proposal.kind, proposal.starts_at) == ("call_back", at(18, 0, days=1))
    assert proposal.confidence == 0.75


def test_at03_marathi_tomorrow_morning_11() -> None:
    proposal = one("उद्या सकाळी 11 वाजता फोन करा", at(16, 0))
    assert (proposal.kind, proposal.starts_at) == ("call_back", at(11, 0, days=1))


def test_at03_devanagari_digits_are_read() -> None:
    proposal = one("उद्या ११ वाजता फोन करा", at(16, 0))
    assert proposal.starts_at == at(11, 0, days=1)


def test_at04_hinglish_whatsapp_tomorrow_evening_6() -> None:
    proposal = one("kal shaam 6 baje whatsapp bhejna", at(12, 0))
    assert (proposal.kind, proposal.starts_at) == ("whatsapp", at(18, 0, days=1))


def test_at05_meeting_thursday_4pm_at_an_office() -> None:
    proposal = one("Meeting Thursday 4pm at Baner office", at(12, 0))
    assert proposal.kind == "meeting"
    # Friday's next Thursday.
    assert proposal.starts_at == at(16, 0, days=6)
    assert proposal.ends_at == at(17, 0, days=6)
    assert proposal.location == "Baner Office"


def test_at06_send_brochure_with_no_time_is_in_an_hour() -> None:
    proposal = one("Send brochure", at(15, 0))
    assert (proposal.kind, proposal.starts_at) == ("send_file", at(16, 0))
    assert proposal.confidence == 0.6


def test_at07_a_note_with_no_promise_proposes_nothing() -> None:
    assert propose("Spoke to her husband, interested in 2 BHK", at(15, 0)) == []
    # A time alone counts only after a call.
    assert propose("5:30", at(15, 0)) == []
    assert [item.kind for item in propose("5:30", at(15, 0), after_call=True)] == ["call_back"]


def test_a_time_already_gone_today_means_tomorrow() -> None:
    proposal = one("call at 11", at(15, 0))
    assert proposal.starts_at == at(11, 0, days=1)


def test_relative_times_and_two_promises_in_one_note() -> None:
    found = propose(
        "Call me in 2 hours. Also send the price list on email tomorrow",
        at(10, 0),
        lead_name="Rohan Sample",
    )
    assert [(item.kind, item.starts_at) for item in found] == [
        ("call_back", at(12, 0)),
        ("email", at(10, 0, days=1)),
    ]


def test_the_same_promise_twice_is_one_proposal() -> None:
    found = propose("call back at 5. ok call at 5:15", at(12, 0))
    assert len(found) == 1 and found[0].starts_at == at(17, 0)


def test_a_promise_outside_work_hours_stays_and_is_marked() -> None:
    hours = work_hours.WorkHours((0, 1, 2, 3, 4, 5), time(10, 0), time(19, 0), False)
    proposal = one(
        "call at 9pm",
        at(12, 0),
        inside=lambda moment: work_hours.inside(hours, moment),
    )
    assert proposal.starts_at == at(21, 0) and proposal.outside_hours


def test_property_a_promise_is_never_in_the_past() -> None:
    """Any of these phrases, written at any minute of any day of a month, resolves after
    the moment it was written (2,000 seeded cases)."""
    phrases = [
        "call back at {h}:{m:02d}",
        "call at {h}",
        "kal {h} baje phone karna",
        "today {h}pm whatsapp",
        "aaj shaam call",
        "उद्या सकाळी फोन करा",
        "meeting {day} at {h} at Kothrud office",
        "send brochure",
        "email in {n} hours",
        "call tonight",
        "parso subah call",
        "next week call",
    ]
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    chooser = random.Random(20261024)  # noqa: S311 (seeded test cases, not security)
    for _ in range(2000):
        written = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(
            minutes=chooser.randrange(0, 31 * 24 * 60)
        )
        text = chooser.choice(phrases).format(
            h=chooser.randrange(1, 13),
            m=chooser.randrange(0, 60),
            day=chooser.choice(days),
            n=chooser.randrange(1, 9),
        )
        for proposal in propose(text, written, after_call=True):
            assert proposal.starts_at > written, (text, written, proposal)
            if proposal.ends_at is not None:
                assert proposal.ends_at > proposal.starts_at
