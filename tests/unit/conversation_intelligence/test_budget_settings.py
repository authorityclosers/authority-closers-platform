"""Budget settings (owner decision, 19 Oct 2026): periods in India time, what counts in a
period, and the ledger's period check."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from ac_platform.conversation_intelligence.budget_settings import (
    BudgetLimits,
    limits_from,
    period_end,
    period_start,
)
from ac_platform.conversation_intelligence.entitlements import (
    BudgetExhausted,
    committed_since,
    reserve,
    settle,
)
from ac_platform.conversation_intelligence.execution_control import budget_view

from .test_entitlements import dispatched, permission, quote, settlement


def test_periods_start_at_midnight_india_time():
    now = datetime(2026, 10, 18, 23, 30, tzinfo=UTC)  # 19 Oct, 05:00 India time
    assert period_start(now, "daily") == datetime(2026, 10, 18, 18, 30, tzinfo=UTC)
    assert period_end(now, "daily") == datetime(2026, 10, 19, 18, 30, tzinfo=UTC)
    assert period_start(now, "monthly") == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)
    assert period_end(now, "monthly") == datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    december = datetime(2026, 12, 15, tzinfo=UTC)
    assert period_end(december, "monthly") == datetime(2026, 12, 31, 18, 30, tzinfo=UTC)
    assert period_start(now, "lifetime") is None and period_end(now, "lifetime") is None


def setting(**values):
    return SimpleNamespace(
        **{
            "revision": 3,
            "ceiling_paise": 1_000_000,
            "period": "monthly",
            "period_cap_paise": 300_000,
            **values,
        }
    )


def test_limits_use_the_sealed_ceiling_until_the_owner_saves_one():
    now = datetime(2026, 10, 19, tzinfo=UTC)
    sealed = limits_from(None, sealed_ceiling_paise=850_000, ledger_cap_paise=900_000, now=now)
    assert (sealed.ceiling_paise, sealed.period, sealed.cap_paise, sealed.sealed) == (
        850_000,
        "lifetime",
        850_000,
        True,
    )
    assert sealed.reserve_kwargs() == {"release_cap_paise": 850_000}

    monthly = limits_from(
        setting(), sealed_ceiling_paise=850_000, ledger_cap_paise=2_147_483_647, now=now
    )
    start = period_start(now, "monthly")
    assert start is not None
    assert (monthly.ceiling_paise, monthly.cap_paise, monthly.setting_revision) == (
        1_000_000,
        300_000,
        3,
    )
    assert monthly.reserve_kwargs() == {
        "period_cap_paise": 300_000,
        "period_start_epoch": int(start.timestamp()),
    }

    # Lifetime: the owner's ceiling replaces the sealed one; the ledger holds the cap.
    lifetime = limits_from(
        setting(period="lifetime", period_cap_paise=None),
        sealed_ceiling_paise=850_000,
        ledger_cap_paise=600_000,
        now=now,
    )
    assert (lifetime.ceiling_paise, lifetime.cap_paise, lifetime.sealed) == (
        1_000_000,
        600_000,
        False,
    )
    assert lifetime.reserve_kwargs() == {"release_cap_paise": 1_000_000}


def test_a_period_counts_open_holds_and_the_spend_reserved_inside_it():
    started = dispatched()  # quote made at epoch 100, held at most 2,500 paise
    done = settle(started.minutes, started.budget, "reserve-a", settlement(started))
    budget = done.budget
    assert committed_since(budget, None) == 2_000
    assert committed_since(budget, 100) == 2_000  # reserved inside the period
    assert committed_since(budget, 101) == 0  # settled spend from before the period

    later = quote(quote_id="quote-b", input_sha256="3" * 64, created_at_epoch=150)
    with pytest.raises(BudgetExhausted, match="period"):
        reserve(
            done.minutes,
            budget,
            "reserve-b",
            later,
            permission(later),
            200,
            period_cap_paise=2_400,
            period_start_epoch=101,
        )
    with pytest.raises(BudgetExhausted, match="period"):
        reserve(
            done.minutes,
            budget,
            "reserve-b",
            later,
            permission(later),
            200,
            period_cap_paise=4_000,
            period_start_epoch=100,
        )
    held = reserve(
        done.minutes,
        budget,
        "reserve-b",
        later,
        permission(later),
        200,
        period_cap_paise=2_500,
        period_start_epoch=101,
    )
    # Money still held for a running call counts whenever it was reserved.
    assert committed_since(held.budget, 10_000) == 2_500

    view = budget_view(
        held.budget,
        BudgetLimits(
            ceiling_paise=1_000_000,
            period="daily",
            cap_paise=4_000,
            period_start_epoch=101,
            setting_revision=1,
            sealed=False,
        ),
    )
    assert (view["cap_paise"], view["committed_paise"], view["available_paise"]) == (
        4_000,
        2_500,
        1_500,
    )
    assert (view["settled_paise"], view["held_paise"], view["warning"]) == (0, 2_500, "normal")
    # Without limits the view stays the lifetime ledger view.
    assert budget_view(held.budget)["committed_paise"] == 4_500
