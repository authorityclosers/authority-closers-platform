from datetime import UTC, date, datetime
from uuid import UUID

from ac_platform.lead_desk.capture_guard_nudges import slot
from ac_platform.lead_desk.capture_reminder import (
    BODY,
    as_bell,
    calls_href,
    reminder_day,
    reminder_key,
    words,
)

TENANT = UUID("00000000-0000-4000-8000-000000000001")


def test_daily_slot_is_19_india_time_not_server_timezone():
    assert slot(datetime(2026, 10, 29, 13, 29, 59, tzinfo=UTC)) is None
    due = slot(datetime(2026, 10, 29, 13, 30, tzinfo=UTC))
    assert due is not None and due.hour == 19
    assert slot(datetime(2026, 10, 29, 18, 29, tzinfo=UTC)) == due
    assert slot(datetime(2026, 10, 29, 18, 30, tzinfo=UTC)) is None


def test_nudge_names_its_day_and_one_plain_fix():
    # Persona QA, 31 Oct 2026: yesterday's unread "28 calls today have no recording" next
    # to Home's "Tried 0". The bell line names its own day and never says "today".
    assert words(1, date(2026, 10, 30))[0] == "30 Oct: 1 call had no recording"
    assert words(3, date(2026, 10, 30))[0] == "30 Oct: 3 calls had no recording"
    assert "today" not in words(3, date(2026, 10, 30))[0]
    # Honest about when it comes (ph1-53: no card for today's calls before 19:00).
    assert words(3, date(2026, 10, 30))[1] == BODY
    assert BODY.startswith("Comes at 7 pm") and "top of Calls" in BODY
    # Counted again to none: it says so, never "0 calls".
    assert words(0, date(2026, 10, 30))[0] == "30 Oct: every call has its recording now"


def test_the_bell_never_pops_the_reminder_and_names_older_rows_by_their_day():
    key = reminder_key(TENANT, date(2026, 10, 30))
    assert key == f"capture-missing:{TENANT}:2026-10-30"
    # A row written before the rule: urgent, "today". Read as not urgent, with its day.
    # Its See why opens that day's calls without a recording (ph1-27), old rows too.
    calls = "/analysis/calls?no-recording=2026-10-30"
    assert calls_href(date(2026, 10, 30)) == calls
    assert as_bell(
        key, "28 calls today have no recording: fix", True, "/settings/privacy#calls-setup"
    ) == ("30 Oct: 28 calls had no recording", False, calls)
    assert as_bell(key, "30 Oct: 2 calls had no recording", False, calls) == (
        "30 Oct: 2 calls had no recording",
        False,
        calls,
    )
    # Every other bell line keeps its own title, urgency and link.
    assert as_bell("lead-assigned:x", "New lead", True, "/leads?lead=x") == (
        "New lead",
        True,
        "/leads?lead=x",
    )
    assert as_bell(None, "Report ready", False) == ("Report ready", False, None)
    # A key it can't read still never pops up.
    assert as_bell(
        "capture-missing:broken", "2 calls today have no recording: fix", True, "/x"
    ) == ("2 calls today have no recording: fix", False, "/x")


def test_the_card_says_the_days_count_now_so_the_calls_it_opens_agree():
    # Phone personas ph1-53 (v1.25): the card said 4, the calls it opened none.
    key = reminder_key(TENANT, date(2026, 10, 30))
    calls = "/analysis/calls?no-recording=2026-10-30"
    assert reminder_day(key) == date(2026, 10, 30)
    assert reminder_day("lead-assigned:x") is None and reminder_day(None) is None
    assert as_bell(key, "30 Oct: 4 calls had no recording", False, calls, count=1) == (
        "30 Oct: 1 call had no recording",
        False,
        calls,
    )
    assert as_bell(key, "30 Oct: 4 calls had no recording", False, calls, count=0)[0] == (
        "30 Oct: every call has its recording now"
    )
    # Any other line keeps its words whatever it is given.
    assert as_bell("lead-assigned:x", "New lead", True, "/leads", count=3)[0] == "New lead"
