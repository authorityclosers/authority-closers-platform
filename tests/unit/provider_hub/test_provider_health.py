"""Providers hub, slice 4: each provider's spend and failures in plain words (owner, 20 Oct
2026). Pure: ledger rows and failure groups are fed in, nothing is read."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from ac_platform.ai_spend.ledger import SpendRow
from ac_platform.ai_spend.policy import defaults
from ac_platform.provider_hub.health import health_view, plain_words

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)  # 17:30 in India


def _row(provider: str, day: date, inr: str, requests: int = 1) -> SpendRow:
    return SpendRow(
        feature="call_facts",
        trigger="person",
        day=day,
        provider=provider,
        model="model-a",
        requests=requests,
        input_tokens=0,
        output_tokens=0,
        audio_ms=0,
        inr=Decimal(inr),
        priced=True,
    )


def _failure(provider: str, status: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "provider": provider,
        "failures": 1,
        "failures_day": 0,
        "last_at": datetime(2026, 10, 18, 9, 0, tzinfo=UTC),
        "status": status,
        "category": None,
        "feature": "call_analysis",
        **extra,
    }


def _by_id(view: dict[str, Any]) -> dict[str, Any]:
    return {provider["id"]: provider for provider in view["providers"]}


def test_spend_splits_into_today_this_month_and_the_last_30_days() -> None:
    rows = [
        _row("gemini", date(2026, 10, 20), "1.50"),
        _row("gemini", date(2026, 10, 2), "2.25", requests=3),
        _row("gemini", date(2026, 9, 25), "4"),
        _row("gemini", date(2026, 9, 1), "9"),  # before the window and the month
        _row("sarvam", date(2026, 10, 19), "0.40"),
    ]
    view = health_view(rows, [], defaults("staging"), environment="staging", now=NOW)
    providers = _by_id(view)
    assert providers["gemini"]["spend"] == {
        "today_inr": 1.5,
        "month_inr": 3.75,
        "window_inr": 7.75,
        "requests": 5,
    }
    assert (providers["gemini"]["state"], providers["gemini"]["failures"]) == ("ok", None)
    assert providers["sarvam"]["spend"]["today_inr"] == 0.0
    assert view["month"] == {"spent_inr": 4.15, "cap_inr": defaults("staging")["monthly_cap_inr"]}
    assert (view["environment"], view["window_days"], view["failure_days"]) == ("staging", 30, 7)


def test_the_newest_failure_is_said_plainly_with_what_fixes_it() -> None:
    failures = [
        _failure(
            "gemini",
            "402",
            failures=3,
            failures_day=1,
            feature="call_data_fast",
            last_at=datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
        ),
        _failure("elevenlabs", None),
        _failure("some_other_gateway", "503"),
    ]
    rows = [_row("gemini", date(2026, 10, 20), "1")]
    view = health_view(rows, failures, defaults("staging"), environment="staging", now=NOW)
    providers = _by_id(view)
    gemini = providers["gemini"]
    assert gemini["state"] == "attention"
    assert (gemini["failures"]["last_7_days"], gemini["failures"]["last_24_hours"]) == (3, 1)
    latest = gemini["failures"]["latest"]
    assert latest == {
        "at": "2026-10-20T11:00:00+00:00",
        "status": 402,
        "category": None,
        "feature": "call_data_fast",
        "feature_label": "Call data: fast pipeline",
        "words": latest["words"],
        "fix": "console",
    }
    assert "Top up" in latest["words"]
    # A failure days ago with no use since reads as idle, not as needing attention now.
    assert providers["elevenlabs"]["state"] == "idle"
    assert providers["elevenlabs"]["spend"] is None
    assert providers["elevenlabs"]["failures"]["latest"]["fix"] == "engineer"
    assert providers["some_other_gateway"]["failures"]["latest"]["fix"] == "wait"


@pytest.mark.parametrize(
    ("status", "category", "fix"),
    [
        (402, None, "console"),
        (None, "billing_configuration", "console"),
        (429, None, "console"),
        (401, None, "key"),
        (400, "key_invalid", "key"),
        (400, "credential_reported_exposed", "key"),
        (403, None, "console"),
        (400, "location_restriction", "console"),
        (404, None, "model"),
        (400, "model_or_endpoint_unavailable", "model"),
        (503, None, "wait"),
        (400, "structured_schema_rejected", "engineer"),
        (None, None, "engineer"),
    ],
)
def test_every_failure_says_what_fixes_it(
    status: int | None, category: str | None, fix: str
) -> None:
    words, said = plain_words(status, category)
    assert said == fix
    assert words.endswith(".") and "{" not in words


def test_a_status_that_is_not_three_digits_is_no_status() -> None:
    failures = [_failure("gemini", "40"), _failure("openai", "abc")]
    view = health_view([], failures, defaults("development"), environment="development", now=NOW)
    for provider in view["providers"]:
        assert provider["failures"]["latest"]["status"] is None
