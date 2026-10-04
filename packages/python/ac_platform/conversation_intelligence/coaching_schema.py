"""Provider response schema for the detailed qualitative coaching report.

This module is intentionally independent from the report parser and provider
adapters.  It describes only the bounded JSON wire response sent by the
detailed C5 judge; source metadata, citations, labels and server-derived
evidence are added after the response is validated.
"""

from __future__ import annotations

from copy import deepcopy
from sys import float_info
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
_COACHING_V4 = "coaching-v4"
_COACHING_V5 = "coaching-v5"
_COACHING_V6 = "coaching-v6"
_COACHING_V7 = "coaching-v7"


def _coaching_v7_schema() -> dict[str, Any]:
    from ac_platform.conversation_intelligence.call_map import (
        OBJECTION_KINDS_V1,
        SIGNAL_KINDS_V1,
        CallMap,
    )

    schema = coaching_response_json_schema(_COACHING_V6)
    defs = schema["$defs"]

    def wire(value: Any) -> Any:
        if isinstance(value, dict):
            result = {key: wire(item) for key, item in value.items() if key != "title"}
            if "$ref" in result:
                result["$ref"] = result["$ref"].replace("#/$defs/", "#/$defs/call_map_")
            if "const" in result:
                result["enum"] = [result.pop("const")]
            return result
        if isinstance(value, list):
            return [wire(item) for item in value]
        return value

    call_map = wire(CallMap.model_json_schema())
    defs.update({"call_map_" + key: item for key, item in call_map.pop("$defs").items()})
    defs["call_map_Signal"]["properties"]["kind"]["enum"] = [
        *SIGNAL_KINDS_V1["forward"],
        *SIGNAL_KINDS_V1["risk"],
    ]
    defs["call_map_Objection"]["properties"]["kind"]["enum"] = list(OBJECTION_KINDS_V1)
    defs["golden_moment"] = {
        "type": "object",
        "properties": {
            "evidence": {
                "type": "array",
                "items": {"$ref": "#/$defs/evidence_ref"},
                "minItems": 1,
                "maxItems": 2,
            },
            "why_effective": {"type": "string"},
        },
        "required": ["evidence", "why_effective"],
        "additionalProperties": False,
    }
    variants = defs["dimension"]["anyOf"]
    variants[0]["properties"]["evidence"]["minItems"] = 2
    variants.append(
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                **variants[0]["properties"],
                "status": {"type": "string", "enum": ["partial"]},
                "evidence": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/evidence_ref"},
                    "minItems": 1,
                    "maxItems": 1,
                },
            },
            "required": ["dimension_id", "status", "observation", "evidence"],
        }
    )
    # Only observed needs two segments; conflicted retains its independent rule.
    variants[0]["properties"]["status"]["enum"] = ["observed"]
    variants.append(
        {
            **variants[0],
            "properties": {
                **variants[0]["properties"],
                "status": {"type": "string", "enum": ["conflicted"]},
                "evidence": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/evidence_ref"},
                    "minItems": 1,
                    "maxItems": 8,
                },
            },
        }
    )
    additions = {
        "call_map": call_map,
        "speakers": {
            "type": "array",
            "maxItems": 16,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "speaker_id": {"type": "string"},
                    "spoken_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "role": {"type": "string", "enum": ["you", "salesperson", "prospect", "other"]},
                    "evidence_segment_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 5,
                    },
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                },
                "required": [
                    "speaker_id",
                    "spoken_name",
                    "role",
                    "evidence_segment_ids",
                    "confidence",
                ],
            },
        },
        "sensitive_segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "segment_id": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["SENSITIVE_FINANCIAL", "SENSITIVE_LEGAL"],
                    },
                },
                "required": ["segment_id", "category"],
            },
        },
    }
    schema["properties"].update(additions)
    schema["required"].extend(additions)
    _bound_v7_schema(schema)
    return schema


