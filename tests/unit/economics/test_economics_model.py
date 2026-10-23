"""Sales X-Ray unit economics (23 Oct 2026): revenue after GST and fees, margins, break-even."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ac_platform.conversation_intelligence.analysis_engine import registry
from ac_platform.conversation_intelligence.cost_metrics import Call, Export, Step
from ac_platform.economics import policy, service
from ac_platform.economics.model import Fees, PlanTerms, Route, TopUp, economics

NOW = datetime(2026, 10, 23, 4, 0, tzinfo=UTC)
FEES = Fees(gst_rate=0.18, razorpay_rate=0.02, razorpay_gst_on_fee=True, play_rate=0.15)
# The plans table on 23 Oct (AUT-739 prices, revision 3).
PERSONAL = PlanTerms(
    key="personal",
    name="Personal",
    per_seat=False,
    prices_include_gst=True,
    monthly_paise=249_900,
    yearly_paise=2_699_000,
    minutes=800,
    top_ups=(TopUp(key="topup_100", minutes=100, price_paise=29_900),),
)
ORGANISATION = PlanTerms(
    key="organisation",
    name="Organisation",
    per_seat=True,
    prices_include_gst=False,
    monthly_paise=1_000_000,
    yearly_paise=10_800_000,
    minutes=1000,
    top_ups=(TopUp(key="topup_500", minutes=500, price_paise=129_900),),
)
# ₹ per audio minute on production's mix (registry v2, today's configuration).
STANDARD = Route(
    id="today-brain4-read", label="today", source="projection", per_audio_minute=0.8545
)
FIXED = [
    {"key": "servers", "label": "Servers", "rupees": 12_700, "kind": "running"},
    {"key": "agents", "label": "Agents", "rupees": 39_900, "kind": "building"},
]


def _run(**overrides):
    options = dict(
        audio_per_billed=297.3 / 266.2,
        fixed=FIXED,
        fees=FEES,
        play_plans=["personal"],
        break_even_route="today-brain4-read",
        trial_minutes=60,
        trial_conversion=0.10,
        target_margin=0.5,
    )
    options.update(overrides)
    return economics([PERSONAL, ORGANISATION], [STANDARD], **options)


def _offer(body, offer_id):
    return next(row for row in body["offers"] if row["id"] == offer_id)


def test_personal_after_gst_and_fees_and_its_margins() -> None:
    body = _run()
    web = _offer(body, "personal.monthly.web")
    # ₹2,499 includes GST: ₹2,117.80 without it; Razorpay 2% plus GST on the fee of ₹2,499.
    assert web["gross"] == 2499.0 and web["ex_gst"] == pytest.approx(2117.80, abs=0.01)
    assert web["fee"] == pytest.approx(58.98, abs=0.01)
    assert web["net"] == pytest.approx(2058.82, abs=0.01)
    full = web["margins"]["today-brain4-read"][-1]
    assert full["use"] == 1.0
    # 800 plan minutes at ₹0.8545 an audio minute and 1.117 audio minutes a plan minute.
    assert full["cost"] == pytest.approx(763.5, abs=0.5)
    assert full["margin"] == pytest.approx(1295.3, abs=0.5)
    play = _offer(body, "personal.monthly.play")
    assert play["fee"] == pytest.approx(317.67, abs=0.01) and play["net"] == pytest.approx(
        1800.13, abs=0.01
    )
    yearly = _offer(body, "personal.yearly.web")
    assert yearly["price_paise_per_month"] == round(2_699_000 / 12)


def test_organisation_is_priced_plus_gst_per_seat() -> None:
    seat = _offer(_run(), "organisation.monthly.web")
    assert seat["unit"] == "seat" and seat["gross"] == 11800.0 and seat["ex_gst"] == 10000.0
    assert seat["net"] == pytest.approx(9721.52, abs=0.01)
    assert "organisation.monthly.play" not in [row["id"] for row in _run()["offers"]]


def test_break_even_trial_and_top_ups() -> None:
    body = _run()
    web = _offer(body, "personal.monthly.web")["break_even"]
    assert web["1.0"]["running"] == pytest.approx(9.8, abs=0.1)
    assert web["1.0"]["total"] == pytest.approx(40.6, abs=0.1)
    seat = _offer(body, "organisation.monthly.web")["break_even"]
    assert seat["1.0"]["total"] == pytest.approx(6.0, abs=0.1)
    assert body["fixed"] == {
        "items": FIXED,
        "running": 12700.0,
        "building": 39900.0,
        "total": 52600.0,
    }
    assert body["trial"]["cost"] == pytest.approx(57.3, abs=0.1)
    assert body["trial"]["per_paying_user"] == pytest.approx(572.6, abs=0.5)
    personal_pack = next(row for row in body["top_ups"] if row["key"] == "topup_100")
    assert personal_pack["net_per_minute"] == pytest.approx(2.463, abs=0.001)
    assert personal_pack["margin_share"]["today-brain4-read"] == pytest.approx(0.613, abs=0.002)
    assert body["warnings"] == []


def test_a_route_that_loses_money_is_flagged() -> None:
    dear = Route(id="dear", label="dear", source="projection", per_audio_minute=3.0)
    body = economics(
        [PERSONAL],
        [dear],
        audio_per_billed=1.0,
        fixed=FIXED,
        fees=FEES,
        play_plans=[],
        break_even_route="dear",
        trial_minutes=60,
        trial_conversion=0.1,
        target_margin=0.5,
    )
    kinds = {(row["offer"], row["kind"]) for row in body["warnings"]}
    assert ("personal.monthly.web", "loss_at_full_use") in kinds
    assert ("personal.monthly.web", "below_target_margin") in kinds
    assert _offer(body, "personal.monthly.web")["break_even"]["1.0"]["total"] is None


def _call(call_id: str, kind: str, billed_s: int) -> Call:
    return Call(
        environment="production",
        id=call_id,
        company="c",
        at=NOW,
        kind=kind,
        audio_ms=0,
        billed_s=billed_s,
        plan=None,
        accepted_at=None,
        delivered_at=None,
        report_at=None,
        version=(None, "one-pass-v1", None, None, None),
        gold=(0, 0, 0),
    )


def _step(env: str, call_id: str, stage: str, paise: int, audio_ms: int = 0) -> Step:
    return Step(
        environment=env,
        call=call_id,
        company="c",
        stage=stage,
        provider="gemini",
        model="gemini-3.8-flash",
        status="succeeded",
        attempts=1,
        input_tokens=0,
        output_tokens=0,
        audio_ms=audio_ms,
        elapsed_ms=1,
        paise=paise,
        at=NOW - timedelta(days=1),
    )


def test_measured_route_billed_ratio_and_test_spend_from_the_store() -> None:
    production = Export(
        environment="production",
        generated_at=NOW,
        migration=None,
        window_days=120,
        calls=[_call("real", "real", 540), _call("free", "real", 0), _call("canary", "canary", 60)],
        steps=[
            _step("production", "real", "C2", 300, audio_ms=600_000),
            _step("production", "real", "C4", 700),
            _step("production", "free", "C2", 200, audio_ms=120_000),
            _step("production", "canary", "C2", 100, audio_ms=60_000),
        ],
    )
    staging = Export(
        environment="staging",
        generated_at=NOW,
        migration=None,
        window_days=120,
        calls=[],
        steps=[_step("staging", "s1", "C5", 900)],
    )
    found = service.measure([production, staging], environment="production", now=NOW, days=30)
    # ₹12 on 12 audio minutes; the charged call's 600 s of audio billed as 540 s.
    assert found["per_audio_minute"] == pytest.approx(1.0)
    assert found["audio_per_billed"] == pytest.approx(600 / 540)
    assert found["calls"] == 2 and found["billed_minutes"] == 9.0
    # Analysed, never charged: its AI is a cost of its own.
    assert found["uncharged"] == {"calls": 1, "audio_minutes": 2.0, "rupees": 2.0, "month": 2.0}
    # Production's canary and every staging step, over 30 days (a month already).
    assert found["test_ai_month"] == 10.0
    body = service.build(
        [PERSONAL],
        [production, staging],
        policy.validate({}),
        environment="production",
        now=NOW,
        days=30,
    )
    assert [row["id"] for row in body["routes"]] == policy.DEFAULTS["routes"]
    assert body["fixed"]["items"][0]["key"] == service.TEST_AI_KEY
    assert body["fixed"]["items"][0]["rupees"] == 10.0
    assert body["registry"]["digest"] == registry.digest()
    today = next(row for row in body["routes"] if row["id"] == "today-brain4-read")
    assert today["per_audio_minute"] == pytest.approx(0.8545, abs=0.0005)


def test_settings_defaults_and_refusals() -> None:
    checked = policy.validate({})
    assert checked["break_even_route"] == "today-brain4-read"
    assert sum(item["rupees"] for item in checked["fixed"]) == 51_000
    assert {item["source"] for item in checked["fixed"]} == {"estimate"}
    for bad, code in (
        ({"routes": ["nowhere"]}, "routes"),
        ({"break_even_route": "v2"}, "break_even_route"),
        ({"fees": {"gst_rate": 0.18}}, "fees"),
        (
            {
                "fixed": [
                    {
                        "key": "x1",
                        "label": "X",
                        "rupees": -1,
                        "kind": "running",
                        "source": "invoice",
                    }
                ]
            },
            "fixed_rupees",
        ),
        (
            {
                "fixed": [
                    {"key": "x1", "label": "X", "rupees": 1, "kind": "other", "source": "invoice"}
                ]
            },
            "fixed_kind",
        ),
        ({"price": 1}, "unknown_field"),
    ):
        with pytest.raises(policy.SettingsError) as raised:
            policy.validate(bad)
        assert raised.value.code == code
