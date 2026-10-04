"""Offline v7 candidate contracts; fictional canary dialogue, no provider calls."""

import hashlib
import json
import re
from copy import deepcopy
from uuid import uuid4

import pytest

from ac_platform.conversation_intelligence import reports
from ac_platform.conversation_intelligence.call_map import (
    SIGNALS_PATH,
    check_call_map,
    dimension_state_ceiling,
)
from ac_platform.conversation_intelligence.checkpoints import content_hash
from ac_platform.conversation_intelligence.coaching_schema import (
    coaching_generation_json_schema,
    coaching_response_json_schema,
)
from ac_platform.conversation_intelligence.coaching_validation_gate import (
    coaching_revision_runtime_block,
)
from ac_platform.conversation_intelligence.inference_tasks import prepare_coaching_input
from ac_platform.conversation_intelligence.qualitative_pack import (
    load_qualitative_pack_for_revision,
)
from ac_platform.conversation_intelligence.reporting_pipeline import StageRequest
from tests.unit.conversation_intelligence.test_call_map import _call_map, _segments
from tests.unit.conversation_intelligence.test_coaching_schema import _valid_response
from tests.unit.conversation_intelligence.test_coaching_v6_integration import _fixture


def validate_schema(value, schema, root=None):
    """Check the generated JSON Schema subset independently of report parsing."""
    root = schema if root is None else root
    if "$ref" in schema:
        return validate_schema(value, root["$defs"][schema["$ref"].split("/")[-1]], root)
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                validate_schema(value, branch, root)
                return
            except AssertionError:
                pass
        raise AssertionError("No schema variant accepted the fictional value")
    kind = schema["type"]
    if kind == "object":
        assert isinstance(value, dict)
        assert set(schema["required"]) <= value.keys()
        if schema.get("additionalProperties") is False:
            assert value.keys() <= schema["properties"].keys()
        for key, child in value.items():
            validate_schema(child, schema["properties"][key], root)
    elif kind == "array":
        assert isinstance(value, list)
        assert schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", len(value))
        for child in value:
            validate_schema(child, schema["items"], root)
    elif kind == "string":
        assert isinstance(value, str)
        assert schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", len(value))
        assert "pattern" not in schema or re.search(schema["pattern"], value)
    elif kind in {"integer", "number"}:
        assert type(value) in ({int} if kind == "integer" else {int, float})
        assert schema.get("minimum", value) <= value <= schema.get("maximum", value)
    elif kind == "null":
        assert value is None
    else:
        raise AssertionError(kind)
    assert "enum" not in schema or value in schema["enum"]


def v7_response():
    response = _valid_response()
    response["call_map"] = _call_map()
    response["speakers"] = [
        {
            "speaker_id": row["speaker_id"],
            "spoken_name": None,
            "role": "salesperson" if row["role"] == "seller" else row["role"],
            "evidence_segment_ids": [
                next(s["id"] for s in _segments() if s["speaker_id"] == row["speaker_id"])
            ],
            "confidence": "low",
        }
        for row in response["call_map"]["speakers"]
    ]
    response["sensitive_segments"] = []
    for dimension in response["dimensions"]:
        dimension["evidence"] = []
    response["overview"]["golden_moments"] = [
        {"evidence": [{"segment_id": "s1"}], "why_effective": "You asked permission first."}
    ]
    return response


@pytest.mark.parametrize(
    "provider,model", [("gemini", "gemini-3.8-flash"), ("openai", "gpt-6-luna")]
)
def test_v7_uses_frozen_names_free_roles_without_changing_source_or_legacy(provider, model):
    transcript, packet = _fixture()
    role_ids = sorted({s["speaker_id"] for s in transcript["segments"]} - {"unattributed"})
    snapshot = {
        "origin": "text_predicted_roles",
        "transcript_revision": transcript["revision"],
        "map_revision": "a" * 64,
        "speakers": [
            {"speaker_id": speaker_id, "role": "other", "is_account_holder": False}
            for speaker_id in role_ids
        ],
    }
    pack = load_qualitative_pack_for_revision("coaching-v7")
    options = dict(
        provider=provider,
        model=model,
        max_completion_tokens=8000,
        qualitative_pack_sha256=pack.sha256,
    )
    before = deepcopy((transcript, packet, snapshot))
    request = StageRequest(
        stage="C5",
        transcript_checkpoint_id=uuid4(),
        fact_checkpoint_ids=(uuid4(),),
        coaching_prompt_revision="coaching-v7",
        report_language="en",
        speaker_roles=snapshot,
        **options,
    )
    task = prepare_coaching_input(
        transcript,
        [packet],
        speaker_roles=request.speaker_roles,
        coaching_prompt_revision=request.coaching_prompt_revision,
        **options,
    )
    assert type(task).from_dict(task.as_dict(), payload=task.payload) == task
    body = task.as_provider_body()
    user = body["contents"][0]["parts"][0]["text"] if provider == "gemini" else body["input"]
    assert json.loads(user.split("\n", 1)[1])["source_context"]["speaker_roles"] == snapshot
    assert (transcript, packet, snapshot) == before
    legacy = prepare_coaching_input(
        transcript, [packet], coaching_prompt_revision="coaching-v6", **options
    )
    assert legacy.input_sha256 != task.input_sha256
    assert pack == load_qualitative_pack_for_revision("coaching-v6")
    assert frozenset({"coaching-v7"}) == reports.SPEAKER_ROLE_PROMPT_REVISIONS


