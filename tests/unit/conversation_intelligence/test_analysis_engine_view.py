"""Expected against actual cost per module, on read (analysis engine phase 1, 22 Oct 2026)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.analysis_engine.view import engine_view
from ac_platform.conversation_intelligence.cost_metrics import Call, Export, Step

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
ENV = "production"


def _call(call_id: str, *, facts: str | None, kind: str = "real", at: datetime = NOW) -> Call:
    return Call(
        environment=ENV,
        id=call_id,
        company="c1",
        at=at,
        kind=kind,
        audio_ms=0,
        billed_s=0,
        plan=None,
        accepted_at=None,
        delivered_at=None,
        report_at=None,
        version=("coaching-v5", facts, "gemini-3.8-flash", None, None),
        gold=(0, 0, 0),
    )


def _step(
    call_id: str,
    stage: str,
    model: str | None,
    *,
    paise: int | None,
    minutes: float = 0.0,
    tokens: tuple[int, int] = (0, 0),
    status: str = "succeeded",
    at: datetime = NOW - timedelta(hours=2),
) -> Step:
    return Step(
        environment=ENV,
        call=call_id,
        company="c1",
        stage=stage,
        provider="gemini",
        model=model,
        status=status,
        attempts=1,
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        audio_ms=int(minutes * 60_000),
        elapsed_ms=1_000,
        paise=paise,
        at=at,
    )


def _export() -> Export:
    old = NOW - timedelta(days=9)
    return Export(
        environment=ENV,
        generated_at=NOW - timedelta(minutes=3),
        migration="0121",
        window_days=14,
        calls=[
            _call("one", facts="one-pass-v1"),
            _call("classic", facts="facts-v2"),
            _call("canary", facts="one-pass-v1", kind="canary"),
            _call("old", facts="one-pass-v1", at=old),
        ],
        steps=[
            # One pass, 10 minutes: the store prices Flash-Lite at the sheet's ₹0.30/min.
            _step("one", "C1", None, paise=0),
            _step("one", "C2", "gemini-3.1-flash-lite", paise=300, minutes=10),
            _step("one", "C4", "gemini-3.8-flash", paise=240, tokens=(10_000, 4_400)),
            _step("one", "C5", "gemini-3.8-flash", paise=190, tokens=(9_000, 3_700)),
            # A re-run counts as spend; a review inside the one-pass answer costs nothing.
            _step("one", "C5", "gemini-3.8-flash", paise=None, status="failed"),
            _step("one", "PR", "gemini-3.8-flash", paise=0),
            # Classic, 5 minutes on Scribe, an unknown model and an unpriced Luna read.
            _step("classic", "C2", "scribe_v2", paise=183, minutes=5),
            _step("classic", "C4", "gemini-9", paise=50, tokens=(2_000, 300)),
            _step("classic", "C4", "gpt-6-luna:flex", paise=None),
            _step("classic", "AR", "gemini-3.8-flash", paise=99),
            # Never counted: a canary, and a call first transcribed before the window.
            _step("canary", "C2", "gemini-3.1-flash-lite", paise=300, minutes=10),
            _step("old", "C2", "gemini-3.1-flash-lite", paise=300, minutes=10, at=old),
        ],
    )


def _row(view: dict, module_id: str) -> dict:
    return next(row for row in view["modules"] if row["id"] == module_id)


def test_expected_against_actual_by_module() -> None:
    view = engine_view([_export()], environment=ENV, now=NOW, days=7)
    assert view["available"] and view["age_seconds"] == 180
    assert view["registry"]["version"] == registry.VERSION
    assert view["registry"]["digest"] == registry.digest()
    assert view["window"] == {
        "calls": 2,
        "analysed": 2,
        "short": 0,
        "audio_minutes": 15.0,
        "actual_rupees": 9.63,
        "expected_rupees": 8.45,
        "actual_per_minute": 0.642,
        "expected_per_minute": 0.563,
    }
    transcript = _row(view, "c2.flash-lite")
    assert transcript["calls"] == 1 and transcript["audio_minutes"] == 10.0
    assert transcript["actual_rupees"] == 3.0 and transcript["expected_rupees"] == 2.33
    # The sheet's ceiling against the receipts' measured rate: flagged for a refit.
    assert transcript["ratio"] == pytest.approx(1.288, abs=0.001) and transcript["drifting"]
    one_pass = _row(view, "c4.one-pass-v1")
    assert one_pass["expected_rupees"] == 2.4 and one_pass["ratio"] == 1.0
    assert not one_pass["drifting"]
    assert one_pass["tokens"]["expected_in"] == 3_579 + 6_490
    assert one_pass["tokens"]["expected_out"] == 3_379 + 1_010
    assert one_pass["tokens"]["ratio_in"] == pytest.approx(10_000 / 10_069, abs=0.001)
    report = _row(view, "c5.after-one-pass")
    assert report["steps"] == 2 and report["actual_rupees"] == 1.9
    assert report["expected_rupees"] == 1.89 and report["ratio"] == 1.007
    assert _row(view, "pr.in-one-pass")["expected_rupees"] == 0.0
    assert _row(view, "pr.in-one-pass")["ratio"] is None
    assert _row(view, "c1.audio-check")["actual_rupees"] == 0.0
    scribe = _row(view, "c2.scribe")
    assert scribe["expected_rupees"] == pytest.approx(1.83, abs=0.01)


def test_unknown_models_and_unpriced_reads_are_shown_not_guessed() -> None:
    view = engine_view([_export()], environment=ENV, now=NOW, days=7)
    unknown = _row(view, "C4·gemini-9")
    assert unknown["modelled"] is False and unknown["model"] == "gemini-9"
    assert unknown["expected_rupees"] is None and unknown["actual_rupees"] == 0.5
    # A classic call never takes a one-pass module, so its Luna read is not modelled.
    assert "c4.one-pass-v1.luna-flex" not in [row["id"] for row in view["modules"]]
    unpriced = _row(view, "C4·gpt-6-luna:flex")
    assert unpriced["unpriced_steps"] == 1 and unpriced["actual_rupees"] == 0.0
    # Lead Desk work (AI replies) is not call analysis.
    assert not [row for row in view["modules"] if row["stage"] == "AR"]
    assert [row["id"] for row in view["modules"]][-2:] == ["C4·gemini-9", "C4·gpt-6-luna:flex"]


def test_plans_are_projected_on_the_windows_own_mix() -> None:
    view = engine_view([_export()], environment=ENV, now=NOW, days=7)
    plans = {row["id"]: row for row in view["plans"]}
    assert set(plans) == {item.id for item in registry.PLANS}
    today = plans["today"]["window"]
    assert today["calls"] == 2 and today["audio_minutes"] == 15.0
    expected = registry.project(registry.plan("today"), [(1, 10.0), (1, 5.0)])
    assert today == expected
    assert plans["v2-luna-flex-compact"]["window"]["per_minute"] < today["per_minute"]


def test_a_short_window_and_a_missing_export() -> None:
    view = engine_view([_export()], environment=ENV, now=NOW + timedelta(days=1), days=1)
    assert view["window"]["calls"] == 0 and view["modules"] == []
    assert view["window"]["actual_per_minute"] is None
    missing = engine_view([_export()], environment="staging", now=NOW, days=7)
    assert missing["available"] is False and missing["registry"]["digest"] == registry.digest()
