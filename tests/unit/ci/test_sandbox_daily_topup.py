"""The dev sandbox's daily top-up (owner via the orchestrator, 14 Nov 2026: "a nice sales
inbox… live data… so my dev can continuously continue with the new numbers"): each day is
planned from its date alone, calls stay inside the day's hours and outside lunch, the cold
seller dials most, Sunday is short, enquiries are fictional, and the app's reason keys are the
30-day build's (scripts/data-changes/sandbox-daily-topup.py)."""

import importlib.util
import json
import random
import re
import sys
from datetime import date, time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, file: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / "scripts/data-changes" / file)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


topup = _load("sandbox_daily_topup", "sandbox-daily-topup.py")
build = _load("sandbox_organisations_for_topup", "sandbox-organisations.py")

BASE = UUID("8d3c1f0e-7a4b-4c2d-9e1f-0a1b2c3d4e5f")
SATURDAY, SUNDAY = date(2026, 11, 14), date(2026, 11, 15)
COLD = topup.Seller(uuid4(), "Aditya Joshi", True, False)
WARM = topup.Seller(uuid4(), "Priya Deshmukh", False, False)


def _local(moment):  # type: ignore[no-untyped-def]
    return moment.astimezone(topup.IST).time()


def test_a_day_is_planned_from_its_date_alone() -> None:
    first = topup.seller_slots(BASE, SATURDAY, 0, WARM, works=True, sunday=False)
    again = topup.seller_slots(BASE, SATURDAY, 0, WARM, works=True, sunday=False)
    assert first == again and first
    assert topup.seller_slots(BASE, date(2026, 11, 13), 0, WARM, works=True, sunday=False) != first
    assert topup.arrivals(BASE, SATURDAY, sunday=False) == topup.arrivals(
        BASE, SATURDAY, sunday=False
    )


def test_calls_sit_inside_the_day_outside_lunch_in_order() -> None:
    for seller in (COLD, WARM):
        slots = topup.seller_slots(BASE, SATURDAY, 0, seller, works=True, sunday=False)
        starts = [slot.start for slot in slots]
        assert starts == sorted(starts) and len(set(starts)) == len(starts)
        for slot in slots:
            clock = _local(slot.start)
            assert topup.DAY_START <= clock < topup.DAY_END
            assert not (topup.LUNCH[0] <= clock < topup.LUNCH[1])
        assert [slot.number for slot in slots] == list(range(len(slots)))


def test_the_cold_seller_dials_most_and_sunday_is_short() -> None:
    cold = topup.seller_slots(BASE, SATURDAY, 0, COLD, works=True, sunday=False)
    warm = topup.seller_slots(BASE, SATURDAY, 1, WARM, works=True, sunday=False)
    assert len(cold) > len(warm) >= 8
    sunday = topup.seller_slots(BASE, SUNDAY, 1, WARM, works=True, sunday=True)
    assert 0 < len(sunday) < len(warm)
    assert all(time(11, 0) <= _local(s.start) < time(17, 0) for s in sunday)
    assert topup.seller_slots(BASE, SUNDAY, 1, WARM, works=False, sunday=True) == []
    assert len(topup.arrivals(BASE, SUNDAY, sunday=True)) <= 4


def test_enquiries_are_fictional() -> None:
    for item in topup.arrivals(BASE, SATURDAY, sunday=False):
        assert re.fullmatch(r"\+91 00000 1[89]\d{3}", item.record["phone"])
        assert item.source[0] in {"meta", "webhook"}
        assert item.record["interest"] in topup.INTERESTS


def test_outcomes_follow_the_30_day_build() -> None:
    rng = random.Random(1)  # noqa: S311
    assert topup.outcome_for("new", 0.99, cold=False, rng=rng) == (False, "nc")
    seen = {topup.outcome_for("int", 0.0, cold=False, rng=rng)[1] for _ in range(300)}
    assert seen <= {"meet", "again", "lost", "later", "won"} and "again" in seen
    for outcome in ("lost", "junk", "int", "open", "again", "meet", "won", "later"):
        assert topup.talk_seconds(rng, outcome) > 0
    assert dict(topup.NC_REASONS) == dict(build.NC_REASONS)
    assert dict(topup.FIRST_LOST) == dict(build.FIRST_LOST)
    assert dict(topup.LATER_LOST) == dict(build.LATER_LOST)
    assert dict(topup.JUNK_REASONS) == dict(build.JUNK_REASONS)
    assert dict(topup.OPEN_REASONS) == dict(build.OPEN_REASONS)
    assert topup.MEANINGS == build.MEANINGS and topup.OPTIONAL_MEANINGS == build.OPTIONAL_MEANINGS


def test_follow_ups_land_on_working_days_inside_hours() -> None:
    rng = random.Random(7)  # noqa: S311
    after = topup.at(SATURDAY, time(18, 0))
    for _ in range(50):
        slot = topup.next_slot(rng, after, days=(1, 3), work_days=(0, 1, 2, 3, 4, 5))
        local = slot.astimezone(topup.IST)
        assert local.weekday() != 6 and time(11, 0) <= local.time() <= time(17, 30)


def test_the_input_is_checked(tmp_path: Path) -> None:
    good = {
        "command_id": str(uuid4()),
        "approver_email": "a@example.com",
        "issue": "x",
        "tenant_id": str(uuid4()),
    }
    path = tmp_path / "in.json"
    path.write_text(json.dumps(good), "utf-8")
    assert topup.spec_of(str(path))["include_sunday"] is False
    path.write_text(json.dumps({**good, "tenant_id": ""}), "utf-8")
    with pytest.raises(SystemExit) as refused:
        topup.spec_of(str(path))
    assert json.loads(str(refused.value))["refused"] == "missing_input"


def test_several_days_and_exclusions_are_checked(tmp_path: Path) -> None:
    """Owner, 19 Nov 2026 ("show the app to investors"): a TEST workspace plays the days it
    missed, oldest first, in one transaction, leaving out members who are not its sellers."""
    good = {
        "command_id": str(uuid4()),
        "approver_email": "a@example.com",
        "issue": "x",
        "tenant_id": str(uuid4()),
        "days": ["2026-11-16", "2026-11-17"],
        "exclude_person_ids": [str(uuid4())],
    }
    path = tmp_path / "in.json"
    path.write_text(json.dumps(good), "utf-8")
    assert topup.spec_of(str(path))["days"] == ["2026-11-16", "2026-11-17"]
    for bad in (
        {**good, "days": ["2026-11-17", "2026-11-16"]},
        {**good, "days": ["2026-11-16", "2026-11-16"]},
        {**good, "day": "2026-11-16"},
    ):
        path.write_text(json.dumps(bad), "utf-8")
        with pytest.raises(SystemExit) as refused:
            topup.spec_of(str(path))
        assert json.loads(str(refused.value))["refused"] == (
            "days_must_be_distinct_oldest_first_without_day"
        )
    path.write_text(json.dumps({**good, "exclude_person_ids": ["nope"]}), "utf-8")
    with pytest.raises(ValueError):
        topup.spec_of(str(path))
    assert topup.TEST_PREFIX == "TEST · "
