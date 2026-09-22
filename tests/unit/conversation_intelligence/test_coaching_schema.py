"""Contract tests for the provider-facing detailed coaching schema."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast, get_args

import pytest

from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.report_overview import (
    OVERVIEW_VERSION,
    BusinessImpact,
    CallDiagnosis,
    ConversationChange,
    DetailedOverview,
    FinalAssessment,
    GoldenMoment,
    ImprovementDetail,
    MissedDetail,
    NextCallFocus,
    ObservedOutcome,
    PracticeDrill,
    ProspectInterpretation,
    RewatchMoment,
    SourceNote,
    StrengthDetail,
)

PROFILE = (
    Path(__file__).parents[3]
    / "packages/python/ac_platform/conversation_intelligence/profiles/dipak_report_v1.json"
)
SUPPORTED_KEYS = {
    "$defs",
    "$ref",
    "type",
    "enum",
    "items",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "anyOf",
    "properties",
    "additionalProperties",
    "required",
}


def _valid_response() -> dict[str, Any]:
    evidence = [
        {"segment_id": "s1"},
        {"segment_id": "s2", "quote_start": 0, "quote_end": 5},
    ]
    finding = {
        "title": "A grounded finding",
        "explanation": "The source supports this observation.",
        "evidence": evidence,
    }
    source_note = {"text": "A source-bound note.", "evidence": evidence[:1]}
    overview: dict[str, Any] = {
        "version": OVERVIEW_VERSION,
        "diagnosis": source_note,
        "outcome": None,
        "business_impact": None,
        "strength_details": [],
        "improvement_details": [],
        "golden_moments": [],
        "missed_details": [],
        "prospect_interpretations": [],
        "rewatch": [],
        "conversation_change": None,
        "ethics_notes": [],
        "next_call_focus": None,
        "practice": None,
        "progress": None,
        "final_assessment": {
            "repeat": "Repeat the supported behavior.",
            "fix_first": "Clarify the next step.",
            "next_focus": "Ask one grounded follow-up.",
            "assessment": "A qualitative draft with bounded evidence.",
        },
    }
    return {
        "summary": "A bounded qualitative summary.",
        "strengths": [finding],
        "improvements": [],
        "missed_opportunities": [],
        "objection_analysis": [copy.deepcopy(finding)],
        "closing_analysis": [],
        "verdict": "Continue with human review.",
        "review_status": "draft_not_dipak_adjudicated",
        "dimensions": [
            {
                "dimension_id": dimension_id,
                "status": "unknown",
                "observation": "Insufficient evidence in this synthetic response.",
            }
            for dimension_id in _dimension_ids()
        ],
        "overview": overview,
    }


def _dimension_ids() -> tuple[str, ...]:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    return tuple(dimension["id"] for dimension in profile["dimensions"])


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    reference = schema.get("$ref")
    if reference is None:
        return schema
    assert reference.startswith("#/$defs/")
    return cast(dict[str, Any], root["$defs"][reference.removeprefix("#/$defs/")])


def _validate(value: Any, schema: dict[str, Any], root: dict[str, Any]) -> None:
    schema = _resolve(schema, root)
    alternatives = schema.get("anyOf")
    if alternatives is not None:
        errors = []
        for alternative in alternatives:
            try:
                _validate(value, alternative, root)
                return
            except AssertionError as error:
                errors.append(str(error))
        raise AssertionError(f"no anyOf branch accepted {value!r}: {errors}")
    expected = schema.get("type")
    if expected == "object":
        assert isinstance(value, dict), value
        for key in schema["required"]:
            assert key in value, key
        if schema["additionalProperties"] is False:
            assert set(value).issubset(schema["properties"]), set(value)
        for key, child in value.items():
            _validate(child, schema["properties"][key], root)
    elif expected == "array":
        assert isinstance(value, list), value
        assert len(value) >= schema.get("minItems", 0), value
        assert len(value) <= schema.get("maxItems", len(value)), value
        for item in value:
            _validate(item, schema["items"], root)
    elif expected == "string":
        assert isinstance(value, str), value
    elif expected == "integer":
        assert type(value) is int, value
        assert value >= schema.get("minimum", value), value
        assert value <= schema.get("maximum", value), value
    elif expected == "null":
        assert value is None, value
    else:
        raise AssertionError(f"unsupported schema type {expected!r}")
    if "enum" in schema:
        assert value in schema["enum"], value


def _assert_invalid(value: Any) -> None:
    with pytest.raises(AssertionError):
        schema = coaching_response_json_schema()
        _validate(value, schema, schema)


def test_detailed_response_accepts_full_required_wire_shape() -> None:
    schema = coaching_response_json_schema()
    _validate(_valid_response(), schema, schema)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("closing_analysis"),
        lambda value: value.update({"source_sha256": "not-a-wire-field"}),
        lambda value: value["overview"].pop("missed_details"),
        lambda value: value["strengths"][0]["evidence"][0].update({"quote": "generated"}),
        lambda value: value["strengths"][0]["evidence"][1].update({"quote_end": 0}),
        lambda value: value["overview"].update(
            {"business_impact": {"status": "insufficient_data", "estimate": 5}}
        ),
        lambda value: value["dimensions"][0].update({"dimension_id": "invented"}),
    ],
)
def test_detailed_response_rejects_omissions_extras_and_unsafe_evidence(
    mutate: Callable[[dict[str, Any]], Any],
) -> None:
    value = _valid_response()
    mutate(value)
    _assert_invalid(value)


def test_schema_is_fresh_closed_and_parity_bound() -> None:
    first = coaching_response_json_schema()
    second = coaching_response_json_schema()
    assert first == second
    first["properties"]["summary"]["type"] = "integer"
    assert second["properties"]["summary"]["type"] == "string"
    assert second["$defs"]["dimension"]["properties"]["dimension_id"]["enum"] == list(
        _dimension_ids()
    )
    assert set(second["required"]) == {
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
    }
    assert "business_impact" not in second["$defs"]["overview"]["required"]


@pytest.mark.parametrize(
    ("schema_name", "model"),
    [
        ("source_note", SourceNote),
        ("call_diagnosis", CallDiagnosis),
        ("outcome", ObservedOutcome),
        ("business_impact", BusinessImpact),
        ("strength_detail", StrengthDetail),
        ("improvement_detail", ImprovementDetail),
        ("golden_moment", GoldenMoment),
        ("missed_detail", MissedDetail),
        ("prospect_interpretation", ProspectInterpretation),
        ("rewatch", RewatchMoment),
        ("conversation_change", ConversationChange),
        ("next_call_focus", NextCallFocus),
        ("practice", PracticeDrill),
        ("final_assessment", FinalAssessment),
        ("overview", DetailedOverview),
    ],
)
def test_overview_defs_match_canonical_model_fields_and_bounds(
    schema_name: str, model: type[Any]
) -> None:
    schema = coaching_response_json_schema()["$defs"][schema_name]
    fields = model.model_fields
    assert set(schema["properties"]) == set(fields)
    assert set(schema["required"]) == {
        name for name, field in fields.items() if field.is_required()
    }
    for name, field in fields.items():
        max_length = next(
            (
                metadata.max_length
                for metadata in field.metadata
                if getattr(metadata, "max_length", None) is not None
            ),
            None,
        )
        property_schema = schema["properties"][name]
        if property_schema.get("type") == "array" and max_length is not None:
            assert property_schema["maxItems"] == max_length


@pytest.mark.parametrize(
    ("schema_name", "field_name", "model"),
    [
        ("overview", "version", DetailedOverview),
        ("outcome", "kind", ObservedOutcome),
        ("business_impact", "status", BusinessImpact),
        ("prospect_interpretation", "interpretation_kind", ProspectInterpretation),
        ("rewatch", "purpose", RewatchMoment),
        ("conversation_change", "interpretation_kind", ConversationChange),
    ],
)
def test_overview_defs_preserve_canonical_literal_enums(
    schema_name: str, field_name: str, model: type[Any]
) -> None:
    annotation = model.model_fields[field_name].annotation
    assert get_args(annotation)
    assert coaching_response_json_schema()["$defs"][schema_name]["properties"][field_name][
        "enum"
    ] == list(get_args(annotation))


def test_overview_defs_preserve_canonical_nullability() -> None:
    schema = coaching_response_json_schema()["$defs"]["overview"]
    fields = DetailedOverview.model_fields
    for name, field in fields.items():
        property_schema = schema["properties"][name]
        nullable = type(None) in get_args(field.annotation) or field.annotation is type(None)
        if field.annotation is type(None):
            assert property_schema == {"type": "null"}
        elif nullable:
            assert any(branch.get("type") == "null" for branch in property_schema["anyOf"])
        else:
            assert "anyOf" not in property_schema


def test_schema_uses_only_supported_keywords_and_closes_every_object() -> None:
    schema = coaching_response_json_schema()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            assert set(value).issubset(SUPPORTED_KEYS), set(value) - SUPPORTED_KEYS
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
            for child in value.get("$defs", {}).values():
                visit(child)
            for child in value.get("properties", {}).values():
                visit(child)
            for key, child in value.items():
                if key not in {"$defs", "properties"}:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