def _bound_v7_schema(schema: dict[str, Any]) -> None:
    """Tighten only the fresh v7 wire tree; B1 and legacy revisions stay canonical."""
    string_limits = {
        "summary": 300,
        "verdict": 300,
        "title": 60,
        "explanation": 240,
        "observation": 240,
        "segment_id": 16,
        "speaker_id": 16,
        "raised_by": 16,
        "id": 16,
        "addressed_by": 16,
        "evidence_segment_ids": 16,
        "spoken_name": 40,
        "quote": 64,
        "due_text": 60,
        "next_step_when": 60,
        "label": 60,
        "unit": 12,
    }

    def bound(node: Any, field: str = "") -> None:
        if not isinstance(node, dict):
            return
        if node.get("type") == "string":
            maximum = (
                max(map(len, node["enum"])) if "enum" in node else string_limits.get(field, 120)
            )
            node["maxLength"] = min(node.get("maxLength", maximum), maximum)
        if node.get("type") == "array":
            node["maxItems"] = max(node.get("minItems", 0), min(node.get("maxItems", 2), 2))
            bound(node["items"], field)
        if node.get("type") == "integer":
            node["maximum"] = min(node.get("maximum", 2147483647), 2147483647)
        if node.get("type") == "number":
            node.update(minimum=0, maximum=float_info.max)
        for key, child in node.get("properties", {}).items():
            bound(child, key)
        for child in node.get("anyOf", []):
            bound(child, field)
        for child in node.get("$defs", {}).values():
            bound(child)

    bound(schema)
    defs = schema["$defs"]
    # Direct IDs avoid repeating offset pairs throughout the completion.
    defs["evidence_ref"] = defs["evidence_ref"]["anyOf"][0]
    for name, text_limit in {
        "PitchItem": 120,
        "Pain": 120,
        "Claim": 160,
        "ProspectTask": 120,
        "SellerTask": 120,
        "Objection": 120,
        "ProspectFact": 80,
        "Signal": 80,
    }.items():
        defs["call_map_" + name]["properties"]["text"]["maxLength"] = text_limit
    for key, maximum in {
        "strengths": 1,
        "improvements": 1,
        "missed_opportunities": 1,
        "objection_analysis": 1,
        "closing_analysis": 1,
        "speakers": 16,
        "sensitive_segments": 12,
    }.items():
        schema["properties"][key]["maxItems"] = maximum
    call_map = schema["properties"]["call_map"]["properties"]
    for key, maximum in {
        "speakers": 16,
        "phases": 8,
        "qualification_gaps": 5,
        "qualification_confirmed": 5,
        "prospect_facts": 2,
        "pitch_items": 1,
        "pains": 1,
        "money": 1,
        "prospect_tasks": 1,
        "seller_tasks": 1,
        "objections": 1,
    }.items():
        call_map[key]["maxItems"] = maximum
    for name in (
        "PitchItem",
        "Pain",
        "Money",
        "ProspectTask",
        "SellerTask",
        "QualificationConfirmed",
        "ProspectFact",
    ):
        defs["call_map_" + name]["properties"]["evidence"]["maxItems"] = 1
    schema["properties"]["speakers"]["items"]["properties"]["evidence_segment_ids"]["maxItems"] = 1
    defs["business_impact"]["properties"]["missing_inputs"]["maxItems"] = 1
    defs["source_note"]["properties"]["evidence"]["maxItems"] = 1
    defs["ethics_note"] = deepcopy(defs["source_note"])
    defs["ethics_note"]["properties"]["evidence"]["maxItems"] = 2
    overview = defs["overview"]["properties"]
    overview["ethics_notes"].update(maxItems=2, items={"$ref": "#/$defs/ethics_note"})
    for key in ("golden_moments", "prospect_interpretations", "rewatch"):
        overview[key]["maxItems"] = 1
    for key, findings in {
        "strength_details": "strengths",
        "improvement_details": "improvements",
        "missed_details": "missed_opportunities",
    }.items():
        overview[key]["maxItems"] = schema["properties"][findings]["maxItems"]
    for name in ("strength_detail", "improvement_detail", "missed_detail"):
        defs[name]["properties"]["finding_index"]["maximum"] = 0
    defs["call_map_TimePromise"]["properties"]["promised_ms"].update(
        minimum=60000, maximum=14400000
    )


