from __future__ import annotations

import pytest

from ac_platform.decisions.__main__ import evaluate
from ac_platform.decisions.core import (
    AC_TENANT,
    Example,
    ProbabilityModel,
    intervals,
    metrics,
    ranking,
    split,
    tenant_allowlist,
    validate,
)
from ac_platform.decisions.router import Answer, AnswerRouter


def row(i=0, label=0, day=1, label_day=None, tenant=AC_TENANT, features=None):
    return Example(
        tenant,
        f"lead-{i}",
        f"2026-10-{day:02}T10:00:00+00:00",
        f"2026-10-{label_day or day:02}T11:00:00+00:00",
        label,
        features or {"duration_seconds": 30.0 if label else 4.0},
        f"event-{i}",
    )


def test_refuse_foreign_tenant_even_if_other_rows_allowed():
    with pytest.raises(ValueError, match="non-owner"):
        validate([row(), row(1, tenant="foreign")], "call_classifier", tenant_allowlist())


def test_ea_requires_canonical_uuid_matching_owner_prefix():
    with pytest.raises(ValueError):
        tenant_allowlist("62562d4d-short")
    with pytest.raises(ValueError):
        tenant_allowlist(AC_TENANT)


def test_temporal_split_purges_labels_learned_later():
    train, test, purged = split(
        [row(0), row(1, label_day=20), row(2, day=20)], "2026-10-15T00:00:00+00:00"
    )
    assert len(train) == len(test) == purged == 1


@pytest.mark.parametrize(
    "bad",
    [
        row(features={"seller_score": 10}),
        row(features={"duration_seconds": float("nan")}),
        row(day=20, label_day=1),
        row(label=2),
    ],
)
def test_invalid_snapshots_refused(bad):
    with pytest.raises(ValueError):
        validate([bad], "call_classifier", tenant_allowlist())


def test_duplicate_events_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        validate([row(), row()], "call_classifier", tenant_allowlist())


def test_precision_recall_and_undefined_values():
    result = metrics([1, 1, 0, 0], [0.9, 0.1, 0.8, 0.1])
    assert result["precision"] == result["recall"] == 0.5
    assert metrics([0], [0.0])["recall"] is None
    assert metrics([1], [0.0])["precision"] is None


def test_cluster_intervals_repeatable_and_single_cluster_unknown():
    rows = [row(i, i % 2) for i in range(8)]
    assert intervals(rows, [r.label for r in rows]) == intervals(rows, [r.label for r in rows])
    assert intervals([row()], [0])["intervals"]["precision"] is None


def test_real_fit_and_no_test_label_training():
    train = [row(i, i % 2) for i in range(20)]
    model = ProbabilityModel("call_classifier").fit(train)
    assert model.predict({"duration_seconds": 30}) > model.predict({"duration_seconds": 4})
    test = [row(30 + i, i % 2, day=20) for i in range(10)]
    result, fitted = evaluate(train + test, "call_classifier", "2026-10-15T00:00:00+00:00")
    assert result["model"]["n"] == 10
    assert fitted.state() == model.state()
    assert set(result["ring_rules"]) == {"7", "8"}


def test_insufficient_training_never_claims_metrics():
    result, model = evaluate([row()], "junk", "2026-10-15T00:00:00+00:00")
    assert result["status"] == "needs_data" and model is None
    assert "model" not in result


def test_ranking_deduplicates_same_lead_hour():
    rows = [row(0, 1), row(1, 0)]
    duplicate = Example(
        rows[0].tenant,
        rows[0].lead,
        rows[0].at,
        rows[0].label_at,
        1,
        rows[0].features,
        "other-event",
    )
    result = ranking(rows + [duplicate], [0.9, 0.8, 0.7])
    assert result["selected"] == 2
    assert result["precision_at_k"] == 0.5


def test_router_approved_only_and_abstention():
    router = AnswerRouter(
        [
            Answer("price", "What is the price?", "Fictional price is 100.", "fixture-v1", True),
            Answer("secret", "Secret discount", "Never route this.", "draft", False),
        ]
    )
    assert router.route("What is the price?")["answer_key"] == "price"
    assert router.route("zzzzzzzz")["status"] == "abstain"
    assert router.route("Secret discount")["status"] == "abstain"


