"""Provider response schema for the detailed qualitative coaching report.

This module is intentionally independent from the report parser and provider
adapters.  It describes only the bounded JSON wire response sent by the
detailed C5 judge; source metadata, citations, labels and server-derived
evidence are added after the response is validated.
"""

from __future__ import annotations

from typing import Any

from ac_platform.conversation_intelligence.report_overview import OVERVIEW_VERSION

_REVIEW_STATUS = "draft_not_dipak_adjudicated"
_DIMENSION_IDS = (
    "human_connection_trust",
    "discovery_deep_understanding",
    "qualification",
    "problem_impact_desire",
    "solution_relevance_presentation",
    "certainty_objection_intelligence",
    "closing_decision_management",
    "communication_tonality",
)
_DIMENSION_STATES = (
    "observed",
    "insufficient_evidence",
    "not_applicable",
    "conflicted",
    "unknown",
)
_OUTCOME_KINDS = (
    "closed",
    "follow_up",
    "no_sale",
    "future_date",
    "disqualified",
    "unclear",
)
_REWATCH_PURPOSES = ("must_watch", "watch", "repeat")


def coaching_response_json_schema() -> dict[str, Any]:
    """Return a fresh Gemini-compatible schema for a detailed C5 response.

    The returned tree uses only the responseJsonSchema subset supported by the
    Gemini adapter.  Every object is closed.  Evidence references deliberately
    contain only a segment selector or a bounded source-text offset pair; the
    server resolves those references to quote and timing fields.
    """

    def obj(properties: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
            "required": list(required),
        }

    def arr(
        items: dict[str, Any], *, min_items: int | None = None, max_items: int | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "array", "items": items}
        if min_items is not None:
            result["minItems"] = min_items
        if max_items is not None:
            result["maxItems"] = max_items
        return result

    def integer(*, minimum: int | None = None, maximum: int | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {"type": "integer"}
        if minimum is not None:
            result["minimum"] = minimum
        if maximum is not None:
            result["maximum"] = maximum
        return result

    def nullable(ref: str) -> dict[str, Any]:
        return {"anyOf": [{"$ref": ref}, {"type": "null"}]}

    defs: dict[str, Any] = {
        "evidence_ref": {
            "anyOf": [
                obj({"segment_id": {"type": "string"}}, ("segment_id",)),
                obj(
                    {
                        "segment_id": {"type": "string"},
                        "quote_start": integer(minimum=0),
                        "quote_end": integer(minimum=1),
                    },
                    ("segment_id", "quote_start", "quote_end"),
                ),
            ]
        },
        "source_note": obj(
            {
                "text": {"type": "string"},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=3),
            },
            ("text", "evidence"),
        ),
        "finding": obj(
            {
                "title": {"type": "string"},
                "explanation": {"type": "string"},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=8),
            },
            ("title", "explanation", "evidence"),
        ),
        "business_impact": obj(
            {
                "status": {"type": "string", "enum": ["insufficient_data"]},
                "missing_inputs": arr({"type": "string"}, min_items=1, max_items=6),
            },
            ("status", "missing_inputs"),
        ),
        "dimension": obj(
            {
                "dimension_id": {"type": "string", "enum": list(_DIMENSION_IDS)},
                "status": {"type": "string", "enum": list(_DIMENSION_STATES)},
                "observation": {"type": "string"},
            },
            ("dimension_id", "status", "observation"),
        ),
        "call_diagnosis": obj(
            {
                "text": {"type": "string"},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=3),
            },
            ("text", "evidence"),
        ),
        "outcome": obj(
            {
                "kind": {"type": "string", "enum": list(_OUTCOME_KINDS)},
                "text": {"type": "string"},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=3),
            },
            ("kind", "text", "evidence"),
        ),
        "strength_detail": obj(
            {
                "finding_index": integer(minimum=0, maximum=2),
                "why_it_matters": {"type": "string"},
            },
            ("finding_index", "why_it_matters"),
        ),
        "improvement_detail": obj(
            {
                "finding_index": integer(minimum=0, maximum=2),
                "what_happened": {"$ref": "#/$defs/source_note"},
                "why_it_matters": {"type": "string"},
                "replacement_behavior": {"type": "string"},
                "business_impact": {"$ref": "#/$defs/business_impact"},
            },
            (
                "finding_index",
                "what_happened",
                "why_it_matters",
                "replacement_behavior",
                "business_impact",
            ),
        ),
        "golden_moment": obj(
            {
                "strength_index": integer(minimum=0, maximum=2),
                "evidence_index": integer(minimum=0, maximum=7),
                "why_effective": {"type": "string"},
            },
            ("strength_index", "evidence_index", "why_effective"),
        ),
        "missed_detail": obj(
            {
                "finding_index": integer(minimum=0, maximum=9),
                "prospect_signal": {"$ref": "#/$defs/source_note"},
                "closer_response": {"$ref": "#/$defs/source_note"},
                "follow_up": {"type": "string"},
                "potential_impact": {"type": "string"},
            },
            (
                "finding_index",
                "prospect_signal",
                "closer_response",
                "follow_up",
                "potential_impact",
            ),
        ),
        "prospect_interpretation": obj(
            {
                "source": {"$ref": "#/$defs/source_note"},
                "possible_concern": {"type": "string"},
                "interpretation_kind": {"type": "string", "enum": ["inference"]},
            },
            ("source", "possible_concern", "interpretation_kind"),
        ),
        "rewatch": obj(
            {
                "text": {"type": "string"},
                "purpose": {"type": "string", "enum": list(_REWATCH_PURPOSES)},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=1),
            },
            ("text", "purpose", "evidence"),
        ),
        "conversation_change": obj(
            {
                "before": {"$ref": "#/$defs/source_note"},
                "change": {"$ref": "#/$defs/source_note"},
                "after": {"$ref": "#/$defs/source_note"},
                "possible_effect": {"type": "string"},
                "interpretation_kind": {"type": "string", "enum": ["inference"]},
            },
            (
                "before",
                "change",
                "after",
                "possible_effect",
                "interpretation_kind",
            ),
        ),
        "next_call_focus": obj(
            {
                "improvement_index": integer(minimum=0, maximum=0),
                "behavior": {"type": "string"},
                "target": {"type": "string"},
            },
            ("improvement_index", "behavior", "target"),
        ),
        "practice": obj(
            {
                "improvement_index": integer(minimum=0, maximum=0),
                "instructions": {"type": "string"},
                "success_condition": {"type": "string"},
            },
            ("improvement_index", "instructions", "success_condition"),
        ),
        "final_assessment": obj(
            {
                "repeat": {"type": "string"},
                "fix_first": {"type": "string"},
                "next_focus": {"type": "string"},
                "assessment": {"type": "string"},
            },
            ("repeat", "fix_first", "next_focus", "assessment"),
        ),
    }
    defs["overview"] = obj(
        {
            "version": {"type": "string", "enum": [OVERVIEW_VERSION]},
            "diagnosis": nullable("#/$defs/call_diagnosis"),
            "outcome": nullable("#/$defs/outcome"),
            "business_impact": nullable("#/$defs/business_impact"),
            "strength_details": arr({"$ref": "#/$defs/strength_detail"}, max_items=3),
            "improvement_details": arr({"$ref": "#/$defs/improvement_detail"}, max_items=3),
            "golden_moments": arr({"$ref": "#/$defs/golden_moment"}, max_items=3),
            "missed_details": arr({"$ref": "#/$defs/missed_detail"}, max_items=10),
            "prospect_interpretations": arr(
                {"$ref": "#/$defs/prospect_interpretation"}, max_items=3
            ),
            "rewatch": arr({"$ref": "#/$defs/rewatch"}, max_items=3),
            "conversation_change": nullable("#/$defs/conversation_change"),
            "ethics_notes": arr({"$ref": "#/$defs/source_note"}, max_items=3),
            "next_call_focus": nullable("#/$defs/next_call_focus"),
            "practice": nullable("#/$defs/practice"),
            "progress": {"type": "null"},
            "final_assessment": {"$ref": "#/$defs/final_assessment"},
        },
        (
            "version",
            "diagnosis",
            "outcome",
            "strength_details",
            "improvement_details",
            "golden_moments",
            "missed_details",
            "prospect_interpretations",
            "rewatch",
            "conversation_change",
            "ethics_notes",
            "next_call_focus",
            "practice",
            "progress",
            "final_assessment",
        ),
    )
    return {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "strengths": arr({"$ref": "#/$defs/finding"}, max_items=3),
            "improvements": arr({"$ref": "#/$defs/finding"}, max_items=3),
            "missed_opportunities": arr({"$ref": "#/$defs/finding"}, max_items=10),
            "objection_analysis": arr({"$ref": "#/$defs/finding"}, max_items=8),
            "closing_analysis": arr({"$ref": "#/$defs/finding"}, max_items=8),
            "verdict": {"type": "string"},
            "review_status": {"type": "string", "enum": [_REVIEW_STATUS]},
            "dimensions": arr({"$ref": "#/$defs/dimension"}, min_items=8, max_items=8),
            "overview": {"$ref": "#/$defs/overview"},
        },
        "additionalProperties": False,
        "required": [
            "summary",
            "strengths",
            "improvements",
            "missed_opportunities",
            "objection_analysis",
            "closing_analysis",
            "verdict",
            "review_status",
            "dimensions",
            "overview",
        ],
        "$defs": defs,
    }


def coaching_generation_json_schema() -> dict[str, Any]:
    """Describe wire shape while leaving numeric/cardinality validation local."""
    local_bounds = {"minItems", "maxItems", "minimum", "maximum"}

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items() if key not in local_bounds}
        if isinstance(value, list):
            return [shape(item) for item in value]
        return value

    return shape(coaching_response_json_schema())  # type: ignore[no-any-return]


__all__ = ["coaching_response_json_schema", "coaching_generation_json_schema"]
