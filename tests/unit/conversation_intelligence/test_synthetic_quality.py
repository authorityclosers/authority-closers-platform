from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence.synthetic_quality import build_scorecard


def rows():
    return [
        {"call_id": "syn-a", "language_mix": "hi-en", "business_id": "syn-advisory"},
        {"call_id": "syn-b", "language_mix": "mr-en", "business_id": "syn-advisory"},
    ]


def review():
    return {
        "schema": "ac.sales-xray.synthetic-quality-review/1",
        "call_id": "syn-a",
        "environment": "staging",
        "reference_basis": "independent_answer_key",
        "reviewer_reference": "fictional-human-reviewer",
        "recording_id": str(uuid4()),
        "report_run_id": str(uuid4()),
        "source_sha256": "a" * 64,
        "response_sha256": "b" * 64,
        "answer_key_sha256": "c" * 64,
        "criteria": {
            "outcome": {"verdict": "pass", "evidence_reference": "overview.outcome + key.outcome"},
            "speaker_roles": {
                "verdict": "fail",
                "evidence_reference": "call_map.speakers + key.roles",
            },
        },
    }


def test_missing_outputs_do_not_produce_quality_passes():
    score = build_scorecard(rows(), {})
    assert score["official_score"] is False
    assert score["overall"]["review_receipts"] == 0
    assert all(item["pass_rate"] is None for item in score["overall"]["criteria"].values())
    assert score["by_language"]["hi-en"]["criteria"]["outcome"]["unreviewed"] == 1


def test_quality_denominators_distinguish_failed_unreviewed_and_unavailable():
    score = build_scorecard(rows(), {"syn-a": review()})
    outcome = score["overall"]["criteria"]["outcome"]
    assert outcome == {"pass": 1, "fail": 0, "unreviewed": 1, "reviewed": 1, "pass_rate": 1.0}
    assert score["overall"]["criteria"]["speaker_roles"]["pass_rate"] == 0
    assert score["by_language"]["mr-en"]["criteria"]["outcome"]["pass_rate"] is None


@pytest.mark.parametrize(
    "invalid", ["oracle_only", "no_evidence", "production", "wrong_call", "missing_run", "bad_run"]
)
def test_generated_answer_keys_or_unbound_judgments_are_not_pipeline_proof(invalid):
    receipt = review()
    if invalid == "oracle_only":
        receipt = {"synthetic": True, "report": {}, "per_call_coaching": {}}
    elif invalid == "no_evidence":
        receipt["criteria"]["outcome"].pop("evidence_reference")
    elif invalid == "production":
        receipt["environment"] = "production"
    elif invalid == "wrong_call":
        receipt["call_id"] = "syn-b"
    elif invalid == "missing_run":
        receipt.pop("report_run_id")
    else:
        receipt["recording_id"] = 123
    with pytest.raises(ValueError):
        build_scorecard(rows(), {"syn-a": receipt})
