"""AI spend rules, prices and the Admin summary (owner, 20 Oct 2026). No database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from ac_platform.ai_spend import ledger, policy
from ac_platform.ai_spend.admin_http import summary


def test_defaults_add_up_to_the_owners_monthly_ceiling() -> None:
    months = [policy.defaults(name)["monthly_cap_inr"] for name in policy.ENVIRONMENTS]
    assert sum(months) == 10_000
    dev = policy.defaults("development-live")
    assert dev["background_enabled"] is False
    assert dev["daily_cap_inr"] == 50
    for name in policy.ENVIRONMENTS:
        assert policy.defaults(name)["backfill_daily_cap_inr"] == 0
        assert policy.defaults(name)["skip_sandbox"] is True


def test_validate_fills_defaults_and_refuses_unknown_or_out_of_range() -> None:
    merged = policy.validate("staging", {"daily_cap_inr": 300, "feature_caps_inr": {"canary": 5}})
    assert merged["daily_cap_inr"] == 300
    assert merged["feature_caps_inr"] == {
        "canary": 5,
        "pointer_review": 30,
        "partner_quote_facts": 20,
        "one_pass": 0,
    }
    for bad in (
        {"surprise": 1},
        {"daily_cap_inr": -1},
        {"daily_cap_inr": True},
        {"monthly_cap_inr": policy.MAX_MONTHLY_INR + 1},
        {"background_enabled": "yes"},
        {"feature_caps_inr": {"call_data_fast": 10}},  # its cap lives on its own page
    ):
        with pytest.raises(policy.SettingsError):
            policy.validate("staging", bad)
    with pytest.raises(policy.SettingsError):
        policy.environment_name("qa")


def test_one_click_raises_and_targets() -> None:
    assert policy.raise_to(50) == 100
    assert policy.raise_to(1000) == 1250
    assert policy.raise_to(500, monthly=True) == 1000
    assert policy.raise_to(policy.MAX_DAILY_INR) == policy.MAX_DAILY_INR
    config = policy.defaults("production")
    raised = policy.with_cap(config, "pointer_review", 250)
    assert policy.cap_of(raised, "pointer_review") == 250
    assert policy.cap_of(raised, "canary") == 10
    assert config["feature_caps_inr"]["pointer_review"] == 200  # the original is untouched
    assert policy.cap_of(policy.with_cap(config, "backfill", 15), "backfill") == 15


@pytest.mark.parametrize(
    ("spent", "cap", "level"),
    [
        (10, 50, None),
        (25, 50, 50),
        (40, 50, 80),
        (50, 50, 100),
        (60, 50, 100),
        (0, 0, None),
        (1, 0, 100),
    ],
)
def test_alert_levels(spent: float, cap: int, level: int | None) -> None:
    assert policy.alert_level(spent, cap) == level


def test_prices_come_from_the_admin_price_sheet() -> None:
    # Gemini 3.8 Flash: $0.75 in, $3.75 out per million tokens, ₹100 per dollar.
    assert ledger.price_inr("gemini", "gemini-3.8-flash", 1_000_000, 0, 0) == (Decimal("75"), True)
    assert ledger.price_inr("gemini", "gemini-3.8-flash", 0, 1_000_000, 0) == (Decimal("375"), True)
    # A Gemini model missing from the sheet is never read as free.
    assert ledger.price_inr("gemini", "gemini-9-unknown", 1_000_000, 0, 0) == (Decimal("75"), True)
    # Scribe v2: $0.22 an hour.
    assert ledger.price_inr("elevenlabs", "scribe_v2", 0, 0, 3_600_000) == (Decimal("22"), True)
    assert ledger.price_inr("nobody", "x", 5, 5, 0) == (Decimal(0), False)


def _row(
    feature: str, inr: str, *, trigger: str = "auto", day: date | None = None
) -> ledger.SpendRow:
    return ledger.SpendRow(
        feature=feature,
        trigger=trigger,
        day=day or datetime.now(UTC).date(),
        provider="gemini",
        model="gemini-3.8-flash",
        requests=1,
        input_tokens=1000,
        output_tokens=100,
        audio_ms=0,
        inr=Decimal(inr),
        priced=True,
    )


def test_summary_totals_alerts_and_projection() -> None:
    now = datetime.now(UTC)
    rows = [
        _row("canary", "6", trigger="release"),
        _row("call_data_deep", "30", trigger="backfill"),
        _row("call_report", "4", trigger="person", day=(now - timedelta(days=3)).date()),
    ]
    config = policy.defaults("development")
    view = summary(rows, rows[:2], rows, config, days=14, now=now, elsewhere=[])
    assert view["now"]["last_24h_inr"] == 36.0
    assert view["window"]["by_trigger"] == {"backfill": 30.0, "person": 4.0, "release": 6.0}
    assert view["window"]["projected_month_inr"] == pytest.approx(40 / 7 * 30, abs=0.01)
    caps = {line["target"]: line for line in view["caps"]}
    assert caps["daily"]["level"] == 50  # ₹36 of ₹50
    assert caps["canary"]["level"] == 50  # ₹6 of ₹10
    assert caps["backfill"]["level"] == 100  # any backfill spend over a ₹0 cap
    assert {line["target"] for line in view["alerts"]} == {"daily", "canary", "backfill"}
    assert view["models"][0]["feature"] == "call_data_deep"
