"""Analysis health, Phase 4: engine runs per pipeline and Review 2.0 agreement (pure parts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from ac_platform.conversation_intelligence.analysis_health_engine import (
    review_measures,
    run_health,
)
from ac_platform.conversation_intelligence.review_verdicts import DEFAULT_PIPELINES

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
SINCE = NOW - timedelta(days=2)
CALL_A, CALL_B = UUID(int=101), UUID(int=102)


def _run(identifier: int, pipeline: str, state: str, **values: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": UUID(int=identifier),
        "recording_id": CALL_A,
        "pipeline": pipeline,
        "pipeline_version": "fast-1",
        "state": state,
        "reason_code": None,
        "provider": None,
        "model_id": None,
        "cost_inr": None,
        "duration_ms": None,
        "supersedes_id": None,
        "created_at": NOW - timedelta(minutes=5),
    }
    base.update(values)
    return SimpleNamespace(**base)


def test_runs_end_succeeded_failed_or_skipped_and_running_rows_go_quiet() -> None:
    rows = [
        _run(1, "fast", "running", created_at=NOW - timedelta(hours=1)),
        _run(
            2,
            "fast",
            "succeeded",
            supersedes_id=UUID(int=1),
            provider="gemini",
            model_id="flash",
            cost_inr=Decimal("0.4200"),
            duration_ms=9000,
        ),
        _run(3, "fast", "running", recording_id=CALL_B, created_at=NOW - timedelta(days=1)),
        _run(
            4,
            "fast",
            "failed",
            recording_id=CALL_B,
            supersedes_id=UUID(int=3),
            reason_code="provider_timeout",
            provider="gemini",
            model_id="flash",
            cost_inr=Decimal("0.0800"),
            created_at=NOW - timedelta(days=1),
        ),
        _run(5, "fast", "skipped", reason_code="Too long: 3 hours of audio"),
        _run(
            6,
            "fast",
            "succeeded",
            pipeline_version="fast-2",
            duration_ms=3000,
            created_at=NOW - timedelta(minutes=1),
        ),
        # Deep: one still going, one silent for two hours.
        _run(7, "deep", "running", pipeline_version="deep-1"),
        _run(8, "deep", "running", pipeline_version="deep-1", created_at=NOW - timedelta(hours=2)),
    ]
    view = run_health(rows, now=NOW, since=SINCE)
    fast, deep = view["pipelines"]
    assert fast["pipeline"] == "fast" and deep["pipeline"] == "deep"
    assert (fast["runs"], fast["succeeded"], fast["failed"], fast["skipped"]) == (4, 2, 1, 1)
    assert fast["success_share"] == 0.667  # skips are not attempts that could fail
    assert fast["calls"] == 1
    assert fast["time"] == {"count": 2, "p50_ms": 6000, "p90_ms": 9000}
    assert fast["cost_inr"] == 0.5 and fast["cost_per_run_inr"] == 0.17
    # Free text never shows: an unrecognised reason reads "withheld".
    assert fast["reasons"] == [
        {"state": "failed", "code": "provider_timeout", "runs": 1},
        {"state": "skipped", "code": "withheld", "runs": 1},
    ]
    assert fast["models"] == [{"provider": "gemini", "model": "flash", "runs": 2}]
    assert fast["version"] == "fast-2" and fast["running"] == fast["quiet"] == 0
    assert (deep["runs"], deep["running"], deep["quiet"]) == (0, 1, 1)
    assert deep["success_share"] is None and deep["cost_per_run_inr"] is None
    assert view["quiet"] == [
        {
            "run_id": str(UUID(int=8)),
            "recording_id": str(CALL_A),
            "pipeline": "deep",
            "started_at": (NOW - timedelta(hours=2)).isoformat(),
        }
    ]
    assert [(row["pipeline"], row["version"], row["runs"]) for row in view["versions"]] == [
        ("fast", "fast-2", 1),
        ("fast", "fast-1", 3),
    ]
    # Every date the window touches, so the chart adds up to the totals.
    assert [day["day"] for day in view["daily"]] == ["2026-10-17", "2026-10-18", "2026-10-19"]
    assert view["daily"][1]["fast"] == {"succeeded": 0, "failed": 1}
    assert view["daily"][2]["fast"] == {"succeeded": 2, "failed": 0}
    assert view["daily"][2]["deep"] == {"succeeded": 0, "failed": 0}


def _verdict(reviewer: int, ref: str, question: str, answer: Any, **values: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "pipeline_key": "analysis-sales",
        "recording_id": CALL_A,
        "reviewer_id": UUID(int=reviewer),
        "target_kind": "object",
        "target_ref": ref,
        "question_key": question,
        "ai_sha256": "a" * 64,
        "answer": answer,
    }
    base.update(values)
    return SimpleNamespace(**base)


def test_review_measures_right_share_by_type_version_and_reviewer_agreement() -> None:
    price, budget = str(UUID(int=11)), str(UUID(int=12))
    objects = {
        UUID(int=11): SimpleNamespace(
            type_key="buyer.objection", pipeline="fast", pipeline_version="fast-2"
        ),
        UUID(int=12): SimpleNamespace(
            type_key="buyer.budget", pipeline="deep", pipeline_version="deep-1"
        ),
    }
    verdicts = [
        # Both reviewers say the objection is right: they agree.
        _verdict(1, price, "correct", {"value": "correct"}),
        _verdict(2, price, "correct", {"value": "correct"}),
        # They split on the budget.
        _verdict(1, budget, "correct", {"value": "wrong"}),
        _verdict(2, budget, "correct", {"value": "correct"}),
        _verdict(1, budget, "fix", {"text": "Budget was 40 lakh"}),
        # "Unsure" is an answer, not a vote either way.
        _verdict(2, str(UUID(int=13)), "correct", {"value": "unsure"}, recording_id=CALL_B),
        # Coaching, judged apart.
        _verdict(
            1,
            "run-1:better:2",
            "true",
            {"value": "true"},
            pipeline_key="coaching",
            target_kind="coaching",
        ),
        _verdict(
            1,
            "run-1:better:2",
            "useful",
            {"value": 4},
            pipeline_key="coaching",
            target_kind="coaching",
        ),
        _verdict(
            2,
            "run-1:focus",
            "useful",
            {"value": 2},
            pipeline_key="coaching",
            target_kind="coaching",
        ),
    ]
    names = {UUID(int=1): "Dipak"}
    view = review_measures(verdicts, DEFAULT_PIPELINES, objects, names)

    assert (view["answers"], view["calls"]) == (9, 2)
    pipelines = {item["key"]: item for item in view["pipelines"]}
    sales, coaching = pipelines["analysis-sales"], pipelines["coaching"]
    assert pipelines["analysis-psychology"]["answers"] == 0
    assert sales["key"] == "analysis-sales" and sales["title"] == "Analysis: sales"
    assert (sales["answers"], sales["items"], sales["reviewers"]) == (6, 3, 2)
    assert (sales["right"], sales["wrong"], sales["right_share"]) == (3, 1, 0.75)
    correct = next(item for item in sales["questions"] if item["key"] == "correct")
    assert correct["counts"] == {"correct": 3, "wrong": 1, "unsure": 1}
    fix = next(item for item in sales["questions"] if item["key"] == "fix")
    assert fix == {"key": "fix", "label": "What should it say?", "kind": "correct", "answers": 1}
    assert sales["agreement"] == {"compared": 2, "agreed": 1, "share": 0.5}
    assert sales["types"] == [
        {"type": "buyer.budget", "answers": 2, "right": 1, "wrong": 1, "right_share": 0.5},
        {"type": "buyer.objection", "answers": 2, "right": 2, "wrong": 0, "right_share": 1.0},
        {"type": "unknown", "answers": 1, "right": 0, "wrong": 0, "right_share": None},
    ]
    assert view["engine_versions"] == [
        {"pipeline": "deep", "version": "deep-1", "answers": 2, "right_share": 0.5},
        {"pipeline": "fast", "version": "fast-2", "answers": 2, "right_share": 1.0},
    ]

    assert coaching["right_share"] == 1.0
    assert coaching["types"][0]["type"] == "coaching.better"
    useful = next(item for item in coaching["questions"] if item["key"] == "useful")
    assert useful["average"] == 3.0 and useful["answers"] == 2
    assert coaching["agreement"] == {"compared": 0, "agreed": 0, "share": None}

    assert view["reviewers"] == [
        {"name": "Dipak", "answers": 5, "calls": 1},
        {"name": "Reviewer", "answers": 4, "calls": 2},
    ]


def test_review_measures_lists_every_active_pipeline_even_unanswered() -> None:
    view = review_measures([], DEFAULT_PIPELINES, {}, {})
    assert [item["key"] for item in view["pipelines"]] == list(DEFAULT_PIPELINES)
    assert all(item["answers"] == 0 for item in view["pipelines"])
    assert view["reviewers"] == [] and view["engine_versions"] == []
