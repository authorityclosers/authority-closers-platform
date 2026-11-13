"""Own disposable test templates once per session; migration subjects stay cold."""

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.database.conversation_harness import CURRENT_MODULE, template_session  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def postgres_template_session() -> Iterator[None]:
    with template_session(ROOT):
        yield


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    CURRENT_MODULE.set(Path(item.path))


# Scenarios worked out for the one-hour trial. The owner made the trial three hours on
# 13 Nov 2026 (limits.TRIAL_SECONDS, pinned in tests/unit/billing/test_trial.py and run
# for real by test_tenant_trial_composition). These files prove races, caps, replays and
# ledger vectors whose mechanics don't depend on the trial's size, so they keep the hour
# their numbers were derived for instead of re-deriving every vector.
ONE_HOUR_TRIAL_TESTS = (
    "tests/unit/billing/test_ledger.py",
    "tests/unit/http/test_conversation_learner_acquisition.py",
    "tests/database/test_billing_ledger_postgresql.py",
    "tests/database/test_billing_org_pool_postgresql.py",
    "tests/database/test_conversation_acquisition_postgresql.py",
    "tests/database/test_conversation_recording_duration_postgresql.py",
    "tests/database/test_conversation_submission_http_postgresql.py",
    "tests/database/test_sales_xray_organisation_tenant_postgresql.py",
    "tests/integration/test_c1_audited_minute_allowance_postgresql.py",
    "tests/integration/test_me_plan_usage_postgresql.py",
    "tests/integration/test_operations_http_postgresql.py",
    "tests/database/test_billing_settlement_postgresql.py",
    "tests/database/test_staff_refunds_postgresql.py",
    "tests/database/test_billing_refund_safety_postgresql.py",
)
ONE_HOUR = 3600


@pytest.fixture(autouse=True)
def one_hour_trial(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """The listed files' trial is the hour they were written for (see above)."""
    if not Path(request.node.path).as_posix().endswith(ONE_HOUR_TRIAL_TESTS):
        return
    from ac_platform.billing import trial
    from ac_platform.conversation_intelligence import (
        acquisition_usage,
        application,
        minute_grants,
    )
    from ac_platform.http import operations

    monkeypatch.setitem(trial._SECONDS, "v1", ONE_HOUR)
    for module in (acquisition_usage, application, minute_grants, operations):
        monkeypatch.setattr(module, "ALLOWANCE_SECONDS", ONE_HOUR)
    # A file that imported the allowance itself reads the hour too.
    if hasattr(request.module, "ALLOWANCE_SECONDS"):
        monkeypatch.setattr(request.module, "ALLOWANCE_SECONDS", ONE_HOUR)
