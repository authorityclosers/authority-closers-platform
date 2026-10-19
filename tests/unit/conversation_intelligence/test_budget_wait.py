"""A call out of AI budget waits and resumes (owner, 19 Oct 2026): typed refusal, public code."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from ac_platform.conversation_intelligence.acquisition_reports import _progress_failure_code
from ac_platform.conversation_intelligence.checkpoints import SourceBinding
from ac_platform.conversation_intelligence.entitlements import BudgetExhausted, reserve
from tests.unit.conversation_intelligence.test_entitlements import (
    accounts,
    permission,
    quote,
    reserved,
)


def test_budget_refusals_are_typed_and_other_refusals_are_not() -> None:
    first = reserved(cap=4000)
    minutes, _ = accounts(tenant="tenant-b", account="account-b")
    second = quote(
        source=SourceBinding("tenant-b", "recording-b", "3" * 64, "v1"), account_id="account-b"
    )
    with pytest.raises(BudgetExhausted, match="shared project budget exhausted"):
        reserve(minutes, first.budget, "reserve-b", second, permission(second), 200)
    small = replace(second, max_cost_paise=1)
    with pytest.raises(BudgetExhausted, match="current release project budget exhausted"):
        reserve(
            minutes, first.budget, "reserve-c", small, permission(small), 200, release_cap_paise=1
        )
    # Not enough customer minutes is a different refusal: it doesn't wait for budget.
    poor, budget = accounts(seconds=1)
    value = quote()
    with pytest.raises(ValueError) as refused:
        reserve(poor, budget, "reserve-d", value, permission(value), 200)
    assert not isinstance(refused.value, BudgetExhausted)


def _plan(state: str, code: str | None, generation: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        state=state, generation=generation, progress={} if code is None else {"failure_code": code}
    )


def test_the_app_sees_waiting_for_budget_only_on_an_active_waiting_call() -> None:
    def code(plan: SimpleNamespace, *, has_report: bool = False) -> str | None:
        return _progress_failure_code(plan, [], generation=1, has_report=has_report)  # type: ignore[arg-type]

    assert code(_plan("active", "budget_cap_reached")) == "budget_cap_reached"
    assert code(_plan("active", "budget_cap_reached"), has_report=True) is None
    assert code(_plan("active", "budget_cap_reached", generation=2)) is None
    assert code(_plan("active", "stage_failed")) is None  # an active call shows no other code
    assert code(_plan("active", None)) is None
    assert code(_plan("held", "processing_budget_expired")) == "processing_budget_expired"
