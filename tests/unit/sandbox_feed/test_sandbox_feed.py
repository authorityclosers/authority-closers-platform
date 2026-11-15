"""The dev sandbox feed's plan (owner, 15 Nov 2026: "data keeps coming live every day in
proper working hours"): seller days sit inside 09:30-19:30 with lunch, one seller a day
doesn't work and never the star, each day's enquiries are the same on every tick, the
support calls fall in working hours, the drawn avatars are distinct 256 px pictures, and the
timer runs inside the capped ac-strikes.slice as the dev-live API's user."""

import importlib.util
import io
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
IST = ZoneInfo("Asia/Kolkata")


def _load(name: str, path: Path):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, path)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


feed = _load("sandbox_feed_unit", ROOT / "scripts/sandbox_feed/feed.py")
avatars = _load("sandbox_feed_avatars_unit", ROOT / "scripts/sandbox_feed/avatars.py")
reports = _load("sandbox_feed_reports_unit", ROOT / "scripts/sandbox_feed/reports.py")
UNITS = ROOT / "infra/application/development/sandbox-feed"
DAYS = [date(2026, 11, 2) + timedelta(days=n) for n in range(28)]


def test_each_day_one_seller_is_idle_in_turn_and_never_the_star() -> None:
    idle = Counter(feed.idle_on(day) for day in DAYS)
    assert feed.STAR not in idle
    assert set(idle) == set(feed.IDLE_TURN)
    assert max(idle.values()) - min(idle.values()) <= 1
    for day in DAYS:
        assert feed.work_day(feed.PROFILES[feed.idle_on(day)], day) is None


def test_a_seller_day_sits_inside_working_hours_with_lunch() -> None:
    worked = 0
    for day in DAYS:
        for alias, seller in feed.PROFILES.items():
            shape = feed.work_day(seller, day)
            if shape is None:
                continue
            worked += 1
            start, end = shape.start.astimezone(IST), shape.end.astimezone(IST)
            assert start.time() >= feed.OPENS and end.time() <= feed.CLOSES
            assert start < end
            lunch = shape.lunch[0].astimezone(IST).time()
            assert time(13, 0) <= lunch <= time(14, 0)
            for begin, finish in shape.windows:
                assert shape.start <= begin < finish <= shape.end
            # The same day comes out the same on every tick.
            assert feed.work_day(seller, day) == shape, alias
    # Nearly everyone works nearly every day (one idle seller a day, the odd day off).
    assert worked >= len(DAYS) * (len(feed.PROFILES) - 1) * 0.9


def test_the_star_works_hardest_and_farah_leaves_follow_ups() -> None:
    star = feed.PROFILES[feed.STAR]
    others = [p for alias, p in feed.PROFILES.items() if alias != feed.STAR]
    assert all(star.think < p.think for p in others)
    assert all(star.connect > p.connect for p in others)
    # The star also works the most Cold leads a day, so she leads the month's calls.
    assert all(star.cold_cap > p.cold_cap for p in others)
    assert feed.PROFILES["ac.farah"].skip == max(p.skip for p in feed.PROFILES.values())
    assert feed.PROFILES["ac.sneha"].sides == "inbound"
    assert feed.PROFILES["ac.aditya"].sides == "cold"
    # A long name for the screens to cut.
    first, last, alias = feed.NEWCOMER
    assert len(f"{first} {last}") >= 20 and alias in feed.PROFILES


def test_the_night_batch_runs_from_midnight_without_lunch() -> None:
    day = date(2026, 11, 15)
    until = datetime(2026, 11, 14, 20, 40, tzinfo=UTC)
    shape = feed.night_day(feed.PROFILES[feed.STAR], day, until)
    assert shape is not None
    assert shape.start.astimezone(IST).date() == day
    assert shape.start.astimezone(IST).time() < time(0, 15)
    assert shape.windows == ((shape.start, shape.end),)
    assert feed.night_day(feed.PROFILES[feed.idle_on(day)], day, until) is None


def test_a_day_of_enquiries_is_fixed_and_realistic() -> None:
    for day in DAYS:
        plan = feed.arrival_plan(day)
        assert plan == feed.arrival_plan(day)
        low, high = feed.ARRIVALS
        assert low <= len(plan) <= high
        assert [number for number, *_ in plan] == list(range(len(plan)))
        assert all(moment.astimezone(IST).date() == day for _, moment, _, _ in plan)
        moments = [moment for _, moment, _, _ in plan]
        assert moments == sorted(moments)
        for moment in feed.support_plan(day):
            assert time(10, 0) <= moment.astimezone(IST).time() < time(19, 0)


