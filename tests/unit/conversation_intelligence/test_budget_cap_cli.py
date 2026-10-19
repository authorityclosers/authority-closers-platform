from argparse import Namespace

import pytest

from ac_platform.conversation_intelligence.budget_cap_cli import (
    CommandError,
    validate_environment,
)
from ac_platform.http.conversation_execution_control import BudgetCapIntent


@pytest.mark.parametrize(
    ("environment", "configured", "allowed", "database", "message"),
    [
        ("production", "production", False, "set", "Production requires"),
        ("staging", "production", False, "set", "must match"),
        ("test", "test", False, "", "explicit AC_DATABASE_URL"),
        ("unknown", "", False, "set", "Unsupported environment"),
    ],
)
def test_budget_cli_environment_guard(
    monkeypatch, environment, configured, allowed, database, message
):
    monkeypatch.setenv("AC_ENVIRONMENT", configured)
    monkeypatch.setenv("AC_DATABASE_URL", database)
    with pytest.raises(CommandError, match=message):
        validate_environment(
            Namespace(
                environment=environment,
                allow_production=allowed,
                idempotency_key="budget-key",
            )
        )


def test_budget_intent_is_strict_and_bounded():
    # 19 Oct 2026 (owner, via the orchestrator): no ₹10,000 limit in code any more; the
    # ceiling is checked by the budget service. The intent only bounds the integer.
    value = BudgetCapIntent(
        expected_revision=0,
        new_cap_paise=1_500_000,
        reason="Raised by Rs 5,000 from Execution & budget",
    )
    assert value.new_cap_paise == 1_500_000
    for cap in (-1, 2_147_483_648):
        with pytest.raises(ValueError):
            BudgetCapIntent(expected_revision=0, new_cap_paise=cap, reason="out of range")
    with pytest.raises(ValueError):
        BudgetCapIntent(expected_revision=0, new_cap_paise="1000", reason="not an integer")
    with pytest.raises(ValueError):
        BudgetCapIntent(
            expected_revision=0,
            new_cap_paise=1_000,
            reason="ok",
            extra=True,
        )
