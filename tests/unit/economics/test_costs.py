"""AC's real monthly cost (owner, 30 Oct 2026): the register, a cost a month, allocation by
measured keys, profit or loss per product, and the register in the Economics view."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from ac_platform.economics import burn, costs, policy, service
from ac_platform.economics.model import Fees, PlanTerms

NOW = datetime(2026, 10, 30, 4, 0, tzinfo=UTC)
OCTOBER = date(2026, 10, 15)
FEES = Fees(gst_rate=0.18, razorpay_rate=0.02, razorpay_gst_on_fee=True, play_rate=0.15)
PERSONAL = PlanTerms(
    key="personal",
    name="Personal",
    per_seat=False,
    prices_include_gst=True,
    monthly_paise=249_900,
    yearly_paise=None,
    minutes=800,
)


def _item(key: str, **fields: Any) -> dict[str, Any]:
    return {
        "key": key,
        "vendor": fields.pop("vendor", "Vendor"),
        "label": fields.pop("label", key),
        "category": fields.pop("category", "tools"),
        "centre": fields.pop("centre", "company"),
        "cadence": fields.pop("cadence", "monthly"),
        "rupees": fields.pop("rupees", 1000),
        "allocation": fields.pop("allocation", {"rule": "direct", "product": "company"}),
        **fields,
    }


# Agent work in one 30-day window, as the nightly job writes it (list-price weighted).
TOKENS = {
    "claude": {"sales_xray": 50, "ops": 40, "learner": 5, "pulse_ea": 5},
    "codex": {"sales_xray": 64, "ops": 32, "learner": 4},
}


def test_a_cost_a_month_by_cadence_and_life() -> None:
    assert costs.monthly(_item("a", rupees=1200), OCTOBER) == 1200
    assert costs.monthly(_item("q", cadence="quarterly", rupees=3000), OCTOBER) == 1000
    assert costs.monthly(_item("y", cadence="yearly", rupees=1200), OCTOBER) == 100
    assert costs.monthly(_item("u", cadence="usage", rupees=2000), OCTOBER) == 2000
    phone = _item("p", cadence="one_time", rupees=24_000, started="2026-10-20", life_months=24)
    assert costs.monthly(phone, OCTOBER) == 1000
    assert costs.monthly(phone, date(2028, 9, 1)) == 1000  # the 24th month
    assert costs.monthly(phone, date(2028, 10, 1)) == 0  # spread in full
    assert costs.monthly(phone, date(2026, 9, 30)) == 0  # not bought yet
    ended = _item("e", started="2026-08-01", ended="2026-09-30")
    assert costs.monthly(ended, date(2026, 9, 1)) == 1000
    assert costs.monthly(ended, OCTOBER) == 0
    future = _item("f", started="2026-11-01")
    assert costs.monthly(future, OCTOBER) == 0


def test_agent_work_split_by_product() -> None:
    keys = costs.Keys(tokens=TOKENS)
    # Claude: Sales X-Ray 50 and learner 5 of the 55 built; ops 40 spread the same way.
    claude = costs.token_shares(keys, "claude", "pro_rata")
    assert claude["sales_xray"] == pytest.approx(0.5 + 0.4 * 50 / 55)
    assert claude["learner"] == pytest.approx(0.05 + 0.4 * 5 / 55)
    assert claude["other_companies"] == pytest.approx(0.05)
    kept = costs.token_shares(keys, "claude", "company")
    assert kept == pytest.approx(
        {"sales_xray": 0.5, "learner": 0.05, "other_companies": 0.05, "company": 0.4}
    )
    both = costs.token_shares(keys, "all", "company")
    assert both["sales_xray"] == pytest.approx((0.5 + 0.64) / 2)
    assert sum(both.values()) == pytest.approx(1)
    assert costs.token_shares(costs.Keys(), "claude", "pro_rata") == {}


def test_allocation_rules_and_unmeasured_keys() -> None:
    keys = costs.Keys(tokens=TOKENS, cpu={"apps": 60, "agents": 30, "other": 10})
    direct = _item("d", allocation={"rule": "direct", "product": "sales_xray"})
    assert costs.allocate(direct, keys, "pro_rata") == ({"sales_xray": 1.0}, "direct")
    people = _item("p", allocation={"rule": "fixed", "shares": {"sales_xray": 75, "company": 25}})
    assert costs.allocate(people, keys, "pro_rata")[0] == {"sales_xray": 0.75, "company": 0.25}
    server, basis = costs.allocate(_item("s", allocation={"rule": "cpu_share"}), keys, "company")
    assert basis == "server time measured"
    # Apps 60% to Sales X-Ray; the agents' 30% by Codex's work; other 10% to the company.
    assert server["sales_xray"] == pytest.approx(0.6 + 0.3 * 0.64)
    assert server["company"] == pytest.approx(0.1 + 0.3 * 0.32)
    claude = _item("c", allocation={"rule": "token_burn", "tool": "claude"})
    assert costs.allocate(claude, costs.Keys(), "pro_rata") == (
        {"company": 1.0},
        "agent work not measured yet",
    )
    overhead = _item("o", allocation={"rule": "revenue_share"})
    assert costs.allocate(overhead, costs.Keys(), "pro_rata") == (
        {"company": 1.0},
        "no money in yet",
    )
    paid = costs.Keys(revenue={"sales_xray": 5000})
    assert costs.allocate(overhead, paid, "pro_rata") == ({"sales_xray": 1.0}, "money in")


def test_the_month_by_category_centre_and_product() -> None:
    register = [
        _item(
            "claude",
            category="ai_subscriptions",
            centre="agents",
            rupees=20_338.14,
            allocation={"rule": "token_burn", "tool": "claude"},
        ),
        _item(
            "gemini",
            category="ai_product",
            centre="sales_xray",
            cadence="usage",
            rupees=2000,
            allocation={"rule": "direct", "product": "sales_xray"},
        ),
        _item(
            "play",
            category="store_fees",
            centre="sales_xray",
            cadence="one_time",
            rupees=2200,
            started="2026-10-20",
            allocation={"rule": "direct", "product": "sales_xray"},
        ),
        _item("domain", category="workspace", cadence="yearly", rupees=1200),
    ]
    keys = costs.Keys(tokens=TOKENS, revenue={"sales_xray": 6000})
    picture = costs.analysis(
        register,
        month=OCTOBER,
        keys=keys,
        platform_work="company",
        contribution={"personal": 1500, "seat": None},
    )
    total = 20_338.14 + 2000 + 2200 / 24 + 100
    assert picture["month"] == "2026-10"
    assert picture["total"] == pytest.approx(total, abs=0.01)
    assert [row["key"] for row in picture["by_category"]] == [
        "ai_subscriptions",
        "ai_product",
        "workspace",
        "store_fees",
    ]
    centres = {row["key"]: row["rupees"] for row in picture["by_centre"]}
    assert centres["agents"] == pytest.approx(20_338.14)
    assert centres["people"] == 0
    play = next(row for row in picture["items"] if row["key"] == "play")
    assert play["monthly"] == pytest.approx(91.67) and play["months_left"] == 23
    products = {row["key"]: row for row in picture["products"]}
    sx = products["sales_xray"]
    assert sx["costs"] == pytest.approx(20_338.14 * 0.5 + 2000 + 2200 / 24, abs=0.01)
    assert sx["money_in"] == 6000 and sx["profit"] == pytest.approx(6000 - sx["costs"], abs=0.01)
    assert sx["break_even_personal"] == pytest.approx(sx["costs"] / 1500, abs=0.1)
    assert sx["break_even_seats"] is None
    assert products["company"]["costs"] == pytest.approx(20_338.14 * 0.4 + 100, abs=0.01)
    assert picture["overall"]["costs"] == pytest.approx(total, abs=0.01)
    assert picture["overall"]["profit"] == pytest.approx(6000 - total, abs=0.01)
    assert picture["overall"]["break_even_personal"] == pytest.approx(total / 1500, abs=0.1)


def test_the_register_is_checked() -> None:
    good = _item(
        "phone",
        vendor="Mi",
        label="Redmi test phone",
        category="devices",
        centre="sales_xray",
        cadence="one_time",
        rupees=12_999,
        started="2026-10-02",
        allocation={"rule": "direct", "product": "sales_xray"},
        source="invoice",
        evidence="Order 123",
    )
    config = policy.validate({"costs": [good]})
    assert config["costs"][0]["life_months"] == 24 and config["costs"][0]["currency"] == "INR"
    assert policy.validate({})["costs"] == [] and policy.validate({})["cost_rules"] == {
        "platform_work": "pro_rata"
    }
    people = _item("people", category="people", centre="people")
    refusals = {
        "cost_item": {**good, "salary_of": "x"},
        "cost_category": {**good, "category": "lunch"},
        "cost_started": {**good, "started": None},
        "cost_life": _item("monthly_life", life_months=12),
        "cost_shares": _item(
            "shares_bad", allocation={"rule": "fixed", "shares": {"sales_xray": 60, "company": 30}}
        ),
        "cost_allocation": _item("tool_bad", allocation={"rule": "token_burn", "tool": "gemini"}),
        "cost_ended": _item("ended_bad", started="2026-10-01", ended="2026-09-01"),
        "cost_currency": _item("currency_bad", currency="usd"),
    }
    for code, item in refusals.items():
        with pytest.raises(policy.SettingsError) as raised:
            policy.validate({"costs": [item]})
        assert raised.value.code == code, code
    # People and debt are one total each, never one line per person.
    with pytest.raises(policy.SettingsError) as raised:
        policy.validate({"costs": [people, {**people, "key": "people_two"}]})
    assert raised.value.code == "cost_single"
    with pytest.raises(policy.SettingsError):
        policy.validate({"cost_rules": {"platform_work": "ignore"}})


def test_the_burn_file_is_counts_only_and_optional(tmp_path: Path) -> None:
    raw = {
        "version": 1,
        "generated_at": "2026-10-30T00:30:00Z",
        "window_days": 30,
        "tools": {
            "claude": {"areas": {"sales_xray": 9.5, "ops": 8, "bad": "x"}, "sources": {"ac": "t"}},
            "codex": {"areas": {}},
        },
        "cpu": {"apps": 0.6, "agents": 0.3, "other": 0.1, "nan": float("inf")},
    }
    parsed = burn.parse(raw)
    assert parsed is not None
    assert parsed["tokens"] == {"claude": {"sales_xray": 9.5, "ops": 8.0}}
    assert parsed["cpu"] == {"apps": 0.6, "agents": 0.3, "other": 0.1}
    assert burn.parse({**raw, "version": 2}) is None
    assert burn.read(str(tmp_path)) is None
    (tmp_path / burn.FILE).write_text(json.dumps(raw), encoding="utf-8")
    assert burn.read(str(tmp_path)) == parsed
    (tmp_path / burn.FILE).write_text("{broken", encoding="utf-8")
    assert burn.read(str(tmp_path)) is None
    assert burn.read(None) is None


def test_the_register_replaces_the_fixed_list_in_the_view() -> None:
    register = [
        _item(
            "claude",
            category="ai_subscriptions",
            centre="agents",
            rupees=20_000,
            allocation={"rule": "token_burn", "tool": "claude"},
        ),
        _item("server", category="servers", centre="sales_xray", allocation={"rule": "cpu_share"}),
    ]
    config = policy.validate({"costs": register})
    keys = burn.parse(
        {"version": 1, "window_days": 30, "tools": {"claude": {"areas": TOKENS["claude"]}}}
    )
    revenue = {
        "mode": "live",
        "recurring_taxable": 2118.0,
        "paying_accounts": 1,
        "active_subscriptions": 1,
    }
    body = service.build(
        [PERSONAL],
        [],
        config,
        environment="production",
        now=NOW,
        days=30,
        burn=keys,
        revenue=revenue,
    )
    keys_line = [line["key"] for line in body["fixed"]["items"]]
    # No AI-for-the-product cost in the register: the measured test-call AI line stays.
    assert keys_line == [service.TEST_AI_KEY, "claude", "server"]
    assert body["fixed"]["building"] == 20_000 and body["fixed"]["running"] == 1000
    assert body["money_in"]["net_month"] == pytest.approx(
        2118 - 2118 * 1.18 * 0.02 * 1.18, abs=0.01
    )
    picture = body["costs"]
    assert picture["total"] == 21_000
    assert picture["keys"]["tools"]["claude"]["sales_xray"] > 0.5
    assert picture["products"][0]["key"] == "sales_xray"
    assert picture["ai_calls"] == {"customer_month": 0.0, "test_month": 0.0}
    with_ai = policy.validate(
        {"costs": [*register, _item("gemini", category="ai_product", centre="sales_xray")]}
    )
    lines = service.build([PERSONAL], [], with_ai, environment="production", now=NOW, days=30)
    assert service.TEST_AI_KEY not in [line["key"] for line in lines["fixed"]["items"]]
    assert lines["money_in"] is None
    # Without a register the fixed list (and no picture) as before.
    legacy = service.build(
        [PERSONAL], [], policy.validate({}), environment="production", now=NOW, days=30
    )
    assert legacy["costs"] is None and legacy["fixed"]["items"][0]["key"] == service.TEST_AI_KEY