def test_v7_prompt_contains_honest_report_and_owner_amendments():
    transcript, packet = _fixture()
    prompt = reports.build_report_groq_prompt(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision="coaching-v7",
        qualitative_pack_sha256=load_qualitative_pack_for_revision("coaching-v7").sha256,
    )
    system = prompt["messages"][0]["content"]
    for rule in [
        "HEU-03",
        "judge only stages that happened",
        "no close penalty",
        "not_applicable",
        "what to ask next time",
        "atomic claims",
        "own 1-2 segment refs",
        "partial needs one",
        "Every qualification item is a gap",
        "budget gap plus affordability_gap",
        "seller_error: term",
        "Every unverifiable claim",
        "at most 20 words",
        "prospect's own words",
        "never convert a spoken date",
        "answer_fit",
        "seller_tasks",
        "objections",
        "frozen names-free",
        "is_account_holder",
        "profile-match gate",
        "spoken_name",
        "literally after normalization",
        "confidence low/medium/high",
        "no numeric confidence",
        "sensitive_terms_v1",
        "informal books",
        "undeclared income",
        "Ordinary business figures stay BIZ-03",
    ]:
        assert rule in system, rule
    assert "strength_index" not in system and "evidence_index" not in system
    assert reports.COACHING_PROMPT_V6_MARKER not in system
    assert hashlib.sha256(SIGNALS_PATH.read_bytes()).hexdigest() in system
    signals = json.loads(SIGNALS_PATH.read_bytes())
    assert all(
        kind in system for key in ("forward", "risk", "objection_kinds") for kind in signals[key]
    )


def test_first_meeting_is_applicable_to_discovery_without_a_close_penalty():
    response = v7_response()
    call_map = response["call_map"]
    call_map["phases"] = [
        {"name": "opening", "start_ms": 0},
        {"name": "discovery", "start_ms": 5000},
    ]
    for key in (
        "pitch_items",
        "pains",
        "money",
        "claims",
        "signals",
        "qualification_confirmed",
        "prospect_tasks",
        "seller_tasks",
        "objections",
    ):
        call_map[key] = []
    call_map["qualification_gaps"] = ["budget", "timeline", "decision_maker", "authority", "need"]
    call_map["outcome"] = {
        "kind": "none",
        "next_step_rung": "none",
        "next_step_when": None,
        "evidence": [],
    }
    response["closing_analysis"] = []
    for dimension in response["dimensions"]:
        if dimension["dimension_id"] == "closing_decision_management":
            dimension.update(
                status="not_applicable",
                observation="Next time, ask which step you should discuss.",
                evidence=[],
            )
    validate_schema(response, coaching_response_json_schema("coaching-v7"))
    assert check_call_map(call_map, _segments(), max(s["end_ms"] for s in _segments())) == []
    assert dimension_state_ceiling("not_applicable", []) == "not_applicable"
    assert dimension_state_ceiling("observed", [{"segment_id": "s1"}]) == "partial"


def test_owner_fields_and_sensitive_closed_categories_accept_literal_fictional_data():
    response = v7_response()
    prospect = next(
        row
        for row in _segments()
        if row["speaker_id"]
        == next(
            s["speaker_id"] for s in response["call_map"]["speakers"] if s["role"] == "prospect"
        )
    )
    words = " ".join(prospect["text"].split()[:8])
    response["call_map"]["prospect_facts"] = [
        {
            "key": "company",
            "text": words,
            "evidence": [{"segment_id": prospect["id"], "quote": words}],
        }
    ]
    response["call_map"]["outcome"]["next_step_when"] = "next Tuesday"
    response["sensitive_segments"] = [
        {"segment_id": "s1", "category": "SENSITIVE_FINANCIAL"},
        {"segment_id": "s2", "category": "SENSITIVE_LEGAL"},
    ]
    validate_schema(response, coaching_response_json_schema("coaching-v7"))
    assert response["call_map"]["outcome"]["next_step_when"] == "next Tuesday"
    assert set(response["sensitive_segments"][0]) == {"segment_id", "category"}


