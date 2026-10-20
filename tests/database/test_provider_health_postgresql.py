"""Providers hub health on PostgreSQL: a provider's failures and spend from the pipelines' own
rows (owner, 20 Oct 2026). Disposable loopback PostgreSQL, fictional rows only; the text model
is a local fake (no network, no key)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

from ac_platform.ai_spend import policy
from ac_platform.provider_hub import health
from tests.database.conversation_harness import conversation_harness
from tests.database.test_call_data_postgresql import FakeModel, _call, _process

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def postgres_harness() -> Iterator[Engine]:
    yield from conversation_harness(ROOT)


def test_a_refused_run_then_a_paid_one_show_on_the_provider(postgres_harness: Engine) -> None:
    seeded = _call(postgres_harness, lead_name=None)
    refused = _process(postgres_harness, seeded, FakeModel(failure="provider_http_402"))
    assert refused["outcome"] == "failed:provider_http_402"
    assert _process(postgres_harness, seeded, FakeModel())["outcome"] == "succeeded"

    with postgres_harness.connect() as connection:
        view = health.read(connection, "staging", datetime.now(UTC))
    gemini = next(provider for provider in view["providers"] if provider["id"] == "gemini")
    assert gemini["state"] == "attention"
    assert (gemini["failures"]["last_7_days"], gemini["failures"]["last_24_hours"]) == (1, 1)
    latest = gemini["failures"]["latest"]
    assert (latest["status"], latest["feature"], latest["fix"]) == (
        402,
        "call_data_fast",
        "console",
    )
    assert gemini["spend"]["requests"] >= 2  # the refused run and the paid one
    assert gemini["spend"]["today_inr"] > 0
    assert gemini["spend"]["today_inr"] == gemini["spend"]["month_inr"]
    assert view["month"]["cap_inr"] == policy.defaults("staging")["monthly_cap_inr"]


def test_nothing_run_reads_as_no_providers(postgres_harness: Engine) -> None:
    with postgres_harness.connect() as connection:
        view = health.read(connection, "production", datetime.now(UTC))
    assert view["providers"] == []
    assert view["month"]["spent_inr"] == 0.0
