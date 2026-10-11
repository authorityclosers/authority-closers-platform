"""Internal aggregation of independent reviews; never an autonomous learner score.

Answer keys and generated fixture reports are not pipeline results. A review
must bind a staging recording/run and response digest before it is counted.
Semantic pillar, mistake and coaching judgments remain explicit review input.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any
from uuid import UUID

PILLARS = (
    "the_big_picture",
    "how_the_call_played_out",
    "what_worked_and_what_didnt",
    "moments_that_mattered",
    "your_skills_on_this_call",
    "where_the_deal_stands",
)
CRITERIA = (
    *PILLARS,
    "skills_states",
    "mistakes",
    "next_step",
    "outcome",
    "per_call_coaching",
    "speaker_roles",
)


def validate_review(review: dict[str, Any], call_id: str) -> dict[str, str]:
    if (
        review.get("schema") != "ac.sales-xray.synthetic-quality-review/1"
        or review.get("call_id") != call_id
        or review.get("environment") != "staging"
        or review.get("reference_basis") != "independent_answer_key"
        or not isinstance(review.get("reviewer_reference"), str)
        or not review["reviewer_reference"].strip()
    ):
        raise ValueError("A bound independent staging review is required.")
    for field in ("recording_id", "report_run_id"):
        if not isinstance(review.get(field), str):
            raise ValueError("Immutable staging run references are required.")
        UUID(review[field])
    for field in ("source_sha256", "response_sha256", "answer_key_sha256"):
        if not isinstance(review.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{64}", review[field]
        ):
            raise ValueError("Immutable review source references are required.")
    criteria = review.get("criteria")
    if not isinstance(criteria, dict) or set(criteria) - set(CRITERIA):
        raise ValueError("Unknown review criteria.")
    result = {}
    for criterion in CRITERIA:
        value = criteria.get(criterion, {})
        if not isinstance(value, dict):
            raise ValueError("Invalid review judgment.")
        verdict = value.get("verdict", "unreviewed")
        if verdict not in {"pass", "fail", "unreviewed"}:
            raise ValueError("Invalid review verdict.")
        if verdict != "unreviewed" and not (
            isinstance(value.get("evidence_reference"), str) and value["evidence_reference"].strip()
        ):
            raise ValueError("A reviewed judgment needs an inspectable evidence reference.")
        result[criterion] = verdict
    return result


def build_scorecard(
    rows: list[dict[str, Any]], reviews: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    identifiers = {row["call_id"] for row in rows}
    if len(identifiers) != len(rows) or set(reviews) - identifiers:
        raise ValueError("The exact selected call list and reviews must agree.")
    judgments = {call_id: validate_review(review, call_id) for call_id, review in reviews.items()}

    def aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
        result = {}
        for criterion in CRITERIA:
            counts = Counter(
                judgments.get(row["call_id"], {}).get(criterion, "unreviewed") for row in selected
            )
            compared = counts["pass"] + counts["fail"]
            result[criterion] = {
                "pass": counts["pass"],
                "fail": counts["fail"],
                "unreviewed": counts["unreviewed"],
                "reviewed": compared,
                "pass_rate": counts["pass"] / compared if compared else None,
            }
        return {
            "expected_calls": len(selected),
            "review_receipts": sum(row["call_id"] in reviews for row in selected),
            "criteria": result,
        }

    groups = {}
    for field in ("language_mix", "business_id"):
        groups[field] = {
            value: aggregate([row for row in rows if row[field] == value])
            for value in sorted({row[field] for row in rows})
        }
    return {
        "schema": "ac.sales-xray.internal-quality-scorecard/1",
        "official_score": False,
        "status": "review_receipts_available"
        if reviews
        else "awaiting_staging_reports_and_independent_review",
        "overall": aggregate(rows),
        "by_language": groups["language_mix"],
        "by_business": groups["business_id"],
        "calls": [
            {
                "call_id": row["call_id"],
                "language_mix": row["language_mix"],
                "business_id": row["business_id"],
                "audio_present": row.get("audio_present", False),
                "audio_manifest_status": row.get("audio_status"),
                "quality_review": "available" if row["call_id"] in reviews else "unavailable",
            }
            for row in rows
        ],
        "limitations": [
            "Review receipts are supplied artifacts; this tool does not verify live staging state.",
            "Missing reports and judgments stay unreviewed; they are never counted as passes.",
            "Audio presence and a manifest status do not certify exact playback timestamps.",
            "No provider calls, official scores or product-state changes are performed.",
        ],
    }
