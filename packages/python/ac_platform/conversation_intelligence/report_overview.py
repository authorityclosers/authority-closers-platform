"""Versioned qualitative fields for the owner-supplied fourteen-part template.

These are review proposals, not canonical outcomes, psychology, financial
forecasts or approved scores. Source normalization is supplied by reports.py.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ac_platform.conversation_intelligence.completion_limits import completion_ceiling

OVERVIEW_VERSION = "dipak-14-point-v1"
OVERVIEW_MARKER = "REPORT_FORMAT: dipak-14-point-v1"
TEMPLATE_SHA256 = "4fad19ce3234848c9f992190f9f498184bb8be6996664a9e7cb6dc133aa3a0eb"


def stage_completion_limit(
    stage: str, approved_maximum: int, *, provider: str = "", model: str = ""
) -> int:
    """Allocate a larger C5 response only within the exact approved output cap."""
    if stage not in {"C4", "C5"} or type(approved_maximum) is not int:
        raise ValueError("report_stage_limit_invalid")
    if not 256 <= approved_maximum <= completion_ceiling(provider, model, stage):
        raise ValueError("report_stage_limit_invalid")
    if approved_maximum > 4_000:
        return approved_maximum
    return min(3_200 if stage == "C5" else 1_400, approved_maximum)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OverviewEvidence(_Strict):
    segment_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=2_000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class SourceNote(_Strict):
    text: str = Field(min_length=1, max_length=1_200)
    evidence: list[OverviewEvidence] = Field(min_length=1, max_length=3)


class CallDiagnosis(SourceNote):
    text: str = Field(min_length=1, max_length=320)


class ObservedOutcome(SourceNote):
    kind: Literal["closed", "follow_up", "no_sale", "future_date", "disqualified", "unclear"]


class StrengthDetail(_Strict):
    finding_index: int = Field(ge=0, le=2)
    why_it_matters: str = Field(min_length=1, max_length=700)


class BusinessImpact(_Strict):
    # No historical or financial inputs are provided to the current C5 input.
    # Quantitative estimation belongs to a separately validated input contract.
    status: Literal["insufficient_data"]
    missing_inputs: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(
        min_length=1, max_length=6
    )


class ImprovementDetail(_Strict):
    finding_index: int = Field(ge=0, le=2)
    what_happened: SourceNote
    why_it_matters: str = Field(min_length=1, max_length=700)
    replacement_behavior: str = Field(min_length=1, max_length=1_200)
    business_impact: BusinessImpact


class GoldenMoment(_Strict):
    strength_index: int = Field(ge=0, le=2)
    evidence_index: int = Field(ge=0, le=7)
    why_effective: str = Field(min_length=1, max_length=700)


class MissedDetail(_Strict):
    finding_index: int = Field(ge=0, le=9)
    prospect_signal: SourceNote
    closer_response: SourceNote
    follow_up: str = Field(min_length=1, max_length=1_200)
    potential_impact: str = Field(min_length=1, max_length=700)


class ProspectInterpretation(_Strict):
    source: SourceNote
    possible_concern: str = Field(min_length=1, max_length=700)
    interpretation_kind: Literal["inference"]


class RewatchMoment(SourceNote):
    purpose: Literal["must_watch", "watch", "repeat"]
    evidence: list[OverviewEvidence] = Field(min_length=1, max_length=1)


class ConversationChange(_Strict):
    before: SourceNote
    change: SourceNote
    after: SourceNote
    possible_effect: str = Field(min_length=1, max_length=1_200)
    interpretation_kind: Literal["inference"]


class NextCallFocus(_Strict):
    improvement_index: int = Field(ge=0, le=0)
    behavior: str = Field(min_length=1, max_length=500)
    target: str = Field(min_length=1, max_length=500)


class PracticeDrill(_Strict):
    improvement_index: int = Field(ge=0, le=0)
    instructions: str = Field(min_length=1, max_length=1_200)
    success_condition: str = Field(min_length=1, max_length=500)


class FinalAssessment(_Strict):
    repeat: str = Field(min_length=1, max_length=500)
    fix_first: str = Field(min_length=1, max_length=500)
    next_focus: str = Field(min_length=1, max_length=500)
    assessment: str = Field(min_length=1, max_length=1_200)


class DetailedOverview(_Strict):
    version: Literal["dipak-14-point-v1"]
    diagnosis: CallDiagnosis | None
    outcome: ObservedOutcome | None
    strength_details: list[StrengthDetail] = Field(max_length=3)
    improvement_details: list[ImprovementDetail] = Field(max_length=3)
    golden_moments: list[GoldenMoment] = Field(max_length=3)
    missed_details: list[MissedDetail] = Field(max_length=10)
    prospect_interpretations: list[ProspectInterpretation] = Field(max_length=3)
    rewatch: list[RewatchMoment] = Field(max_length=3)
    conversation_change: ConversationChange | None
    ethics_notes: list[SourceNote] = Field(max_length=3)
    next_call_focus: NextCallFocus | None
    practice: PracticeDrill | None
    # Multi-call history is not in the single-call judge's input. Never infer it.
    progress: None
    final_assessment: FinalAssessment


def normalize_overview(
    payload: Any,
    *,
    findings: Mapping[str, Any],
    normalize_evidence: Callable[[Any], dict[str, Any]],
) -> DetailedOverview:
    """Resolve every quote through native source validation and check references."""

    def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {
                key: [normalize_evidence(item) for item in child]
                if key == "evidence" and isinstance(child, list)
                else walk(child)
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    parsed = DetailedOverview.model_validate(walk(payload))
    for field, collection in (
        (parsed.strength_details, "strengths"),
        (parsed.improvement_details, "improvements"),
        (parsed.missed_details, "missed_opportunities"),
    ):
        indices = [item.finding_index for item in field]
        if len(indices) != len(set(indices)) or any(
            index >= len(findings[collection]) for index in indices
        ):
            raise ValueError("overview_finding_reference_invalid")
        if collection in {"strengths", "improvements"} and set(indices) != set(
            range(len(findings[collection]))
        ):
            raise ValueError("overview_finding_detail_missing")
    golden_refs = [(item.strength_index, item.evidence_index) for item in parsed.golden_moments]
    if len(golden_refs) != len(set(golden_refs)):
        raise ValueError("overview_golden_reference_duplicate")
    for strength_index, evidence_index in golden_refs:
        if strength_index >= len(findings["strengths"]) or evidence_index >= len(
            findings["strengths"][strength_index]["evidence"]
        ):
            raise ValueError("overview_golden_reference_invalid")
    if not findings["improvements"] and (parsed.next_call_focus or parsed.practice):
        raise ValueError("overview_focus_requires_improvement")
    if bool(parsed.next_call_focus) != bool(parsed.practice):
        raise ValueError("overview_focus_practice_mismatch")
    if findings["improvements"] and not parsed.next_call_focus:
        raise ValueError("overview_focus_required")
    clips = [
        (item.evidence[0].segment_id, item.evidence[0].start_ms, item.evidence[0].end_ms)
        for item in parsed.rewatch
    ]
    if len(clips) != len(set(clips)):
        raise ValueError("overview_rewatch_duplicate")
    if parsed.conversation_change:
        change = parsed.conversation_change
        before_end = max(item.end_ms for item in change.before.evidence)
        pivot_start = min(item.start_ms for item in change.change.evidence)
        pivot_end = max(item.end_ms for item in change.change.evidence)
        after_start = min(item.start_ms for item in change.after.evidence)
        if before_end > pivot_start or pivot_end > after_start:
            raise ValueError("overview_change_order_invalid")
    return parsed


OVERVIEW_INSTRUCTION = (
    " Follow the owner's fourteen-part overview template. Link existing report findings; "
    "do not invent or duplicate findings to fill slots. Separate what happened, why it matters "
    "and replacement behavior. Golden moments need useful source-backed strengths; fewer is valid. "
    "Prospect interpretations and causal effects are hypotheses, not observed psychology. "
    "Unsupported diagnosis, outcome or chronological before/change/after sequence is null. "
    "A follow-up window is not a booked appointment or closed sale. ONE focus and ONE drill "
    "link improvement 0 with an observable practice target. No conversion, lead-volume, financial "
    "or historical inputs are supplied: business impact is insufficient_data with named missing "
    "inputs; progress is null. No invented closer name, level or ethics verdict; ethics concerns "
    "are source-linked observations for human review. Omit server-derived source_label, "
    "source_sha256, transcript_revision and report_sections. Dimensions use only dimension_id, "
    "status and observation; the server supplies labels and principle citations. "
)

# Compact semantic contract in the judge input; the Pydantic model above is the
# validating boundary. Repeating the entire JSON Schema would waste bounded TPM.
OVERVIEW_FORMAT = {
    "version": OVERVIEW_VERSION,
    "diagnosis": "{text: one sentence <=320 characters, evidence}|null",
    "outcome": (
        "{kind: closed|follow_up|no_sale|future_date|disqualified|unclear, text, evidence}|null"
    ),
    "strength_details": "[{finding_index, why_it_matters}] for each strength",
    "improvement_details": (
        "[{finding_index, what_happened: {text,evidence}, why_it_matters, "
        "replacement_behavior, business_impact: {status: insufficient_data, "
        "missing_inputs: [text]}}] for each improvement"
    ),
    "golden_moments": "[{strength_index,evidence_index,why_effective}], at most 3",
    "missed_details": (
        "[{finding_index,prospect_signal:{text,evidence},closer_response:{text,evidence},"
        "follow_up,potential_impact}]"
    ),
    "prospect_interpretations": (
        "[{source:{text,evidence},possible_concern,interpretation_kind:inference}], at most 3"
    ),
    "rewatch": (
        "[{text,purpose:must_watch|watch|repeat,evidence:[one exact source span]}], at most 3"
    ),
    "conversation_change": (
        "{before:{text,evidence},change:{text,evidence},after:{text,evidence},"
        "possible_effect,interpretation_kind:inference}|null; strictly chronological source spans"
    ),
    "ethics_notes": "[{text,evidence}], at most 3; observations only",
    "next_call_focus": "{improvement_index:0,behavior,target}|null if no improvement",
    "practice": "{improvement_index:0,instructions,success_condition}|null if no improvement",
    "progress": None,
    "final_assessment": "{repeat,fix_first,next_focus,assessment:2-4 sentences}",
}
