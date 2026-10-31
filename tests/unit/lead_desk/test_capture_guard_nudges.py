from datetime import UTC, date, datetime
from uuid import UUID

from ac_platform.lead_desk.capture_guard_nudges import slot
from ac_platform.lead_desk.capture_reminder import as_bell, reminder_key, words

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
    assert words(3, date(2026, 10, 30))[1].startswith("Pick the missing recordings")


def test_the_bell_never_pops_the_reminder_and_names_older_rows_by_their_day():
    key = reminder_key(TENANT, date(2026, 10, 30))
    assert key == f"capture-missing:{TENANT}:2026-10-30"
    # A row written before the rule: urgent, "today". Read as not urgent, with its day.
    assert as_bell(key, "28 calls today have no recording: fix", True) == (
        "30 Oct: 28 calls had no recording",
        False,
    )
    assert as_bell(key, "30 Oct: 2 calls had no recording", False) == (
        "30 Oct: 2 calls had no recording",
        False,
    )
    # Every other bell line keeps its own title and urgency.
    assert as_bell("lead-assigned:x", "New lead", True) == ("New lead", True)
    assert as_bell(None, "Report ready", False) == ("Report ready", False)
    # A key it can't read still never pops up.
    assert as_bell("capture-missing:broken", "2 calls today have no recording: fix", True) == (
        "2 calls today have no recording: fix",
        False,
    )
