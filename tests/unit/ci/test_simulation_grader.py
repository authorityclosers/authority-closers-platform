"""The simulation lab's grader scores what the app made of a synthetic call fairly, and the
scenario library stays fictional and complete (owner, 1 Nov 2026: hardcore simulated
testing of reports and data extraction from calls; scripts/simulation/README.md)."""

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, file: str):  # type: ignore[no-untyped-def]
    found = importlib.util.spec_from_file_location(name, ROOT / "scripts/simulation" / file)
    assert found is not None and found.loader is not None
    module = importlib.util.module_from_spec(found)
    sys.modules[name] = module
    found.loader.exec_module(module)
    return module


grade = _load("simulation_grade", "grade.py")
scenarios = _load("simulation_scenarios", "scenarios.py")
inject = _load("simulation_inject", "inject.py")


def test_word_error_rate_counts_substitutions_insertions_and_deletions() -> None:
    assert grade.wer("Tuesday at four p.m.", "tuesday at four pm") == 0.0
    assert grade.wer("Tuesday at four p.m.", "tuesday at five") == pytest.approx(0.5)
    assert grade.wer("hello there", "hello there") == 0.0
    assert grade.wer("one two three four", "one three four five") == pytest.approx(0.5)
    assert grade.wer("hello", "") == 1.0


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Budget is about 2.5 lakh", 250000),
        ("₹2,50,000 all in", 250000),
        ("forty-five thousand rupees per seat", 45000),
        ("one lakh fifty-five thousand, two instalments", 155000),
        ("two and a half lakh", 250000),
        ("1.55 L", 155000),
        ("45k per person", 45000),
        ("seventy-five thousand in twelve EMIs", 75000),
    ],
)
def test_amounts_read_indian_money_in_words_and_figures(text: str, value: int) -> None:
    assert value in grade.amounts(text)


def test_amount_specs_accept_a_range_or_another_quoted_price() -> None:
    assert grade.amount_matches({"amount": 250000, "low": 200000, "high": 250000}, "2 to 2.5 lakh")
    assert grade.amount_matches({"amount": 180000, "also": [155000]}, "settled at 1.55 lakh")
    assert not grade.amount_matches({"amount": 300000}, "about 6 lakh for the year")
    assert grade.amount_matches({"amount": 300000}, "", {"amount": 300000})


def test_facts_give_recall_over_the_key_and_precision_over_extracted_objects() -> None:
    key = {
        "person.name": ["anil"],
        "money.budget": {"amount": 250000},
        "friction.objection": [["price", "expensive"], ["time"]],
        "company.team_size": {"number": 8},
        "outcome.call_outcome": "meeting_scheduled",
        "meeting": {"weekday": "tuesday"},
        "forbid": ["market.competitor"],
    }
    objects = [
        {"type_key": "person.name", "display": "Anil Deshmukh"},
        {"type_key": "money.budget", "display": "₹2.5 lakh"},
        {"type_key": "friction.objection", "display": "Too expensive for now"},
        {"type_key": "friction.objection", "display": "Wants a free trial"},
        {"type_key": "company.team_size", "value": {"count": 8}, "display": "8 salespeople"},
        {"type_key": "outcome.call_outcome", "value": "meeting_scheduled"},
        {"type_key": "market.competitor", "display": "Shop next door"},
    ]
    result = grade.grade_facts(key, objects)
    assert result["expected"] == 6
    assert result["hit"] == 5  # the "time" objection is missed
    assert result["recall"] == pytest.approx(5 / 6, abs=0.001)
    # 6 graded objects, 5 right; plus 1 forbidden competitor -> 5 / 7.
    assert result["precision"] == pytest.approx(5 / 7, abs=0.001)
    assert result["forbidden"] == 1


def test_objects_are_found_anywhere_in_an_api_answer_once() -> None:
    payload = {
        "groups": [
            {"items": [{"type_key": "money.budget", "display": "3 lakh"}]},
            {"items": [{"type_key": "money.budget", "display": "3 lakh"}]},
        ],
        "other": {"type": "not-a-fact"},
    }
    assert [o["type_key"] for o in grade.objects_from(payload)] == ["money.budget"]


def test_roles_line_segments_up_with_the_truth_timeline() -> None:
    timeline = [
        {"index": 0, "who": "S", "start": 0.5, "end": 4.0},
        {"index": 1, "who": "P", "start": 4.5, "end": 8.0},
        {"index": 2, "who": "S", "start": 8.4, "end": 12.0},
    ]
    turns = [["S", "hello there friend"], ["P", "yes tell me"], ["S", "we run a programme"]]
    segments = [
        {"start": 0.4, "end": 4.1, "speaker": "Seller", "text": "hello there friend"},
        {"start": 4.4, "end": 8.1, "speaker": "Customer", "text": "yes tell me"},
        {"start": 8.3, "end": 12.1, "speaker": "Customer", "text": "we run a programme"},
    ]
    result = grade.grade_roles(timeline, turns, segments, {})
    # 3 + 3 words right out of 3 + 3 + 4.
    assert result["accuracy"] == pytest.approx(0.6)
    assert result["mapped"] is True


def test_unnamed_speaker_labels_take_the_better_assignment() -> None:
    timeline = [{"who": "S", "start": 0, "end": 2}, {"who": "P", "start": 2, "end": 4}]
    turns = [["S", "a b"], ["P", "c d"]]
    segments = [
        {"start": 0, "end": 2, "speaker": "1", "text": "a b"},
        {"start": 2, "end": 4, "speaker": "0", "text": "c d"},
    ]
    assert grade.grade_roles(timeline, turns, segments, {})["accuracy"] == 1.0


