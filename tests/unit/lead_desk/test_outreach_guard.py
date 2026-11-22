"""The cadence guard's maths (v1.95, lead_desk/outreach.py; spec §4.1 and §8), pure, with fixed
clocks: the day in the team's time zone, the rolling 7 days, the reply window, the cool-off,
sending hours, channel modes, STOP, the lead's state, overrides, what counts, and the words."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest

from ac_platform.lead_desk import outreach
from ac_platform.lead_desk.outreach import Fact, Facts, Rules, Window

ALWAYS = Window(tuple(range(7)), time(0), time(23, 59))
WORK = Window(tuple(range(6)), time(10), time(20))  # Mon-Sat 10:00-20:00
RULES = Rules()
# Tuesday 24 Nov 2026, 12:00 IST (06:30 UTC).
NOON = datetime(2026, 11, 24, 6, 30, tzinfo=UTC)


def touch(
    at: datetime, channel: str = "whatsapp", counted: bool = True, status: str = "sent"
) -> Fact:
    return Fact(sent_at=at, channel=channel, counted=counted, status=status)


def check(
    facts: Facts,
    now: datetime = NOON,
    *,
    channel: str = "whatsapp",
    sender: outreach.Sender = "person",
    rules: Rules = RULES,
    window: Window = ALWAYS,
) -> outreach.OutreachGuard:
    return outreach.guard(
        facts, channel=channel, sender=sender, rules=rules, window=window, now=now
    )


def codes(result: outreach.OutreachGuard) -> set[str]:
    return {reason.code for reason in result.reasons}


def test_a_new_lead_is_ok_and_not_contacted_yet() -> None:
    result = check(Facts())
    assert (result.verdict, result.words, result.counts.week) == ("ok", "Not contacted yet", 0)
    assert result.next_ok_at is None and not result.opted_out


def test_the_day_is_the_teams_day_in_india_not_utc() -> None:
    # 23:50 IST on Tuesday is 18:20 UTC; 00:10 IST on Wednesday is 18:40 UTC: the same UTC day.
    late = datetime(2026, 11, 24, 18, 20, tzinfo=UTC)
    facts = Facts(touches=(touch(late),))
    same_day = check(facts, now=datetime(2026, 11, 24, 18, 25, tzinfo=UTC))
    assert same_day.counts.today == 1
    assert same_day.verdict == "warn" and "day_cap" in codes(same_day)
    next_day = check(facts, now=datetime(2026, 11, 24, 18, 40, tzinfo=UTC))
    assert next_day.counts.today == 0 and "day_cap" not in codes(next_day)
    assert next_day.verdict == "ok"


def test_the_day_limit_waits_for_tomorrows_sending_hours() -> None:
    facts = Facts(touches=(touch(NOON - timedelta(hours=1)),))
    result = check(facts, window=WORK, sender="automation")
    assert result.verdict == "block"
    # Wednesday 25 Nov, 10:00 IST.
    assert result.next_ok_at == datetime(2026, 11, 25, 4, 30, tzinfo=UTC)


def test_the_week_is_a_rolling_seven_days() -> None:
    inside = NOON - timedelta(days=6, hours=23)
    outside = NOON - timedelta(days=7, minutes=1)
    two_more = (NOON - timedelta(days=3), NOON - timedelta(days=2))
    # (no cool-off here: three unanswered would also rest the lead)
    counted = check(
        Facts(touches=(touch(inside), *map(touch, two_more))), rules=Rules(rest_after=0)
    )
    assert counted.counts.week == 3 and "week_cap" in codes(counted)
    # It frees when the oldest of those three is 7 days old.
    assert counted.next_ok_at == inside + timedelta(days=7)
    dropped = check(Facts(touches=(touch(outside), *map(touch, two_more))))
    assert dropped.counts.week == 2 and "week_cap" not in codes(dropped)
    assert dropped.words == "Last touched 2 days ago · 2 touches this week"


def test_a_reply_in_the_last_24_hours_is_never_limited_or_counted() -> None:
    busy = tuple(touch(NOON - timedelta(hours=h)) for h in (1, 30, 50))
    within = check(Facts(touches=busy, last_inbound={"whatsapp": NOON - timedelta(hours=23)}))
    assert within.verdict == "ok" and within.in_reply_window
    assert not outreach.would_count(within)
    after = check(Facts(touches=busy, last_inbound={"whatsapp": NOON - timedelta(hours=25)}))
    assert after.verdict == "warn" and not after.in_reply_window
    assert outreach.would_count(after)
    # A reply on another channel opens no window here.
    other = check(Facts(touches=busy, last_inbound={"email": NOON - timedelta(hours=1)}))
    assert not other.in_reply_window


def test_three_unanswered_rest_fourteen_days_and_a_reply_resets_the_streak() -> None:
    three = tuple(touch(NOON - timedelta(days=d)) for d in (20, 15, 10))
    rested = check(Facts(touches=three), sender="automation", rules=Rules(per_week=30))
    assert rested.counts.unanswered == 3 and "rest" in codes(rested)
    assert rested.verdict == "block"
    assert rested.next_ok_at == NOON - timedelta(days=10) + timedelta(days=14)
    assert "rests until Sat 28 Nov" in next(r.words for r in rested.reasons if r.code == "rest")
    answered = check(
        Facts(touches=three, last_inbound={"whatsapp": NOON - timedelta(days=12)}),
        rules=Rules(per_week=30),
    )
    assert answered.counts.unanswered == 1 and "rest" not in codes(answered)
    over = check(Facts(touches=tuple(touch(NOON - timedelta(days=d)) for d in (40, 35, 30))))
    assert "rest" not in codes(over)  # the 14 days are over
    off = check(Facts(touches=three), rules=Rules(rest_after=0, per_week=30))
    assert "rest" not in codes(off)


def test_sending_hours_warn_people_hold_automations_and_sunday_is_off() -> None:
    sunday = datetime(2026, 11, 22, 6, 30, tzinfo=UTC)  # Sunday 12:00 IST
    person = check(Facts(), now=sunday, window=WORK)
    engine = check(Facts(), now=sunday, window=WORK, sender="automation")
    assert (person.verdict, engine.verdict) == ("warn", "block")
    assert engine.quiet_until == datetime(2026, 11, 23, 4, 30, tzinfo=UTC)  # Monday 10:00 IST
    night = check(Facts(), now=datetime(2026, 11, 24, 16, 0, tzinfo=UTC), window=WORK)
    assert "quiet" in codes(night)
    assert check(Facts(), window=WORK).verdict == "ok"  # Tuesday noon
    # Calls are shown only: no sending hours for them.
    assert check(Facts(), now=sunday, window=WORK, channel="call").verdict == "ok"


@pytest.mark.parametrize(
    ("mode", "verdict", "counts"),
    [("off", "ok", False), ("show", "ok", True), ("warn", "warn", True), ("block", "block", True)],
)
def test_each_channel_mode(mode: str, verdict: str, counts: bool) -> None:
    rules = Rules(modes={**outreach.DEFAULT_MODES, "sms": (mode, mode)})
    today = Facts(touches=(touch(NOON - timedelta(hours=1), channel="sms"),))
    result = check(today, channel="sms", rules=rules)
    assert result.verdict == verdict
    assert outreach.would_count(result) is counts
    if mode == "show":
        assert {r.level for r in result.reasons} == {"show"} and "day_cap" in codes(result)


def test_whatsapp_splits_people_and_automations() -> None:
    today = Facts(touches=(touch(NOON - timedelta(hours=1)),))
    assert check(today, sender="person").verdict == "warn"
    assert check(today, sender="automation").verdict == "block"


def test_a_stop_blocks_its_channel_only_and_nothing_overrides_it() -> None:
    said = Facts(opted_out=frozenset({"whatsapp"}), override_id=uuid4())
    result = check(said)
    assert (result.verdict, result.opted_out, result.override_id) == ("block", True, None)
    assert result.next_ok_at is None and not result.override.possible
    email = check(said, channel="email")
    assert email.verdict == "ok"
    assert [r.words for r in email.reasons] == ["Said stop on WhatsApp"]


def test_bin_and_test_data_block_archived_and_history_warn() -> None:
    assert check(Facts(state="bin")).verdict == "block"
    assert check(Facts(state="test"), sender="automation").verdict == "block"
    # Sandbox practice leads are test data: a person in the app is told, never stopped.
    assert check(Facts(state="test")).verdict == "warn"
    assert check(Facts(state="archived")).verdict == "warn"
    assert check(Facts(state="history")).verdict == "warn"


def test_an_override_passes_a_limit_for_its_channel() -> None:
    override = uuid4()
    today = (touch(NOON - timedelta(hours=1)),)
    passed = check(Facts(touches=today, override_id=override), sender="automation")
    assert (passed.verdict, passed.override_id) == ("ok", override)
    # No limit, nothing to use it on.
    assert check(Facts(override_id=override)).override_id is None
    # The override facts are per channel (outreach.facts reads this channel's only).
    assert check(Facts(touches=today), sender="automation").verdict == "block"


def test_calls_are_shown_not_counted_unless_their_mode_warns() -> None:
    calls = tuple(touch(NOON - timedelta(hours=h), channel="call", counted=False) for h in (1, 2))
    shown = check(Facts(touches=calls), channel="call")
    assert shown.verdict == "ok" and not outreach.would_count(shown)
    assert shown.counts.calls_week == 2
    assert shown.words == "Touched today at 11:00 · 0 touches this week · 2 calls"
    warn = Rules(modes={**outreach.DEFAULT_MODES, "call": ("warn", "warn")})
    counted = touch(NOON - timedelta(hours=1), channel="call")
    assert outreach.would_count(check(Facts(), channel="call", rules=warn))
    assert check(Facts(touches=(counted,)), channel="call", rules=warn).verdict == "warn"


def test_failed_expired_and_lapsed_reservations_never_count() -> None:
    gone = (
        touch(NOON - timedelta(hours=1), status="failed"),
        touch(NOON - timedelta(hours=2), status="expired"),
    )
    assert check(Facts(touches=gone)).counts.today == 0
    held = (touch(NOON - timedelta(minutes=5), status="queued"),)
    result = check(Facts(touches=held), sender="automation")
    assert result.counts.today == 1 and result.verdict == "block"  # a live reservation holds
    assert result.last_touch_at is None  # but it is not a touch yet


def test_disabled_limits_only_count() -> None:
    today = Facts(touches=(touch(NOON - timedelta(hours=1)),), opted_out=frozenset({"sms"}))
    result = check(today, rules=Rules(enabled=False), sender="automation", window=WORK)
    assert result.verdict == "ok" and result.counts.today == 1
    assert check(today, channel="sms", rules=Rules(enabled=False)).verdict == "block"


def test_counter_words() -> None:
    now = NOON
    assert outreach.counter_words(None, 0, 0, now) == "Not contacted yet"
    assert (
        outreach.counter_words(now - timedelta(minutes=30), 1, 0, now)
        == "Touched today at 11:30 · 1 touch this week"
    )
    assert (
        outreach.counter_words(now - timedelta(days=1), 3, 1, now)
        == "Last touched yesterday · 3 touches this week · 1 call"
    )


def test_statuses_move_forward_only() -> None:
    at = NOON
    assert outreach.advance("sent", at, "delivered", at + timedelta(seconds=1))
    assert not outreach.advance("read", at, "delivered", at + timedelta(seconds=1))
    assert not outreach.advance("sent", at, "delivered", at - timedelta(seconds=1))  # older
    assert outreach.advance("delivered", at, "failed", at + timedelta(seconds=1))
    assert outreach.advance("failed", at, "delivered", at + timedelta(seconds=1))  # a retry
    assert not outreach.advance("failed", at, "sent", at + timedelta(seconds=1))
    assert not outreach.advance("expired", at, "sent", at + timedelta(seconds=1))


def test_rules_parse_with_defaults_and_bounds() -> None:
    assert outreach.parse_rules({}) == Rules()
    rules = outreach.parse_rules(
        {
            "outreach": {
                "per_day": 99,
                "per_week": 0,
                "modes": {"whatsapp": "block", "email": {"people": "off"}},
                "quiet": {"days": [0, 1], "start": "09:00", "end": "18:00"},
            }
        }
    )
    assert (rules.per_day, rules.per_week, rules.saved) == (10, 1, True)
    assert rules.modes["whatsapp"] == ("block", "block")
    assert rules.modes["email"] == ("off", "warn")
    assert rules.quiet == Window((0, 1), time(9), time(18))
    work = {"work_hours": {"days": [0, 1, 2], "start": "11:00", "end": "17:00"}}
    assert outreach.window_for(Rules(), work) == Window((0, 1, 2), time(11), time(17))
    assert outreach.window_for(Rules(), {}) == Window(tuple(range(6)), time(10), time(20))
