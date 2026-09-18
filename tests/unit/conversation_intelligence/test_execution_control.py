from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.entitlements import mark_dispatched, mark_uncertain
from ac_platform.conversation_intelligence.execution_control import (
    ConversationExecutionPaused,
    already_started_effect,
    budget_view,
    require_execution_enabled,
)
from tests.unit.conversation_intelligence.test_entitlements import reserved


@pytest.mark.parametrize(
    "cost,level", [(790, "normal"), (800, "warning"), (900, "critical"), (1000, "exhausted")]
)
def test_budget_warning_counts_reserved_money_without_inventing_actual(cost, level):
    transition = reserved(cap=1000, max_cost_paise=cost)
    value = budget_view(transition.budget)
    assert value["warning"] == level
    assert value["available_paise"] == 1000 - cost
    assert value["held_paise"] == cost
    assert value["settled_paise"] == 0
    assert value["uncertain_paise"] == 0


def test_uncertain_cost_stays_held():
    value = reserved(cap=1000, max_cost_paise=850)
    value = mark_dispatched(value.minutes, value.budget, "reserve-a", "attempt-a", 200)
    value = mark_uncertain(value.minutes, value.budget, "reserve-a", "ref:uncertain")
    result = budget_view(value.budget)
    assert result["held_paise"] == result["uncertain_paise"] == 850
    assert result["settled_paise"] == 0 and result["available_paise"] == 150


def test_already_started_exception_is_exact_scope_and_restored(monkeypatch):
    import asyncio

    import ac_platform.conversation_intelligence.execution_control as module

    monkeypatch.setattr(module, "execution_state", AsyncMock(return_value={"paused": True}))
    tenant = uuid4()

    async def exercise():
        with already_started_effect(environment="test", operations_tenant_id=tenant):
            await require_execution_enabled(None, environment="test", operations_tenant_id=tenant)
            with pytest.raises(ConversationExecutionPaused):
                await require_execution_enabled(
                    None, environment="production", operations_tenant_id=tenant
                )
            with pytest.raises(ConversationExecutionPaused):
                await require_execution_enabled(
                    None, environment="test", operations_tenant_id=uuid4()
                )
        with pytest.raises(ConversationExecutionPaused):
            await require_execution_enabled(None, environment="test", operations_tenant_id=tenant)

    asyncio.run(exercise())
