"""The test world (owner, 13 Nov 2026: "a proper organisation, proper sales, a coherent story…
Calling durations, work hours followed"): three fictional companies, days that follow on from
each other, calls inside work hours that never overlap, and some calls that aren't sales
(docs/qa/test-world/WORLD.md)."""

import importlib.util
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str):  # type: ignore[no-untyped-def]
    key = f"call_testing_{name}"
    found = importlib.util.spec_from_file_location(
        key, ROOT / "scripts/call_testing" / f"{name}.py"
    )
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[key] = module
    found.loader.exec_module(module)
    return module


world = _load("world")
day_cli = _load("day")

MONDAY = date(2026, 11, 16)


def _week():  # type: ignore[no-untyped-def]
    leads: list = []
    days = []
    for offset in range(8):
        day = MONDAY + timedelta(days=offset)
        calls, arrived = world.plan_day(leads, day)
        days.append((day, calls, arrived))
    return leads, days


def test_three_companies_all_marked_test_with_fictional_people() -> None:
    assert len(world.AGENCIES) == 3
    for agency in world.AGENCIES:
        assert agency.name.startswith("TEST · ")
        assert 3 <= len(agency.sellers) <= 4 and agency.owner
        assert all(s.weakness and s.strength for s in agency.sellers)
        assert any(not p.sales for p in (*world.NOT_SALES, *agency.personas))
    text = repr(world.AGENCIES)
    for real in ("Authority Closers", "Kulkarni", "Dipak", "Swamini"):
        assert real not in text


def test_lead_numbers_ring_nobody() -> None:
    leads, _ = _week()
    assert leads
    assert all(re.fullmatch(r"\+91 00000 \d{5}", lead.phone) for lead in leads)
    assert len({lead.key for lead in leads}) == len(leads)


def test_the_same_day_and_state_give_the_same_plan() -> None:
    first, _ = world.plan_day([], MONDAY)
    second, _ = world.plan_day([], MONDAY)
    assert [vars(c) for c in first] == [vars(c) for c in second]


def test_calls_stay_inside_work_hours_outside_lunch_and_never_overlap() -> None:
    _, days = _week()
    for day, calls, _ in days:
        for agency in world.AGENCIES:
            own = [c for c in calls if c.agency == agency.key]
            if day.weekday() not in agency.days:
                assert not own
                continue
            for seller in {c.seller for c in own}:
                mine = sorted((c for c in own if c.seller == seller), key=lambda c: c.start)
                previous_end = None
                for call in mine:
                    start = datetime.fromisoformat(call.start)
                    end = start + timedelta(seconds=call.seconds)
                    assert agency.start <= start.time() and end.time() <= agency.end
                    assert not (agency.lunch[0] <= start.time() < agency.lunch[1])
                    if previous_end:
                        assert start >= previous_end
                    previous_end = end


def test_stories_follow_on_from_one_day_to_the_next() -> None:
    leads, days = _week()
    moved = [lead for lead in leads if len(lead.history) >= 2]
    assert moved, "some leads had a second call later in the week"
    for lead in moved:
        steps = world.ARCS[lead.arc]
        kinds = [h["kind"] for h in lead.history]
        assert kinds == [kind for kind, _ in steps[: len(kinds)]]
        assert [h["day"] for h in lead.history] == sorted(h["day"] for h in lead.history)
    sunday = next(calls for day, calls, _ in days if day.weekday() == 6)
    assert sunday == []


def test_some_calls_arent_sales_and_few_are_analysed() -> None:
    _, days = _week()
    for day, calls, _ in days:
        if day.weekday() == 6:
            continue
        connected = [c for c in calls if c.connected]
        not_sales = [c for c in connected if not c.sales]
        assert not_sales and len(not_sales) <= 0.35 * len(connected)
        for agency in world.AGENCIES:
            analysed = [c for c in calls if c.agency == agency.key and c.analyse]
            assert 1 <= len(analysed) <= 3
            assert sum(1 for c in analysed if not c.sales) <= 1
            assert all(c.connected and c.seconds >= 20 for c in analysed)
    purposes = {c.purpose for _, calls, _ in days for c in calls if not c.sales}
    assert {"personal", "internal"} <= purposes


def test_state_round_trips_and_the_day_page_renders(tmp_path: Path) -> None:
    leads, _ = _week()
    again = world.load(world.dump(leads))
    assert [vars(lead) for lead in again] == [vars(lead) for lead in leads]
    assert (
        day_cli.main(["plan", "--day", MONDAY.isoformat(), "--home", str(tmp_path), "--save"]) == 0
    )
    page = (tmp_path / f"{MONDAY}.html").read_text("utf-8")
    assert "TEST · Sahyadri Homes" in page and "Monday 16 November 2026" in page
    assert (tmp_path / "state.json").exists()
