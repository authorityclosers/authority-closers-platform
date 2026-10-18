"""Cost and usage across environments (owner order, 19 Oct 2026).

List-price pricing from the repo price sheet, tests kept apart from real calls,
copied rows counted once upstream, the store read without raising, and the
collector's export SQL kept read-only and free of call content.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest

from ac_platform.conversation_intelligence import cost_metrics
from ac_platform.conversation_intelligence.application import ConversationDenied, ConversationError
from ac_platform.conversation_intelligence.cost_metrics import (
    AdminCostMetrics,
    Scope,
    build_metrics,
    dedupe,
    parse_export,
    price,
    read_store,
    version_id,
)

NOW = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
OPS = UUID("f5386fc3-033d-4e75-a333-7774381cb4d5")
EXPORT_SQL = Path(__file__).resolve().parents[3] / "infra" / "metrics" / "usage-metrics-export.sql"


def _at(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


def _call(
    call_id: str, *, kind: str = "real", hours_ago: float = 5, **extra: Any
) -> dict[str, Any]:
    return {
        "id": call_id,
        "company": "co-1",
        "at": _at(hours_ago),
        "kind": kind,
        "audio_ms": 600_000,
        "billed_s": 600,
        "delivered_at": _at(hours_ago - 0.05),
        "prompt": "coaching-v5",
        "facts": "facts-v2",
        "report_model": "gemini-3.8-flash",
        "transcription_model": "scribe_v2",
        "gold": {"agree": 0, "partly": 0, "disagree": 0},
        **extra,
    }


def _steps(call_id: str, *, hours_ago: float = 5) -> list[dict[str, Any]]:
    gemini = {"promptTokenCount": 1000, "candidatesTokenCount": 200, "totalTokenCount": 1200}
    return [
        {
            "call": call_id,
            "company": "co-1",
            "stage": "C2",
            "status": "succeeded",
            "attempts": 1,
            "provider": "elevenlabs",
            "model": "scribe_v2",
            "usage": {},
            "audio_ms": 600_000,
            "provider_ms": 20_000,
            "at": _at(hours_ago),
        },
        {
            "call": call_id,
            "company": "co-1",
            "stage": "C4",
            "status": "succeeded",
            "attempts": 1,
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "usage": gemini,
            "audio_ms": None,
            "provider_ms": 7_000,
            "at": _at(hours_ago - 0.01),
        },
        {
            "call": call_id,
            "company": "co-1",
            "stage": "C5",
            "status": "succeeded",
            "attempts": 2,
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "usage": gemini,
            "audio_ms": None,
            "provider_ms": 30_000,
            "at": _at(hours_ago - 0.02),
        },
    ]


def _document(environment: str = "staging", **overrides: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema": cost_metrics.SCHEMA,
        "environment": environment,
        "generated_at": _at(0.1),
        "window_days": 120,
        "migration": "20261018_0096",
        "companies": [{"id": "co-1", "name": "Wise Life", "kind": "organisation"}],
        "calls": [_call("call-real"), _call("call-canary", kind="canary", hours_ago=3)],
        "steps": _steps("call-real") + _steps("call-canary", hours_ago=3),
        "local_steps": [],
        "pointer_reviews": [
            {
                "call": "call-real",
                "company": "co-1",
                "model": "gemini-3.8-flash",
                "input_tokens": 1000,
                "output_tokens": 200,
                "by": "timer",
                "at": _at(4),
            }
        ],
        "synthetic_calls": [],
        "holds": [
            {
                "day": "2026-10-18",
                "scope": "scope-s",
                "state": "uncertain",
                "ref": "provider-cost-reconciliation",
                "provider": "gemini",
                "kind": "canary",
                "n": 2,
                "held_paise": 4_400,
                "settled_paise": 0,
            },
            {
                "day": "2026-10-16",
                "scope": "scope-s",
                "state": "settled",
                "ref": "list-price-estimate",
                "provider": "elevenlabs",
                "kind": "real",
                "n": 1,
                "held_paise": 2_200,
                "settled_paise": 37,
            },
        ],
        "budgets": [{"scope": "scope-s", "cap_paise": 1_000_000}],
        "payments": [],
        "subscriptions": [],
    }
    document.update(overrides)
    return document


def _scope(**overrides: Any) -> Scope:
    values: dict[str, Any] = {"now": NOW, "days": 30, "environment": "all", "tests": False}
    values.update(overrides)
    return Scope(**values)


def test_steps_are_priced_from_the_price_sheet() -> None:
    # Scribe v2: $0.22 per hour at Rs 100/USD, ceiling paise: 10 min = Rs 3.667 -> 367 paise.
    assert price("elevenlabs", "scribe_v2", None, 600_000) == 367
    # Gemini 3.8 Flash: 1,000 in x $0.75/M + 200 out x $3.75/M = $0.0015 = 15 paise.
    tokens = {"promptTokenCount": 1000, "candidatesTokenCount": 200}
    assert price("gemini", "gemini-3.8-flash", tokens, 0) == 15
    assert price("gemini", "unknown-model", tokens, 0) is None

    export = parse_export("staging", _document())
    real = [step for step in export.steps if step.call == "call-real"]
    assert {step.stage: step.paise for step in real} == {"C2": 367, "C4": 15, "C5": 15, "PR": 15}


def test_tests_stay_apart_from_real_calls_unless_asked() -> None:
    exports = [parse_export("staging", _document())]
    real = build_metrics(exports, _scope())
    overview = real["overview"]
    assert overview["spend_window"] == 4.12  # 367 + 15 + 15 + 15 paise
    assert overview["tests_window"] == 3.97  # the canary's 367 + 15 + 15
    assert overview["test_runs"] == 1 and overview["calls"] == 1
    assert overview["audio_minutes"] == 10.0 and overview["per_minute"] == 0.412
    assert [row["id"] for row in real["calls"]["rows"]] == ["call-real"]

    with_tests = build_metrics(exports, _scope(tests=True))
    assert with_tests["overview"]["spend_window"] == 8.09
    assert {row["kind"] for row in with_tests["calls"]["rows"]} == {"real", "canary"}


def test_a_later_backfill_counts_on_the_day_the_call_was_transcribed() -> None:
    document = _document(
        calls=[_call("call-real", hours_ago=48)],
        steps=_steps("call-real", hours_ago=48),
    )
    document["pointer_reviews"][0]["at"] = _at(1)  # scored two days later
    overview = build_metrics([parse_export("staging", document)], _scope())["overview"]
    daily = {day["day"]: day for day in overview["daily"]}
    transcribed, scored = daily["2026-10-17"], daily["2026-10-19"]
    assert transcribed["per_minute"] == 0.412  # all four steps over its 10 minutes
    assert scored["spend"] == 0.15 and scored["per_minute"] is None
    assert overview["per_minute"] == 0.412
    assert overview["environments"][0]["per_minute"] == 0.412


def test_individuals_are_named_plainly() -> None:
    document = _document(
        companies=[{"id": "co-1", "name": "Authority Closers Public Learners", "kind": "personal"}]
    )
    result = build_metrics([parse_export("staging", document)], _scope())
    assert result["calls"]["rows"][0]["company"] == "Individuals (personal accounts)"


def test_a_call_shows_each_stage_its_billed_minutes_and_report_time() -> None:
    row = build_metrics([parse_export("staging", _document())], _scope())["calls"]["rows"][0]
    assert row["company"] == "Wise Life" and row["environment"] == "staging"
    assert row["stages"]["C2"]["rupees"] == 3.67
    assert row["stages"]["C5"] == {
        "input_tokens": 1000,
        "output_tokens": 200,
        "rupees": 0.15,
        "runs": 1,
        "failed": 0,
    }
    assert row["rupees"] == 4.12 and row["billed_minutes"] == 10.0
    assert row["report"] is True and row["report_ms"] == 180_000
    assert row["revenue"] is None and row["margin"] is None  # no paid plan


def test_copies_count_once_in_the_most_upstream_environment() -> None:
    staging = parse_export("staging", _document())
    copied = _document("development")
    copied["calls"].append(_call("dev-own", hours_ago=1))
    copied["steps"] = copied["steps"] + _steps("dev-own", hours_ago=1)
    copied["budgets"] = [
        {"scope": "scope-s", "cap_paise": 1_000_000},
        {"scope": "scope-d", "cap_paise": 500_000},
    ]
    copied["holds"] = copied["holds"] + [
        {
            "day": "2026-10-18",
            "scope": "scope-d",
            "state": "uncertain",
            "ref": "provider-cost-reconciliation",
            "provider": "gemini",
            "kind": "real",
            "n": 1,
            "held_paise": 2_200,
            "settled_paise": 0,
        }
    ]
    development = parse_export("development", copied)
    merged = dedupe([development, staging])
    assert [export.environment for export in merged] == ["staging", "development"]
    dev = merged[1]
    assert {step.call for step in dev.steps} == {"dev-own"}
    assert [call.id for call in dev.calls] == ["dev-own"]
    assert [row["scope"] for row in dev.budgets] == ["scope-d"]
    assert all(row["scope"] == "scope-d" for row in dev.holds)
    assert dev.copies_dropped > 0

    result = build_metrics(merged, _scope())
    by_env = {row["environment"]: row for row in result["overview"]["environments"]}
    assert by_env["staging"]["window"] == 4.12  # its call has a pointer review
    assert by_env["development"]["window"] == 3.97  # dev's own call only


def test_store_reports_problems_without_raising(tmp_path: Path) -> None:
    assert read_store(None) == ([], [{"environment": "all", "problem": "not_configured"}])
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "usage.json").write_text(json.dumps(_document()))
    (tmp_path / "production").mkdir()
    (tmp_path / "production" / "usage.json").write_text("{not json")
    (tmp_path / "development").mkdir()
    (tmp_path / "development" / "usage.json").write_text(json.dumps({"schema": "other/1"}))
    exports, problems = read_store(str(tmp_path))
    assert [export.environment for export in exports] == ["staging"]
    assert sorted((p["environment"], p["problem"]) for p in problems) == [
        ("development", "unknown_schema"),
        ("production", "unreadable"),
    ]


def test_money_health_shows_open_holds_and_why() -> None:
    money = build_metrics([parse_export("staging", _document())], _scope())["money"]
    staging = money["environments"][0]
    assert staging["open"] == 2 and staging["open_rupees"] == 44.0
    assert staging["settled"] == 1 and staging["settled_rupees"] == 0.37
    assert staging["cap"] == 10_000.0 and staging["cap_share"] == 0.004
    assert staging["by_reason"] == [
        {
            "ref": "provider-cost-reconciliation",
            "label": "Waiting for cost settlement",
            "n": 2,
            "rupees": 44.0,
        }
    ]
    assert staging["by_kind"] == {"canary": 2}
    assert "one-time script" in money["finding"]


def test_pipelines_compare_versions_with_gold_agreement() -> None:
    document = _document()
    document["calls"].append(
        _call("call-v6", prompt="coaching-v6", gold={"agree": 3, "partly": 2, "disagree": 1})
    )
    document["steps"] = document["steps"] + _steps("call-v6", hours_ago=2)
    rows = build_metrics([parse_export("staging", document)], _scope())["pipelines"]
    by_prompt = {row["prompt"]: row for row in rows}
    v6, v5 = by_prompt["coaching-v6"], by_prompt["coaching-v5"]
    assert v6["gold"] == {"reviewed": 6, "agree": 3, "partly": 2, "disagree": 1, "agreement": 0.667}
    assert v5["calls"] == 1 and v5["test_runs"] == 1  # the canary is counted as a test run
    assert v5["stage_ms"] == {"C2": 20_000, "C4": 7_000, "C5": 30_000}
    assert v5["retry_rate"] == 0.25 and v5["failure_rate"] == 0.0  # C2, C4, C5 (2 tries), PR
    assert v6["id"] == version_id(
        ("coaching-v6", "facts-v2", "gemini-3.8-flash", "scribe_v2", None)
    )


def test_revenue_counts_live_money_against_cost() -> None:
    document = _document(
        payments=[
            {
                "company": "co-1",
                "day": "2026-10-18",
                "kind": "subscription.charged",
                "mode": "live",
                "currency": "INR",
                "n": 1,
                "amount_minor": 99_900,
            },
            {
                "company": "co-1",
                "day": "2026-10-18",
                "kind": "payment.captured",
                "mode": "test",
                "currency": "INR",
                "n": 1,
                "amount_minor": 50_000,
            },
            {
                "company": "co-1",
                "day": "2026-10-18",
                "kind": "refund.processed",
                "mode": "live",
                "currency": "INR",
                "n": 1,
                "amount_minor": 9_900,
            },
        ],
        subscriptions=[
            {
                "company": "co-1",
                "plan": "Team",
                "interval": "monthly",
                "seats": 3,
                "included_minutes": 600,
                "amount_minor": 99_900,
                "currency": "INR",
                "mode": "live",
                "at": _at(48),
            }
        ],
    )
    result = build_metrics([parse_export("production", document)], _scope())
    row = result["revenue"]["rows"][0]
    assert row["company"] == "Wise Life" and row["plan"]["name"] == "Team"
    assert row["revenue"] == 900.0 and row["test_revenue"] == 500.0
    assert row["cost"] == 4.12 and row["margin"] == 895.88
    assert row["billed_minutes"] == 10.0 and row["cost_per_billed_minute"] == 0.41
    assert result["revenue"]["totals"]["production"]["margin"] == 895.88
    call = result["calls"]["rows"][0]
    assert call["revenue"] == 16.65 and call["margin"] == 12.53  # Rs 999 / 600 min x 10 min


async def test_summary_admits_only_operations_and_bounds_filters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    application = SimpleNamespace(database=None, clock=lambda: NOW)
    service = AdminCostMetrics(
        application,  # type: ignore[arg-type]
        OPS,
        store_root=str(tmp_path),
        here="staging",
    )
    with pytest.raises(ConversationDenied):
        await service.summary(SimpleNamespace(tenant_id=UUID(int=1)))  # type: ignore[arg-type]

    class _Admin:
        def __init__(self, _application: object) -> None:
            pass

        async def admit(self, _actor: object) -> None:
            return None

    monkeypatch.setattr(cost_metrics, "ConversationProviderAdmin", _Admin)
    actor = SimpleNamespace(tenant_id=OPS)
    for days in (0, 121):
        with pytest.raises(ConversationError):
            await service.summary(actor, days=days)  # type: ignore[arg-type]
    with pytest.raises(ConversationError):
        await service.summary(actor, environment="laptop")  # type: ignore[arg-type]
    (tmp_path / "staging").mkdir()
    (tmp_path / "staging" / "usage.json").write_text(json.dumps(_document()))
    result = await service.summary(actor, days=30)  # type: ignore[arg-type]
    assert result["available"] == ["staging"] and result["problems"] == []
    assert result["here"] == "staging"
    assert AdminCostMetrics(application, OPS, store_root=None, here="test").here is None  # type: ignore[arg-type]
    assert result["sources"][0]["stale"] is False


def test_export_sql_is_one_read_only_statement_without_call_content() -> None:
    sql = EXPORT_SQL.read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    assert body.strip().endswith(";") and body.count(";") == 1
    assert not re.search(
        r"\b(insert|update|delete|truncate|alter|create|drop|grant|copy)\b", body, re.IGNORECASE
    )
    # Content never leaves an environment: no transcript, report, prompt or person columns,
    # and checkpoint/plan/receipt JSON is read only through named numeric or label keys.
    for word in (
        r"transcripts?",
        r"emails?",
        r"phone",
        r"display_name",
        r"payload_sha256",
        r"prompt_sha256",
        r"details",
        r"data\s*->",
    ):
        assert not re.search(rf"\b{word}\b", body), word
    assert re.findall(r"intent ->> '(\w+)'", body) == ["duration_ms", "duration_ms"]
    assert re.findall(r"payload ->> '(\w+)'", body) == [
        "media_duration_ms",
        "media_duration_ms",
        "verdict",
        "verdict",
        "verdict",
    ]