@pytest.mark.parametrize(
    "mutation",
    [
        None,
        "index_golden",
        "three_claim_refs",
        "bad_answer_fit",
        "numeric_confidence",
        "call_type",
        "sensitive_quote",
        "sensitive_category",
        "one_observed_ref",
        "two_partial_refs",
    ],
)
def test_v7_schema_accepts_direct_evidence_and_rejects_invalid_amendments(mutation):
    response = v7_response()
    if mutation == "index_golden":
        response["overview"]["golden_moments"] = [
            {"strength_index": 0, "evidence_index": 0, "why_effective": "Permission."}
        ]
    elif mutation == "three_claim_refs":
        claim = response["call_map"]["claims"][0]
        claim["evidence"] = claim["evidence"] * 3
    elif mutation == "bad_answer_fit":
        response["call_map"]["pains"][0]["answer_fit"] = "perfect"
    elif mutation == "numeric_confidence":
        response["speakers"][0]["confidence"] = 0.9
    elif mutation == "call_type":
        response["call_type"] = "first_meeting"
    elif mutation in {"sensitive_quote", "sensitive_category"}:
        entry = {"segment_id": "s1", "category": "SENSITIVE_FINANCIAL"}
        if mutation == "sensitive_quote":
            entry["quote"] = "Private words"
        else:
            entry["category"] = "BIZ-03"
        response["sensitive_segments"] = [entry]
    elif mutation in {"one_observed_ref", "two_partial_refs"}:
        response["dimensions"][0].update(
            status="observed" if mutation == "one_observed_ref" else "partial",
            evidence=[{"segment_id": "s1"}] * (1 if mutation == "one_observed_ref" else 2),
        )
    schema = coaching_response_json_schema("coaching-v7")
    if mutation:
        with pytest.raises(AssertionError):
            validate_schema(response, schema)
    else:
        validate_schema(response, schema)
        validate_schema(response, coaching_generation_json_schema("coaching-v7"))


@pytest.mark.parametrize("revision", ["coaching-v6", "coaching-v7"])
def test_candidate_revisions_remain_fail_closed(revision):
    assert "AC-SVAL-01 Gate 2" in coaching_revision_runtime_block(revision)
    assert coaching_revision_runtime_block("coaching-v5") is None


@pytest.mark.parametrize(
    "revision,prompt_hash,response_hash,generation_hash",
    [
        (
            "coaching-v4",
            "c88673a45016c2c6a14bae7fdab9dc18fab2df74ea97de1aeb14769850af25a2",
            "cf738359daf55c908b5e0ab664761fd0339f2043583d3a3e17ac85fd07b81cf1",
            "aad4ed620fa69ebb51a6fe91b0fd34a1a3a28aed6fd85e21cf10d6c77718a907",
        ),
        (
            "coaching-v5",
            "fa3c363ef37a2c8001af0422442e729d1dd343d3cdb37c6b4abb3e5b904e2e3a",
            "78825a2d1ba2b7feb90177a37b204a336e0d2b6de2145c080f0bf621033c7fb4",
            "3d3219edb621932df1d87d069876d1d92f2319c52127b5a39593743de7688c2e",
        ),
        (
            "coaching-v6",
            "35646da59e54909dbfabba412311454076fad2093856417a084b9ac71a222494",
            "78825a2d1ba2b7feb90177a37b204a336e0d2b6de2145c080f0bf621033c7fb4",
            "3d3219edb621932df1d87d069876d1d92f2319c52127b5a39593743de7688c2e",
        ),
    ],
)
def test_v4_v6_bytes_match_pre_change_main_pin(
    revision, prompt_hash, response_hash, generation_hash
):
    transcript, packet = _fixture()
    prompt = reports.build_report_groq_prompt(
        transcript,
        [packet],
        provider="gemini",
        model="gemini-3.8-flash",
        max_completion_tokens=8000,
        coaching_prompt_revision=revision,
        qualitative_pack_sha256=load_qualitative_pack_for_revision(revision).sha256,
    )
    assert content_hash(prompt) == prompt_hash
    assert content_hash(coaching_response_json_schema(revision)) == response_hash
    assert content_hash(coaching_generation_json_schema(revision)) == generation_hash
