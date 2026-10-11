"""Adapt only the existing authorized, withheld, full-account report projection.

Source quotes establish inspectable evidence, not a psychological diagnosis or
correct-execution verdict. A unique evidence link associates a finding with a
skill. Older C5 findings without that link remain explicit call suggestions.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ac_platform.coaching.contracts import (
    CallHistory,
    Mission,
    Moment,
    Practice,
    SkillObservation,
    Strength,
)
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


def _moments(
    envelope: dict[str, Any],
    refs: set[tuple[str, str, int, int]],
    observation: str,
    submission_id: UUID,
    created_at: datetime,
) -> tuple[Moment, ...]:
    return tuple(
        Moment(
            submission_id=submission_id,
            recording_id=envelope["recording_id"],
            source_sha256=envelope["source_sha256"],
            transcript_revision=envelope["transcript_revision"],
            created_at=created_at,
            call_label=(
                _text(envelope.get("source_label"), 256)
                or _text(envelope.get("report", {}).get("content", {}).get("source_label"), 256)
                or "Sales call"
            ),
            segment_id=ref[0],
            quote=ref[1],
            start_ms=ref[2],
            end_ms=ref[3],
            observation=observation,
        )
        for ref in sorted(refs, key=lambda ref: (ref[2], ref[0]))[:8]
    )


def quoted_strength(
    report: dict[str, Any],
    envelope: dict[str, Any],
    submission_id: UUID,
    created_at: datetime,
    exclude: str | None = None,
) -> Strength | None:
    """The first retained "What worked" finding with its own quoted moments.

    `exclude` skips a strength already used as the call's focus.
    """
    findings = report.get("strengths")
    for finding in findings if isinstance(findings, list) else ():
        if not isinstance(finding, dict) or WITHHELD_MARKER in str(finding):
            continue
        title = _text(finding.get("title"), 240)
        text = _text(finding.get("explanation"), 4000)
        if not title or not text or title == exclude:
            continue
        try:
            moments = _moments(
                envelope, _refs(finding.get("evidence")), text, submission_id, created_at
            )
        except (KeyError, TypeError, ValueError):
            # Optional: a malformed strength is skipped, never the call.
            continue
        if moments:
            return Strength(title=title, explanation=text, evidence=moments[:2])
    return None


def _call_suggestion(
    report: dict[str, Any],
    envelope: dict[str, Any],
    submission_id: UUID,
    created_at: datetime,
) -> SkillObservation | None:
    """Use actual legacy findings; never guess an assessed skill from their prose.

    The primary improvement is preferred, then a missed opportunity, objection
    or closing finding. Each requires its own validated quotes/timestamps from
    the authorized report projection. Knowledge-base citations are not audio.
    """
    overview = report.get("overview")
    overview = overview if isinstance(overview, dict) else {}
    for section in (
        "improvements",
        "missed_opportunities",
        "objection_analysis",
        "closing_analysis",
    ):
        findings = report.get(section)
        if not isinstance(findings, list):
            continue
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            title = _text(finding.get("title"), 240)
            explanation = _text(finding.get("explanation"), 4000)
            refs = _refs(finding.get("evidence"))
            if not title or not explanation or not refs:
                continue
            proposed = overview.get("next_call_focus")
            proposed = (
                proposed
                if section == "improvements"
                and isinstance(proposed, dict)
                and type(proposed.get("improvement_index")) is int
                and proposed["improvement_index"] == index
                else {}
            )
            details = overview.get("improvement_details")
            detail = (
                next(
                    (
                        row
                        for row in details
                        if isinstance(row, dict) and row.get("finding_index") == index
                    ),
                    {},
                )
                if section == "improvements" and isinstance(details, list)
                else {}
            )
            behavior = _text(proposed.get("behavior"), 500) or _text(
                detail.get("replacement_behavior"), 500
            )
            mission = Mission(
                skill_id="report_next_step",
                behavior=behavior or f"Try the report's suggested change: {explanation}",
                context=f"When a comparable moment relates to: {title}",
                done_when=_text(proposed.get("target"), 500)
                or (
                    "Try one alternative response in that situation on your next call; "
                    "keep the moment for review. An attempt does not establish mastery."
                ),
                cue="Recall your one mission before the next relevant call.",
                active_since=created_at,
                origin_submission_id=submission_id,
            )
            practice = overview.get("practice")
            drill = None
            if (
                section == "improvements"
                and isinstance(practice, dict)
                and practice.get("improvement_index") == index
                and _text(practice.get("instructions"), 1200)
                and _text(practice.get("success_condition"), 500)
            ):
                drill = Practice(
                    exercise=practice["instructions"],
                    success_condition=practice["success_condition"],
                )
            return SkillObservation(
                skill_id="report_next_step",
                label=title,
                report_status="observed",
                observation=explanation,
                evidence=_moments(envelope, refs, explanation, submission_id, created_at),
                improvement=explanation,
                why_it_matters=_text(detail.get("why_it_matters"), 700),
                mission=mission,
                practice=drill,
                basis="report_suggestion",
            )
    return None


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
    dimensions = dimensions if isinstance(dimensions, list) else []
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
            moments = _moments(envelope, refs, dim["observation"], submission_id, created_at)
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
        if not any(row.mission is not None for row in rows):
            suggestion = _call_suggestion(report, envelope, submission_id, created_at)
            if suggestion is not None:
                rows.append(suggestion)
        return CallHistory(
            submission_id=submission_id,
            source_sha256=envelope["source_sha256"],
            created_at=created_at,
            comparison_key=comparison_key,
            skills=tuple(rows),
            strength=quoted_strength(report, envelope, submission_id, created_at),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        # Withheld or incompatible content must not create a fallback diagnosis.
        return None