def test_json_artifact_roundtrip_predictions(tmp_path):
    from ac_platform.decisions.__main__ import private_json
    from ac_platform.decisions.suggest import load_model

    model = ProbabilityModel("call_classifier").fit([row(i, i % 2) for i in range(8)])
    path = tmp_path / "model.json"
    private_json(path, model.state())
    restored = load_model(path)
    assert restored.predict({"duration_seconds": 15}) == model.predict({"duration_seconds": 15})
    assert path.stat().st_mode & 0o777 == 0o600


def test_features_exclude_current_and_future_attempts_and_censor_junk():
    from ac_platform.decisions.features import Attempt, Lead, Stage, build_examples

    lead = Lead(AC_TENANT, "lead", "2026-10-01T00:00:00Z")
    attempts = [
        Attempt(
            AC_TENANT,
            "lead",
            str(i),
            f"2026-10-0{i + 1}T10:00:00Z",
            f"2026-10-0{i + 1}T10:01:00Z",
            60,
            0,
        )
        for i in range(3)
    ]
    stages = [Stage(AC_TENANT, "lead", "lost", "2026-10-04T00:00:00Z", "lost")]
    output = build_examples([lead], attempts, stages, "2026-10-10T00:00:00Z")
    assert output["next_best_lead"][0].features["attempts"] == 0
    assert output["next_best_lead"][2].features["failed_attempts"] == 2
    assert output["junk"][0].label == 1
    # Seven-day horizons not yet observed exclude both positive and negative examples.
    assert build_examples([lead], attempts, stages, "2026-10-05T00:00:00Z")["junk"] == []
    # Lost without three independently failed attempts must not become a dead-number label.
    one = build_examples([lead], attempts[:1], stages, "2026-10-10T00:00:00Z")
    assert one["junk"][0].label == 0


def test_unknown_connection_never_becomes_duration_derived_label():
    from ac_platform.decisions.features import Attempt, Lead, build_examples

    lead = Lead(AC_TENANT, "lead", "2026-10-01T00:00:00Z")
    attempt = Attempt(
        AC_TENANT, "lead", "a", "2026-10-01T10:00:00Z", "2026-10-01T10:01:00Z", 60, None
    )
    output = build_examples([lead], [attempt], [], "2026-10-10T00:00:00Z")
    assert output["call_classifier"] == output["next_best_lead"] == []


def test_cli_rejects_analytics_provenance_before_reading_data(tmp_path, monkeypatch):
    import json
    import sys

    from ac_platform.decisions.__main__ import main

    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"source_kind": "lake_analytics", "query_log": "log"}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "decisions",
            "junk",
            "--input",
            str(tmp_path / "absent"),
            "--cutoff",
            "2026-10-15T00:00:00Z",
            "--provenance",
            str(receipt),
            "--output",
            str(tmp_path / "out"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_prepare_refuses_foreign_scope_before_build(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys

    from ac_platform.decisions.prepare import main

    raw = tmp_path / "raw.json"
    raw.write_text(
        json.dumps(
            {
                "leads": [{"tenant": "foreign", "lead": "x", "created_at": "2026-10-01T00:00:00Z"}],
                "attempts": [],
                "stages": [],
            }
        )
    )
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "source_kind": "owner_crm",
                "query_log": "logged-read",
                "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "history_complete": True,
                "connection_label_source": "explicit_crm_outcome",
                "observed_until": "2026-10-29T00:00:00Z",
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prepare",
            "--extract",
            str(raw),
            "--receipt",
            str(receipt),
            "--output",
            str(tmp_path / "out"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


def test_paid_inventory_separates_jobs_calls_and_unknown_cost():
    from ac_platform.decisions.inventory import inventory

    def analysis(job, call, cost="1", status="succeeded", duration=60, language="hi"):
        return {
            "tenant": AC_TENANT,
            "call": call,
            "job": job,
            "at": "2026-10-01T10:00:00Z",
            "language": language,
            "duration_seconds": duration,
            "status": status,
            "cost_inr": cost,
        }

    rows = [
        analysis("a", "one"),
        analysis("b", "one"),
        analysis("c", "two", duration=None, language=None),
        analysis("d", "three", status="failed"),
        analysis("e", "four", cost=None),
    ]
    report = inventory(rows, tenant_allowlist())
    assert report["paid_successful_analyses"] == 3
    assert report["distinct_paid_success_calls"] == 2
    assert report["known_minutes"] == 1
    assert report["unknown_duration_calls"] == report["unknown_cost_jobs"] == 1
    assert report["known_cost_inr"] == "4"
    with pytest.raises(ValueError, match="duplicate job"):
        inventory(rows + rows[:1], tenant_allowlist())
