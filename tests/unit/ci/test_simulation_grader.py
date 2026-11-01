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


def test_the_apps_speaker_map_names_each_speaker_by_id() -> None:
    answer = {
        "schema": "ac.sales-xray.speaker-map/1",
        "speakers": [
            {"speaker_id": "speaker_0", "role": "you", "name_evidence": [{"segment_id": "s1"}]},
            {"speaker_id": "speaker_1", "role": "prospect"},
        ],
    }
    roles = grade.speaker_roles(answer)
    assert roles == {"speaker_0": "you", "speaker_1": "prospect"}
    timeline = [{"who": "S", "start": 0, "end": 2}, {"who": "P", "start": 2, "end": 4}]
    segments = [
        {"start": 0, "end": 2, "speaker": "speaker_1", "text": "a b"},
        {"start": 2, "end": 4, "speaker": "speaker_0", "text": "c d"},
    ]
    swapped = grade.grade_roles(timeline, [["S", "a b"], ["P", "c d"]], segments, roles)
    assert swapped == {"accuracy": 0.0, "labels": 2, "mapped": True}


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
            "pipelines": {"fast": {"state": "done"}, "deep": {"state": "not_started"}},
            "objects": [
                {"type_key": "person.name", "display": "Anil"},
                {"type_key": "money.budget", "display": "₹2 lakh"},
            ],
        },
        "lead": {"lead": {"stage": "interested"}},
        "phone_log": {"logged": 0, "already": 1},
        "attached": True,
    }
    graded = grade.grade(truth, run)
    assert graded["result"] == "pass"
    assert graded["wer"] == 0.0 and graded["latency_s"] == 150
    assert graded["landing"] == {"one_call_on_lead": True, "attached": True}
    blocked = grade.grade(truth, {"error": "GET /v1/lead-desk/leads -> 422 'stage'"})
    assert blocked["result"] == "blocked"
    refused = grade.grade(truth, {"error": "PUT /v1/x/source -> 403 'longer than 60 minutes'"})
    assert refused["result"] == "fail"
    assert "| S99 t | phone | 120 s | **pass** |" in grade.markdown([graded])
    assert "refused: 403 'longer than 60 minutes'" in grade.markdown([refused])
    # Where the engine never ran (dev's spend guard), an unmoved stage is not a miss.
    run["call_data"] = {"pipelines": {"fast": {"state": "none"}}}
    run["lead_before"] = {"stage": "new"}
    run["lead"] = {"lead": {"stage": "new"}, "stage_suggestion": None}
    run["report"] = {"report": {"content": {"summary": "Anil said his budget is ₹2 lakh."}}}
    guarded = grade.grade(truth, run)
    assert guarded["stage"]["guarded"] and guarded["stage"]["ok"] is None
    assert guarded["report_facts"]["recall"] == 1.0 and guarded["result"] == "pass"


def test_the_report_is_read_in_its_own_words_never_its_quotes() -> None:
    envelope = {
        "report": {
            "content": {
                "summary": "You booked a demo with Anil of Deshmukh Auto for Tuesday at 4 PM.",
                "objection_analysis": [
                    {
                        "explanation": "Budget of 2 to 2.5 lakh fits; you quoted ₹45,000.",
                        "evidence": [{"segment_id": "s9", "quote": "We are in Nashik."}],
                    }
                ],
                "overview": {"version": "dipak-14-point-v1"},
            }
        }
    }
    text = grade.report_text(envelope)
    assert "Deshmukh Auto" in text and "Nashik" not in text and "dipak-14" not in text
    key = {
        "person.name": ["anil"],
        "company.location": ["nashik"],
        "money.budget": {"amount": 250000, "low": 200000, "high": 250000},
        "outcome.call_outcome": "meeting_scheduled",
        "forbid": ["money.price_quoted"],
    }
    facts = grade.grade_report_facts(key, text)
    assert (facts["expected"], facts["hit"]) == (4, 3)
    money = grade.money_precision(
        text, "two lakh, maybe two and a half lakh. it is 45,000 per seat"
    )
    assert money["precision"] == 1.0
    assert grade.money_precision("a ₹9,00,000 deal", "45,000")["unheard"] == [900000]
    assert grade.money_precision("before Diwali 2026", "45,000")["stated"] == 0
    heard = grade.grade_report_facts({"person.name": ["meenal"]}, "When Minal asked for a discount")
    assert heard["detail"][0]["ok"] and heard["detail"][0]["heard_as"] == "minal"
    assert grade.grade_report_facts({"person.name": ["anil"]}, "Sunil asked")["hit"] == 0
    assert grade.follow_up_in_text({"weekday": "tuesday", "hour": 16}, text) is True
    assert grade.follow_up_in_text({"weekday": "tuesday", "hour": 11}, text) is False
    assert grade.follow_up_in_text({"weekday": "friday", "hour": 17}, "a call Friday at five")
    assert grade.engine_ran({"pipelines": {"fast": {"state": "none"}}}) is False
    assert grade.engine_ran({"pipelines": {"fast": {"state": "done"}}}) is True


def test_a_call_over_two_hours_passes_on_a_clear_refusal_before_spend() -> None:
    truth = {
        "id": "S10X",
        "title": "Over the limit",
        "language": "en",
        "path": "phone",
        "duration_seconds": 7579,
        "turns": [["S", "hello"]],
        "key": {},
        "expect": {"report": "either", "over_limit": True},
    }
    refused = grade.grade(truth, {"error": "PUT /v1/x/source -> 413 'Calls up to 2 hours.'"})
    assert refused["result"] == "pass"
    dropped = grade.grade(truth, {"error": "network: timed out"})
    assert dropped["result"] == "blocked"
    assert "S10X" in grade.markdown([refused, dropped])


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
    assert words["S09"] >= 45 * 140 and words["S10"] >= 112 * 140


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
    over_limit = inject.call_start({"id": "S10X", "duration_seconds": 60}, hours, sunday_morning)
    assert over_limit == start + inject.timedelta(minutes=14 * 9)


def test_one_sellers_calls_run_back_to_back(tmp_path: Path) -> None:
    for scenario_id, seconds in (("S01", 120), ("S02", 600), ("S10X", 60)):
        (tmp_path / scenario_id).mkdir()
        (tmp_path / scenario_id / "truth.json").write_text(
            f'{{"id": "{scenario_id}", "duration_seconds": {seconds}}}'
        )
    offsets = [inject.schedule_offset(tmp_path / s / "truth.json") for s in ("S01", "S02", "S10X")]
    assert offsets == [0, 2 + 3, 2 + 3 + 10 + 3]
    assert inject.schedule_offset(tmp_path / "S99" / "truth.json") is None
