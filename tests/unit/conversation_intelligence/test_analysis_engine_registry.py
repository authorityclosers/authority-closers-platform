"""Analysis engine registry v0 (22 Oct 2026): it recomputes the design's measured numbers."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ac_platform.conversation_intelligence.admin_pricing import FX_USD_TO_INR, PRICING_SNAPSHOTS
from ac_platform.conversation_intelligence.analysis_engine import registry

# docs/research/2026-10-22-adaptive-analysis/01-research-one-pass-to-production.md §4, with the
# Brain 4.0 answer from 1.5k to 2.5k output tokens (the registry uses the 2k midpoint).
DESIGN = {
    "today-brain4-read": (0.872, 0.918),
    "v2": (0.826, 0.872),
    "v2-report-on-demand": (0.621, 0.667),
    "v2-flex-report-on-demand": (0.311, 0.334),
    "v2-luna-flex-report-on-demand": (0.153, 0.156),
    "v2-luna-flex-compact": (0.112, 0.115),
}


def _without_fast_facts(plan_id: str, **options: float) -> float:
    """The design priced short calls at the transcript only; plans add fast lead facts."""
    projected = registry.project(registry.plan(plan_id), registry.REFERENCE_MIX, **options)
    return projected["per_minute"] - projected["modules"].get("cdf.fast", 0.0)


def test_today_recomputes_the_measured_rate_on_the_reference_mix() -> None:
    projected = registry.project(registry.plan("today"), registry.REFERENCE_MIX)
    assert projected["calls"] == 62
    assert projected["audio_minutes"] == 284.4
    assert round(_without_fast_facts("today"), 3) == 0.709
    # Fast lead facts on the 27 short calls add under half a paisa a minute.
    assert 0.004 < projected["modules"]["cdf.fast"] < 0.005
    assert projected["modules"]["c2.flash-lite"] == 0.233
    assert round(projected["modules"]["c5.after-one-pass"], 3) == 0.205


@pytest.mark.parametrize(("plan_id", "bounds"), sorted(DESIGN.items()))
def test_every_plan_lands_in_the_designs_range(plan_id: str, bounds: tuple[float, float]) -> None:
    low, high = bounds
    assert low <= _without_fast_facts(plan_id) <= high


def test_each_tenth_of_calls_asking_for_the_report_adds_a_tenth_of_its_cost() -> None:
    plan = registry.plan("v2-report-on-demand")
    none = registry.project(plan, registry.REFERENCE_MIX)
    tenth = registry.project(plan, registry.REFERENCE_MIX, uptake=0.1)
    assert tenth["per_minute"] - none["per_minute"] == pytest.approx(0.0205, abs=0.0002)
    with pytest.raises(ValueError):
        registry.project(plan, registry.REFERENCE_MIX, uptake=1.5)


def test_without_a_module_is_the_plan_less_that_module() -> None:
    plan = registry.plan("today")
    whole = registry.project(plan, registry.REFERENCE_MIX)
    less = registry.project(plan, registry.REFERENCE_MIX, without=frozenset({"c5.after-one-pass"}))
    assert whole["per_minute"] - less["per_minute"] == pytest.approx(
        whole["modules"]["c5.after-one-pass"], abs=0.0002
    )


def test_the_report_table_gives_back_productions_receipts_by_length() -> None:
    # Production's one-pass C4 plus report, rupees a call, at each length's mean minutes.
    one_pass = registry.module("c4.one-pass-v1").fit
    report = registry.module("c5.after-one-pass").fit
    for (_calls, minutes), measured in zip(
        registry.REFERENCE_MIX[1:], (2.91, 3.32, 4.11, 4.86, 6.06), strict=True
    ):
        assert one_pass.cost(minutes) + report.cost(minutes) == pytest.approx(measured, abs=0.001)


def test_flex_is_half_the_standard_price() -> None:
    for standard, flex in (
        ("c2.flash-lite", "c2.flash-lite.flex"),
        ("c4.one-pass-v1", "c4.one-pass-v1.flex"),
        ("c4.one-pass-v2", "c4.one-pass-v2.flex"),
        ("c5.after-one-pass", "c5.after-one-pass.flex"),
    ):
        for minutes in (0.5, 4.0, 25.0):
            expected = registry.module(standard).fit.cost(minutes) / 2
            # Flash-Lite's measured Flex rate includes fallbacks to standard (₹0.1175 vs ₹0.1165).
            assert registry.module(flex).fit.cost(minutes) == pytest.approx(expected, rel=0.01)


def test_token_rates_and_the_planning_rate_are_the_price_sheets() -> None:
    assert float(FX_USD_TO_INR) == registry.PLANNING_FX
    flash = PRICING_SNAPSHOTS[("gemini", "gemini-3.8-flash")]
    flex = PRICING_SNAPSHOTS[("gemini", "gemini-3.8-flash:flex")]
    for module_id, sheet in (
        ("c4.one-pass-v1", flash),
        ("c4.classic", flash),
        ("pr.classic", flash),
        ("c5.classic", flash),
        ("c4.one-pass-v1.flex", flex),
    ):
        usd = registry.module(module_id).fit.usd
        assert usd == (
            float(sheet.input_usd_per_million_tokens),
            float(sheet.output_usd_per_million_tokens),
        ), module_id
    scribe = PRICING_SNAPSHOTS[("elevenlabs", "scribe_v2")]
    assert registry.module("c2.scribe").fit.cost(60) == pytest.approx(
        float(scribe.usd_per_hour) * registry.PLANNING_FX
    )


def test_recorded_steps_find_their_module() -> None:
    match = registry.match
    assert match("C2", "gemini-3.1-flash-lite", None).id == "c2.flash-lite"
    assert match("C2", "gemini-3.1-flash-lite:flex", None).id == "c2.flash-lite.flex"
    assert match("C2", "scribe_v2", "facts-v2").id == "c2.scribe"
    assert match("C4", "gemini-3.8-flash", "one-pass-v1").id == "c4.one-pass-v1"
    assert match("C4", "gemini-3.8-flash:flex", "one-pass-v1").id == "c4.one-pass-v1.flex"
    assert match("C4", "gemini-3.8-flash", "one-pass-v2").id == "c4.one-pass-v2"
    assert match("C4", "gpt-6-luna:flex", "one-pass-v1").id == "c4.one-pass-v1.luna-flex"
    assert match("C4", "gemini-3.8-flash", None).id == "c4.classic"
    assert match("C4", "gemini-3.8-flash", "facts-v2").id == "c4.classic"
    assert match("PR", "gemini-3.8-flash", "facts-v2").id == "pr.classic"
    assert match("PR", "gemini-3.8-flash", "one-pass-v1").id == "pr.in-one-pass"
    assert match("C5", "gemini-3.8-flash", "one-pass-v1").id == "c5.after-one-pass"
    assert match("C5", "gemini-3.8-flash", "facts-v1").id == "c5.classic"
    assert match("CDF", "gemini-3.1-flash-lite", None).id == "cdf.fast"
    assert match("C1", None, None).id == "c1.audio-check"
    # Unknown models are never guessed, and modules with no route never match a step.
    assert match("C4", "gemini-9", "facts-v2") is None
    assert match("C2", "deepgram-nova-3", None) is None
    assert match("B4", "gemini-3.8-flash", None) is None


def test_plans_name_known_modules_and_ids_are_unique() -> None:
    ids = [item.id for item in registry.MODULES]
    assert len(ids) == len(set(ids))
    assert len({item.id for item in registry.PLANS}) == len(registry.PLANS)
    for item in registry.PLANS:
        for module_id in (*item.short, *item.analysed, *item.on_demand):
            registry.module(module_id)


def test_the_digest_moves_with_any_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    before = registry.digest()
    assert len(before) == 10 and before == registry.digest()
    edited = tuple(
        replace(item, fit=replace(item.fit, rupees=(0.0, 0.24)))
        if item.id == "c2.flash-lite"
        else item
        for item in registry.MODULES
    )
    monkeypatch.setattr(registry, "MODULES", edited)
    assert registry.digest() != before


def test_describe_carries_version_examples_and_reference_projections() -> None:
    body = registry.describe()
    assert body["version"] == "analysis-engine-registry/0"
    assert body["digest"] == registry.digest()
    one_pass = next(row for row in body["modules"] if row["id"] == "c4.one-pass-v1")
    assert [row["minutes"] for row in one_pass["examples"]] == [2.0, 5.0, 15.0]
    assert one_pass["examples"][0]["rupees"] == pytest.approx(1.709, abs=0.001)
    assert one_pass["facts"] == ["one-pass-v1"]
    today = next(row for row in body["plans"] if row["id"] == "today")
    assert today["reference"]["calls"] == 62 and today["reference_with_uptake"] is None
    on_demand = next(row for row in body["plans"] if row["id"] == "v2-report-on-demand")
    assert on_demand["reference_with_uptake"]["per_minute"] > on_demand["reference"]["per_minute"]
