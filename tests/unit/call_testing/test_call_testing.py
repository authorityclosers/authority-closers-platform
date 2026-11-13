"""The release call check (owner, 13 Nov 2026: "After each new release on Play Store… really test
being called… see that the report is being generated"): the scenario library stays fictional and
complete, calls are stamped inside work hours without overlapping, every run's files are unique,
and the checker judges the pipeline and the sales-or-not detection fairly
(scripts/call_testing/README.md)."""

import hashlib
import importlib.util
import re
import sys
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

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


scenarios = _load("scenarios")
phone = _load("phone")
check = _load("check")
page = _load("page")
run = _load("run")

IST = phone.IST
HOURS = phone.WorkHours(days=(0, 1, 2, 3, 4, 5), start=time(10, 30), end=time(19, 0))


# ---- the library ------------------------------------------------------------------------------


def test_library_has_at_least_twelve_calls_with_sales_and_not_sales() -> None:
    calls = scenarios.library()
    assert len(calls) >= 12
    ids = [c["id"] for c in calls]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"R\d{2}", i) for i in ids)
    sales = [c for c in calls if c["expect"]["sales"]]
    not_sales = [c for c in calls if not c["expect"]["sales"]]
    assert len(sales) >= 6 and len(not_sales) >= 6
    covered = {tag for c in calls for tag in c["covers"]}
    for needed in (
        "wrong_number",
        "personal",
        "ivr",
        "internal",
        "support",
        "silence",
        "buyer",
        "owner",
    ):
        assert needed in covered, needed
    assert {c["language"] for c in calls} >= {"english", "hinglish", "marathi-english"}


def test_every_scenario_is_renderable_and_its_expectation_is_valid() -> None:
    for call in scenarios.library():
        expect = call["expect"]
        assert expect["outcome"] in scenarios.OUTCOMES
        assert isinstance(expect["sales"], bool)
        assert set(expect["purpose"]) <= set(scenarios.PURPOSES)
        assert (expect["purpose"] == ["sales"]) == expect["sales"]
        roles = {who for who, _ in call["turns"]}
        assert roles <= set(call["voices"]), call["id"]
        assert call["audio"]["format"] == "mp3"
        if expect["outcome"] == "report":
            # Comfortably past the server's one-minute short-call line.
            assert scenarios.words(call) >= 150, call["id"]


def test_the_library_stays_fictional() -> None:
    text = repr(scenarios.library())
    assert not re.search(r"\d{10}", text), "no phone numbers in the scripts"
    for real in ("Authority Closers", "Sales X-Ray", "Dipak", "Kulkarni", "Swamini"):
        assert real not in text


def test_the_smoke_set_has_reports_a_detection_probe_and_a_hold() -> None:
    smoke = scenarios.pick("smoke")
    outcomes = [c["expect"]["outcome"] for c in smoke]
    assert outcomes.count("report") >= 2
    assert any(not c["expect"]["sales"] and c["expect"]["outcome"] == "any" for c in smoke)
    assert "no_conversation" in outcomes
    assert [c["id"] for c in scenarios.pick("R10,R01")] == ["R01", "R10"]
    with pytest.raises(SystemExit):
        scenarios.pick("R99")


def test_library_hash_changes_only_with_the_library() -> None:
    assert scenarios.library_sha256() == scenarios.library_sha256()
    assert re.fullmatch(r"[0-9a-f]{64}", scenarios.library_sha256())


def test_expectations_follow_the_servers_short_call_rule() -> None:
    policy = (ROOT / "packages/python/ac_platform/call_ai/policy.py").read_text("utf-8")
    assert "SHORT_CALL_MS: Final = 60_000" in policy
    assert "NO_CONVERSATION_MS: Final = 20_000" in policy
    assert '"short_call": "ai_short_call"' in policy
    assert '"no_conversation": "ai_no_conversation"' in policy
    assert set(check.HOLDS) == {"ai_short_call", "ai_no_conversation"}


# ---- the phone side ---------------------------------------------------------------------------


def test_dialler_name_matches_the_xiaomi_recorder() -> None:
    stamp = datetime(2026, 11, 13, 18, 5, 9, tzinfo=IST)
    assert (
        phone.dialler_name("+1 800-889-9999", stamp)
        == "18008899999(18008899999)_20261113180509.mp3"
    )
    assert phone.dialler_name("18008899999", stamp.astimezone(UTC)).endswith("_20261113180509.mp3")
    assert phone.dialler_name("+91 1800 889 9999", stamp).startswith("18008899999(18008899999)_")
    assert phone.dialler_name("+91 00000 10001", stamp).startswith(
        "00910000010001(00910000010001)_"
    )
    with pytest.raises(ValueError):
        phone.dialler_name("12", stamp)


def test_work_hours_parse_like_the_server() -> None:
    parsed = phone.parse_hours(
        {"work_hours": {"days": [0, 1, 2, 3, 4, 5, 9], "start": "10:30", "end": "19:00"}}
    )
    assert parsed == HOURS
    assert phone.parse_hours({}) is None
    assert (
        phone.parse_hours({"work_hours": {"days": [1], "start": "19:00", "end": "10:00"}}) is None
    )


