"""Adapt only the existing authorized, withheld, full-account report projection.

Source quotes establish inspectable evidence, not a psychological diagnosis or
correct-execution verdict. A finding must share evidence with exactly one skill
before we associate its practice/mission with that skill. Ambiguity stays unknown.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ac_platform.coaching.contracts import CallHistory, Mission, Moment, Practice, SkillObservation
from ac_platform.conversation_intelligence.sensitive_segments import WITHHELD_MARKER

SKILLS = frozenset(
    {
        "human_connection_trust",
        "discovery_deep_understanding",
        "qualification",
        "problem_impact_desire",
        "solution_relevance_presentation",
        "certainty_objection_intelligence",
        "closing_decision_management",
        "communication_tonality",
    }
)


def _refs(value: Any) -> set[tuple[str, str, int, int]]:
    if not isinstance(value, list):
        return set()
    result = set()
    for ref in value:
        if (
            isinstance(ref, dict)
            and isinstance(ref.get("segment_id"), str)
            and isinstance(ref.get("quote"), str)
            and ref["quote"].strip()
            and WITHHELD_MARKER not in ref["quote"]
            and type(ref.get("start_ms")) is int
            and type(ref.get("end_ms")) is int
            and 0 <= ref["start_ms"] < ref["end_ms"]
        ):
            result.add((ref["segment_id"], ref["quote"], ref["start_ms"], ref["end_ms"]))
    return result


def _text(value: Any, maximum: int) -> str | None:
    return (
        value
        if (
            isinstance(value, str)
            and 0 < len(value.strip()) <= maximum
            and WITHHELD_MARKER not in value
        )
        else None
    )


def from_report(
    envelope: dict[str, Any],
    *,
    submission_id: UUID,
    created_at: datetime,
    comparison_key: str,
) -> CallHistory | None:
    """This is not an authorization seam; caller must use AcquisitionReports.report."""
    projection = envelope.get("report")
    if (
        not isinstance(projection, dict)
        or envelope.get("submission_id") != str(submission_id)
        or projection.get("access") != "claimed_account"
    ):
        return None
    report = projection.get("content")
    if not isinstance(report, dict):
        return None
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, list):
        return None
    overview = report.get("overview")
    improvements = report.get("improvements")
    proposed = overview.get("next_call_focus") if isinstance(overview, dict) else None
    practice = overview.get("practice") if isinstance(overview, dict) else None
    finding: dict[str, Any] | None = None
    if (
        isinstance(proposed, dict)
        and proposed.get("improvement_index") == 0
        and isinstance(improvements, list)
        and improvements
        and isinstance(improvements[0], dict)
    ):
        finding = improvements[0]
    finding_refs = _refs(finding.get("evidence")) if finding else set()
    candidates = [
        dim
        for dim in dimensions
        if isinstance(dim, dict)
        and dim.get("dimension_id") in SKILLS
        and dim.get("status") in {"observed", "partial"}
        and finding_refs.intersection(_refs(dim.get("evidence")))
    ]
    linked_id = candidates[0]["dimension_id"] if len(candidates) == 1 else None
    rows = []
    try:
        for dim in dimensions:
            if (
                not isinstance(dim, dict)
                or dim.get("dimension_id") not in SKILLS
                or dim.get("status") not in {"observed", "partial"}
                or not _text(dim.get("observation"), 4000)
                or not _text(dim.get("label"), 160)
            ):
                continue
            refs = _refs(dim.get("evidence"))
            if not refs:
                continue
            moments = tuple(
                Moment(
                    submission_id=submission_id,
                    recording_id=envelope["recording_id"],
                    source_sha256=envelope["source_sha256"],
                    transcript_revision=envelope["transcript_revision"],
                    created_at=created_at,
                    call_label=_text(envelope.get("source_label"), 256) or "Sales call",
                    segment_id=ref[0],
                    quote=ref[1],
                    start_ms=ref[2],
                    end_ms=ref[3],
                    observation=dim["observation"],
                )
                for ref in sorted(refs, key=lambda ref: (ref[2], ref[0]))[:8]
            )
            mission, drill, improvement, why = None, None, None, None
            if dim["dimension_id"] == linked_id and finding and proposed:
                behavior = _text(proposed.get("behavior"), 500)
                target = _text(proposed.get("target"), 500)
                if behavior and target and _text(finding.get("explanation"), 4000):
                    improvement = finding["explanation"]
                    details = (
                        overview.get("improvement_details", [])
                        if isinstance(overview, dict)
                        else []
                    )
                    detail = next(
                        (d for d in details if isinstance(d, dict) and d.get("finding_index") == 0),
                        {},
                    )
                    why = _text(detail.get("why_it_matters"), 700)
                    mission = Mission(
                        skill_id=linked_id,
                        behavior=behavior,
                        context=(
                            "When a comparable situation offers an opportunity for this behavior."
                        ),
                        done_when=target,
                        # A neutral reminder, never a clipped or invented source quote.
                        cue="Recall your one mission before the next relevant call.",
                        active_since=created_at,
                        origin_submission_id=submission_id,
                    )
                    if (
                        isinstance(practice, dict)
                        and practice.get("improvement_index") == 0
                        and _text(practice.get("instructions"), 1200)
                        and _text(practice.get("success_condition"), 500)
                    ):
                        drill = Practice(
                            exercise=practice["instructions"],
                            success_condition=practice["success_condition"],
                        )
            rows.append(
                SkillObservation(
                    skill_id=dim["dimension_id"],
                    label=dim["label"],
                    report_status=dim["status"],
                    observation=dim["observation"],
                    evidence=moments,
                    improvement=improvement,
                    why_it_matters=why,
                    mission=mission,
                    practice=drill,
                )
            )
        return CallHistory(
            submission_id=submission_id,
            source_sha256=envelope["source_sha256"],
            created_at=created_at,
            comparison_key=comparison_key,
            skills=tuple(rows),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        # Withheld or incompatible content must not create a fallback diagnosis.
        return None