def test_who_is_a_seller_and_what_a_lead_is() -> None:
    assert feed.alias_of("admin+ac.priya@authorityclosers.com") == "ac.priya"
    assert feed.alias_of("admin@authorityclosers.com") is None
    assert feed.alias_of(None) is None
    steps = {"new": "new", "open_leads": "open", "interested": "int"}
    assert feed.phase_of("interested", "interested", steps) == "int"
    assert feed.phase_of("not_connected", None, steps) == "nc"
    assert feed.phase_of("follow_up", "unknown_step", steps) == "open"
    assert feed.phase_of("odd", None, steps) is None
    # Only AC's fictional +91 00000 numbers are the sandbox's own.
    assert feed.fictional_number("+910000010007") == 7
    assert feed.fictional_number("+91 00000 10250") == 250
    assert feed.fictional_number("+919876543210") is None
    assert feed.fictional_number(None) is None


def test_a_window_touches_each_india_day_once() -> None:
    cursor = datetime(2026, 11, 14, 14, 0, tzinfo=UTC)  # 19:30 IST
    until = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)  # 09:30 IST next day
    assert feed.windows(cursor, until) == [date(2026, 11, 14), date(2026, 11, 15)]
    assert feed.windows(until, until) == [date(2026, 11, 15)]


def test_the_avatars_are_distinct_square_drawings() -> None:
    from PIL import Image

    seen = set()
    for alias in feed.PROFILES:
        data = avatars.portrait(alias)
        seen.add(data)
        with Image.open(io.BytesIO(data)) as picture:
            assert picture.format == "PNG"
            assert picture.size == (avatars.SIZE, avatars.SIZE)
    assert len(seen) == len(feed.PROFILES)
    assert avatars.portrait("someone.else")  # anyone else gets the default look


def test_the_timer_runs_capped_as_the_api_user_in_working_hours() -> None:
    service = (UNITS / "ac-dev-sandbox-feed.service").read_text(encoding="utf-8")
    timer = (UNITS / "ac-dev-sandbox-feed.timer").read_text(encoding="utf-8")
    runner = (UNITS / "ac-dev-sandbox-feed").read_text(encoding="utf-8")
    for text in (service, runner):
        assert "ac-strikes.slice" in text
        assert "10001" in text
        assert "/etc/authority-closers/development/api-live.env" in text
        assert "IOSchedulingClass=idle" in text
    assert "feed.py tick --apply" in service
    assert "SyslogIdentifier=ac-dev-sandbox-feed" in service
    # 04:00-14:48 UTC is 09:30-20:18 India time: the working day plus the 20-minute lag.
    assert "OnCalendar=*-*-* 04..14:00/12:00 UTC" in timer
    assert "RandomizedDelaySec=" in timer
    installer = (UNITS / "install-sandbox-feed.sh").read_text(encoding="utf-8")
    assert 'AC_ENVIRONMENT="development"' in installer
    for name in ("feed.py", "avatars.py", "sandbox-organisations.py"):
        assert name in installer


def test_reports_reuse_authored_ones_a_few_a_day_and_charge_nothing() -> None:
    """Reports copy the AUT-1676 loader's authored, AI-free reports (orchestrator, 15 Nov 2026:
    at most 5 new paid analyses a day; this makes none)."""
    loader = (ROOT / "scripts/data-changes/load-sales-xray-sandbox-hosted.py").read_text("utf-8")
    assert f'POLICY = "{reports.SOURCE_POLICY}"' in loader
    assert reports.PER_TICK <= reports.PER_DAY <= 6
    low, high = reports.SECONDS
    assert 60 <= low < high <= 600
    assert reports.CAPTURE == "android_dialer_pickup"
    text = (ROOT / "scripts/sandbox_feed/reports.py").read_text("utf-8")
    assert 'kind="no_work_performed"' in text and "charged_seconds=0" in text
    assert "ConversationReports._validated(draft, recording)" in text
    # One id per call and kind, the same on a replay, never shared between kinds.
    call = reports.NAMESPACE
    kinds = ("recording", "run", "submission", "usage", "lease", "job", "report", "attach")
    ids = {reports._id(kind, call) for kind in kinds}
    assert len(ids) == len(kinds)
    assert reports._id("report", call) == reports._id("report", call)
    # A report tells the same story as the lead: its outcome follows the stage after the call.
    assert reports.outcome_of("won") == "won"
    assert reports.outcome_of("lost") == reports.outcome_of("junk") == "lost"
    for stage in ("new", "not_connected", "follow_up", "interested"):
        assert reports.outcome_of(stage) == "follow_up"
