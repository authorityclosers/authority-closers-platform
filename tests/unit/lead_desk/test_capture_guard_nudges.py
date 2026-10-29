from datetime import UTC, datetime

from ac_platform.lead_desk.capture_guard_nudges import slot, words


def test_daily_slot_is_19_india_time_not_server_timezone():
    assert slot(datetime(2026, 10, 29, 13, 29, 59, tzinfo=UTC)) is None
    due = slot(datetime(2026, 10, 29, 13, 30, tzinfo=UTC))
    assert due is not None and due.hour == 19
    assert slot(datetime(2026, 10, 29, 18, 29, tzinfo=UTC)) == due
    assert slot(datetime(2026, 10, 29, 18, 30, tzinfo=UTC)) is None


def test_nudge_has_a_count_and_one_plain_fix():
    assert words(1)[0] == "1 call today has no recording: fix"
    assert words(3)[0] == "3 calls today have no recording: fix"