def test_calls_are_stamped_back_to_back_inside_work_hours() -> None:
    now = datetime(2026, 11, 13, 16, 0, tzinfo=IST)  # a Friday afternoon
    starts = phone.plan_slots([120, 90, 65], HOURS, now, gap_seconds=180, min_age_seconds=150)
    assert starts == sorted(starts)
    assert starts[1] - starts[0] == timedelta(seconds=120 + 180)
    end = starts[-1] + timedelta(seconds=65)
    assert end <= now - timedelta(seconds=150)
    assert all(
        s.weekday() in HOURS.days and time(10, 30) <= s.astimezone(IST).time() for s in starts
    )


def test_an_evening_run_goes_into_the_days_hours_and_a_sunday_run_into_saturday() -> None:
    evening = datetime(2026, 11, 13, 22, 0, tzinfo=IST)
    starts = phone.plan_slots([100, 100], HOURS, evening)
    assert starts[-1] + timedelta(seconds=100) <= datetime(2026, 11, 13, 19, 0, tzinfo=IST)
    sunday = datetime(2026, 11, 15, 12, 0, tzinfo=IST)
    starts = phone.plan_slots([100], HOURS, sunday)
    assert starts[0].astimezone(IST).date().isoformat() == "2026-11-14"


def test_planned_calls_never_overlap_earlier_calls_or_precede_the_lead() -> None:
    now = datetime(2026, 11, 13, 16, 0, tzinfo=IST)
    first = phone.plan_slots([100, 100], HOURS, now)
    used = [(first[0], first[-1] + timedelta(seconds=100))]
    second = phone.plan_slots([100, 100], HOURS, now, used=used)
    assert second[-1] + timedelta(seconds=100) <= used[0][0] - timedelta(seconds=180)
    created = datetime(2026, 11, 13, 15, 0, tzinfo=IST)
    with pytest.raises(ValueError):
        phone.plan_slots([3000, 3000], HOURS, now, not_before=created, days_back=0)


def test_saved_time_is_inside_the_apps_window() -> None:
    stamp = datetime(2026, 11, 13, 15, 0, tzinfo=IST)
    saved = phone.saved_time(stamp, 120.5)
    assert stamp < saved <= stamp + phone.MAX_SAVE_DELAY
    with pytest.raises(ValueError):
        phone.saved_time(stamp, 5 * 3600)


def test_each_run_gets_unique_bytes_with_the_same_audio() -> None:
    audio = b"ID3" + bytes(range(256)) * 40
    one = phone.unique_bytes(audio, "20261113-2200-ab12", "R01")
    two = phone.unique_bytes(audio, "20261113-2300-cd34", "R01")
    assert one[: len(audio)] == audio and len(one) == len(audio) + 128
    assert one[-128:-125] == b"TAG"
    assert hashlib.sha256(one).digest() != hashlib.sha256(two).digest()
    assert phone.unique_bytes(one, "20261113-2300-cd34", "R01") == two  # the old tag is replaced
    with pytest.raises(ValueError):
        phone.unique_bytes(audio, "bad id; rm", "R01")


def test_the_owners_design_phone_is_never_driven() -> None:
    with pytest.raises(phone.AdbError):
        phone.Adb("192.168.1.5:5555")


# ---- the checker ------------------------------------------------------------------------------

SHA = "a" * 64


def _report(**changes):  # type: ignore[no-untyped-def]
    row = {
        "sha": SHA,
        "submission_id": "11111111-2222-3333-4444-555555555555",
        "capture_source": "android_dialer_pickup",
        "uploaded_at": "2026-11-13T16:00:00+00:00",
        "plan_state": "completed",
        "report": True,
        "report_at": "2026-11-13T16:01:30+00:00",
        "summary": True,
        "verdict": True,
        "strengths": 2,
        "improvements": 1,
        "dimensions": 8,
        "sections": 9,
        "focus": "Ask for the budget before the price",
        "purpose": None,
    }
    row.update(changes)
    return row


def _scenario(sid: str):  # type: ignore[no-untyped-def]
    return next(c for c in scenarios.library() if c["id"] == sid)


def test_queries_take_only_hashes_and_ids() -> None:
    since = datetime(2026, 11, 13, tzinfo=UTC)
    sql = check.status_sql([SHA, "not-a-hash'; drop table x; --"], since)
    assert SHA in sql and "drop table" not in sql
    assert "conversation_report_drafts" in sql and "transcript" not in sql.split("FROM")[0]
    with pytest.raises(ValueError):
        check.status_sql(["x"], since)
    with pytest.raises(ValueError):
        check.preflight_sql("85957539' OR 1=1 --")
    with pytest.raises(ValueError):
        check.remote_sql("select 1", env="prod", name="ctp-x", purpose=None)


def test_a_complete_report_passes_the_gate() -> None:
    result = check.judge(_scenario("R01"), _report(), final=False)
    assert result["gate"] == "pass" and result["detect"] == "pass"
    assert result["report_seconds"] == 90
    assert result["link"].endswith("/analysis/calls/11111111-2222-3333-4444-555555555555")