def coaching_v7_bounds_instruction() -> str:
    """State every local wire limit in the prompt without changing provider schemas."""
    groups: dict[tuple[str, int], set[str]] = {}

    def visit(node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        for keyword, unit in (("maxLength", "characters"), ("maxItems", "items")):
            if keyword in node:
                groups.setdefault((unit, node[keyword]), set()).add(path)
        for key, child in node.get("properties", {}).items():
            visit(child, f"{path}.{key}")
        if "items" in node:
            visit(node["items"], path + "[]")
        for index, child in enumerate(node.get("anyOf", [])):
            visit(child, f"{path}.option{index}")

    schema = coaching_response_json_schema(_COACHING_V7)
    visit(schema, "report")
    for key, node in schema["$defs"].items():
        visit(node, key)
    return (
        "V7 WIRE LIMITS (bounds, not quotas): "
        + " ".join(
            f"At most {maximum} {unit}: {', '.join(sorted(paths))}."
            for (unit, maximum), paths in sorted(groups.items())
        )
        + " Integers are at most 2147483647; monetary amounts are finite nonnegative "
        "binary64 values. "
    )


def coaching_response_json_schema(revision: str = _COACHING_V4) -> dict[str, Any]:
    """Return a fresh Gemini-compatible schema for a detailed C5 response.

    The returned tree uses only the responseJsonSchema subset supported by the
    Gemini adapter.  Every object is closed.  Evidence references deliberately
    contain only a segment selector or a bounded source-text offset pair; the
    server resolves those references to quote and timing fields.
    """

    if revision == _COACHING_V7:
        return _coaching_v7_schema()
    if revision not in {_COACHING_V4, _COACHING_V5, _COACHING_V6}:
        raise ValueError("coaching_schema_revision_invalid")

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
    dimension_properties = {
        "dimension_id": {"type": "string", "enum": list(_DIMENSION_IDS)},
        "status": {"type": "string", "enum": list(_DIMENSION_STATES)},
        "observation": {"type": "string"},
    }
    if revision in {_COACHING_V5, _COACHING_V6}:
        # JSON Schema's anyOf keeps the status-dependent evidence rule in the
        # local validation schema. The Gemini generation schema below removes
        # cardinality hints, so the report parser independently enforces it.
        observed_dimension = obj(
            {
                **dimension_properties,
                "status": {"type": "string", "enum": ["observed", "conflicted"]},
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, min_items=1, max_items=8),
            },
            ("dimension_id", "status", "observation", "evidence"),
        )
        unknown_dimension = obj(
            {
                **dimension_properties,
                "status": {
                    "type": "string",
                    "enum": ["insufficient_evidence", "not_applicable", "unknown"],
                },
                "evidence": arr({"$ref": "#/$defs/evidence_ref"}, max_items=8),
            },
            ("dimension_id", "status", "observation", "evidence"),
        )
        defs["dimension"] = {"anyOf": [observed_dimension, unknown_dimension]}
    else:
        defs["dimension"] = obj(
            dimension_properties,
            ("dimension_id", "status", "observation"),
        )
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


def coaching_generation_json_schema(revision: str = _COACHING_V4) -> dict[str, Any]:
    """Describe wire shape while leaving numeric/cardinality validation local."""
    local_bounds = {"minItems", "maxItems", "minimum", "maximum"}
    if revision == _COACHING_V7:
        local_bounds |= {"minLength", "maxLength", "pattern"}

    def shape(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: shape(item) for key, item in value.items() if key not in local_bounds}
        if isinstance(value, list):
            return [shape(item) for item in value]
        return value

    return shape(coaching_response_json_schema(revision))  # type: ignore[no-any-return]


__all__ = ["coaching_response_json_schema", "coaching_generation_json_schema"]