def test_transcript_segments_are_read_from_ms_or_seconds() -> None:
    payload = {"segments": [{"speaker": "A", "start_ms": 1500, "end_ms": 3000, "text": "hi"}]}
    assert grade.segments_from(payload) == [
        {"start": 1.5, "end": 3.0, "speaker": "A", "text": "hi"}
    ]


@pytest.mark.parametrize(
    ("seconds", "report", "want"),
    [
        (16.0, False, False),
        (19.0, True, False),
        (45.0, True, None),
        (147.0, True, True),
        (147.0, "either", None),
    ],
)
def test_the_short_call_rule_sets_what_is_expected(
    seconds: float, report: object, want: object
) -> None:
    truth = {"duration_seconds": seconds, "expect": {"report": report}}
    assert grade.expected_report(truth)[0] is want


def test_follow_ups_are_checked_in_india_time() -> None:
    call = datetime(2026, 10, 31, 5, 20, tzinfo=UTC)  # Saturday 10:50 IST
    tuesday_4pm = datetime(2026, 11, 3, 10, 30, tzinfo=UTC)  # Tuesday 16:00 IST
    assert grade.due_check({"weekday": "tuesday", "hour": 16}, call, tuesday_4pm) is True
    assert grade.due_check({"weekday": "tuesday", "hour": 11}, call, tuesday_4pm) is False
    assert grade.due_check({"day_offset": 3}, call, tuesday_4pm) is True
    assert grade.due_check({"weekday": "tuesday"}, call, None) is False


def test_a_whole_scenario_grades_pass_and_blocked() -> None:
    truth = {
        "id": "S99",
        "title": "t",
        "language": "english",
        "path": "phone",
        "duration_seconds": 120.0,
        "turns": [["S", "hello anil"], ["P", "budget is two lakh"]],
        "timeline": [{"who": "S", "start": 0, "end": 2}, {"who": "P", "start": 2, "end": 5}],
        "key": {"person.name": ["anil"], "money.budget": {"amount": 200000}},
        "expect": {"report": True, "stage": "interested", "stage_ok": ["interested"]},
    }
    run = {
        "path": "phone",
        "submission_id": "x",
        "upload_accepted": "2026-11-01T00:00:00+00:00",
        "report_at": "2026-11-01T00:02:30+00:00",
        "progress": {"has_report": True},
        "transcript": {
            "segments": [
                {"speaker": "Seller", "start": 0, "end": 2, "text": "hello anil"},
                {"speaker": "Prospect", "start": 2, "end": 5, "text": "budget is two lakh"},
            ]
        },
        "call_data": {
            "objects": [
                {"type_key": "person.name", "display": "Anil"},
                {"type_key": "money.budget", "display": "₹2 lakh"},
            ]
        },
        "lead": {"lead": {"stage": "interested"}},
        "phone_log": {"logged": 0, "already": 1},
        "attached": True,
    }
    graded = grade.grade(truth, run)
    assert graded["result"] == "pass"
    assert graded["wer"] == 0.0 and graded["latency_s"] == 150
    assert graded["landing"] == {"one_call_on_lead": True, "attached": True}
    blocked = grade.grade(truth, {"error": "PUT -> 409 allowance"})
    assert blocked["result"] == "blocked"
    assert "| S99 t | phone | 120.0 s | **pass** |" in grade.markdown([graded])


def test_the_library_is_thirty_fictional_calls_covering_the_brief() -> None:
    library = scenarios.library()
    assert len(library) == 30
    for s in library:
        assert s["lead"]["phone"].startswith("+91 00000 ")
        assert s["tenant_id"] in inject.SANDBOX_TENANTS
        assert {who for who, _ in s["turns"]} <= {"S", "P", "I"}
        for type_key in s["key"]:
            assert type_key in {"meeting", "forbid"} or type_key.count(".") == 1
    covered = {c for s in library for c in s["covers"]}
    assert {
        "inbound",
        "cold_rejected",
        "heavy_objections",
        "negotiation",
        "meeting_booked",
        "callback",
        "wrong_number",
        "ivr_voicemail",
        "hangup_20s",
        "long_45min",
        "long_2h",
        "hinglish",
        "marathi_english",
        "hindi",
        "noisy_line",
        "one_side_silent",
        "crosstalk",
        "speakerphone_echo",
    } <= covered
    words = {s["id"]: scenarios.words(s) for s in library}
    assert words["S09"] >= 45 * 140 and words["S10"] >= 120 * 140


def test_the_fake_phone_ids_match_the_android_app() -> None:
    # Java: UUID.nameUUIDFromBytes("abc".getBytes(UTF_8)) == 90015098-3cd2-3fb0-9696-3f7d28e17f72
    assert inject.name_uuid("abc") == "90015098-3cd2-3fb0-9696-3f7d28e17f72"
    assert inject.secret_name("ac.priya") == "SANDBOX_LOGIN_AC_PRIYA"


def test_calls_outside_work_hours_move_into_the_last_working_day() -> None:
    hours = {"days": [0, 1, 2, 3, 4, 5], "start": "10:30", "end": "19:00", "inside": False}
    sunday_morning = datetime(2026, 10, 31, 22, 55, tzinfo=UTC)  # Sunday 04:25 IST
    start = inject.call_start({"id": "S01", "duration_seconds": 147}, hours, sunday_morning)
    assert start == datetime(2026, 10, 31, 5, 20, tzinfo=UTC)  # Saturday 10:50 IST
    long_call = inject.call_start({"id": "S30", "duration_seconds": 7200}, hours, sunday_morning)
    assert long_call + inject.timedelta(seconds=7200) <= datetime(2026, 10, 31, 13, 30, tzinfo=UTC)