def test_a_report_without_the_coaching_focus_or_a_section_fails() -> None:
    result = check.judge(_scenario("R01"), _report(focus=None, sections=8), final=False)
    assert result["gate"] == "fail"
    assert any("next-call focus" in n for n in result["notes"])
    assert any("sections 8 of 9" in n for n in result["notes"])


def test_holds_are_judged_against_the_expected_hold() -> None:
    held = {
        "sha": SHA,
        "plan_state": "held",
        "failure_code": "ai_no_conversation",
        "report": False,
        "capture_source": "android_dialer_pickup",
    }
    assert check.judge(_scenario("R14"), held, final=False)["gate"] == "pass"
    assert (
        check.judge(_scenario("R09"), {**held, "failure_code": "ai_short_call"}, final=False)[
            "gate"
        ]
        == "pass"
    )
    assert check.judge(_scenario("R01"), held, final=False)["gate"] == "fail"
    other = check.judge(_scenario("R14"), {**held, "failure_code": "stage_uncertain"}, final=False)
    assert other["gate"] == "fail" and "held:stage_uncertain" in other["notes"]
    assert check.judge(_scenario("R14"), _report(), final=False)["gate"] == "fail"


def test_a_personal_call_coached_as_sales_passes_the_gate_but_fails_detection() -> None:
    coached = check.judge(_scenario("R10"), _report(), final=False)
    assert coached["gate"] == "pass" and coached["detect"] == "fail"
    assert "coached as a sales call" in coached["detected"]
    recognised = check.judge(_scenario("R10"), _report(purpose="personal"), final=False)
    assert recognised["detect"] == "pass"
    wrong_kind = check.judge(_scenario("R10"), _report(purpose="internal"), final=False)
    assert wrong_kind["detect"] == "pass" and any(
        "purpose internal" in n for n in wrong_kind["notes"]
    )


def test_unfinished_calls_wait_then_fail_and_web_uploads_dont_count() -> None:
    assert check.judge(_scenario("R01"), None, final=False)["gate"] == "pending"
    missing = check.judge(_scenario("R01"), None, final=True)
    assert missing["gate"] == "fail" and missing["notes"] == ["never uploaded"]
    waiting = {"sha": SHA, "plan_state": "running", "report": False}
    assert check.judge(_scenario("R01"), waiting, final=True)["notes"] == ["still analysing"]
    web = check.judge(_scenario("R01"), _report(capture_source="web_upload"), final=False)
    assert web["gate"] == "fail"


def test_the_run_passes_only_on_gates_and_a_live_app() -> None:
    ok = {"id": "R01", "gate": "pass", "detect": "pass"}
    gap = {"id": "R10", "gate": "pass", "detect": "fail"}
    assert check.run_verdict([ok, gap], crashes=[], app_alive=True, strict=False)["passed"] is True
    assert check.run_verdict([ok, gap], crashes=[], app_alive=True, strict=True)["passed"] is False
    assert (
        check.run_verdict([ok], crashes=["FATAL EXCEPTION"], app_alive=True, strict=False)["passed"]
        is False
    )
    assert check.run_verdict([ok], crashes=[], app_alive=False, strict=False)["passed"] is False
    bad = {"id": "R06", "gate": "fail", "detect": "n/a"}
    assert check.run_verdict([ok, bad], crashes=[], app_alive=True, strict=False)[
        "gate_failed"
    ] == ["R06"]


# ---- the page and the runner ------------------------------------------------------------------


def test_the_page_lists_every_scenario_and_escapes_text() -> None:
    rows = []
    for sid, row in (("R01", _report()), ("R10", _report(summary_head="<script>x</script>"))):
        call = _scenario(sid)
        rows.append(
            {
                "id": sid,
                "title": call["title"],
                "persona": call["persona"],
                "expect": call["expect"],
                **check.judge(call, row, final=True),
            }
        )
    verdict = check.run_verdict(rows, crashes=[], app_alive=True, strict=False)
    html = page.render(
        {
            "run_id": "20261113-2200-ab12",
            "results": rows,
            "verdict": verdict,
            "app": {"versionName": "1.0.99<b>"},
            "environment": "production",
        }
    )
    assert "R01" in html and "R10" in html and "Every gate passed" in html
    assert "1.0.99&lt;b&gt;" in html and "<script>x" not in html
    assert "Non-sales calls caught<b>0 of 1</b>" in html


def test_runner_keeps_clear_of_earlier_calls_and_estimates_spend(tmp_path: Path) -> None:
    pre = {"calls": [{"at": "2026-11-13T12:00:00+00:00", "seconds": "120"}, {"at": "bad"}]}
    blocks = run.used_blocks(pre, tmp_path)
    assert blocks == [
        (datetime(2026, 11, 13, 12, 0, tzinfo=UTC), datetime(2026, 11, 13, 12, 2, tzinfo=UTC))
    ]
    rows = [{"expect": c["expect"]} for c in scenarios.pick("smoke")]
    assert 7 <= run.estimate(rows) <= 15
